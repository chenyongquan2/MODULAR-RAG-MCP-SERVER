"""金标标注的候选池化 (change retriever-agnostic-golden-labels T-2.1 / T-2.2)。

## 这个模块解决什么问题

第一代金标的 ``expected_chunk_ids`` 由 ``scripts/backfill_chunk_ids.py`` 回填:
把 ``ground_truth``(答案文本)编码成向量,在向量库里查 dense top-5,过相似度
阈值后写入。也就是说 —— **标准答案就是「embedding 模型认为最像答案的那 5 条」**。

后果是所有召回类指标都锚定在 dense 这一条路径上:那条路径永远「全对」,其他
路径找到的正确结果连进入标准答案的机会都没有。2026-08-13 的重排 A/B 把这个
问题暴露到了台面上 —— cross-encoder 让英文金标 MRR 从 0.4914 掉到 0.3668,
而同一个模型在集成测试里,把**故意放在末位**(原始分数最低)的相关段落**每次
都提到首位**。模型在做正确的事,指标却在跌,因为重排的全部工作就是不同意
第一阶段的排序,而标准答案正是第一阶段的输出。

## 池化(pooling)是怎么解决的

候选来自 dense、sparse(BM25)、重排后顺序**三路各自 top-N 的并集**。这是信息
检索领域的标准做法(TREC 式 pooling):每条路径都有机会把自己认为相关的东西送进
池子,于是没有任何一路能垄断标准答案。判定相关性的活儿交给 LLM(见
``chunk_labeler``),池化只负责「把候选空间铺开」。

## 两个关键设计点

1. **用 ``query`` 而非 ``ground_truth`` 作检索输入**。第一代用答案去检索,那是
   「找像答案的段落」;而评估时系统面对的是 query。用 query 池化才能覆盖真实
   检索会看到的候选空间。``ground_truth`` 仍然要用 —— 作为判定阶段给 LLM 的
   参考答案。

2. **不调 ``HybridSearch.search()``**。融合已经把三路揉成一个排序,拿不到「这条
   是谁贡献的」,而记录贡献来源是硬要求(它是判断「池化到底有没有起作用」的唯一
   依据,见 ``dense_jaccard``)。所以这里直接用三个组件各自取 top-N。

不在查询链路上,是离线标注工具。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence

from src.observability.logger import get_logger

if TYPE_CHECKING:
    from src.core.settings import Settings
    from src.core.types import RetrievalResult

logger = get_logger(__name__)


# 三条召回路径的名字。作为 contributed_by 的取值域,集中定义以免各处散落字面量。
ROUTE_DENSE = "dense"
ROUTE_SPARSE = "sparse"
ROUTE_RERANK = "rerank"


@dataclass
class PooledCandidate:
    """候选池中的一个 chunk。

    Attributes:
        chunk_id: chunk 唯一标识。
        text: chunk 正文,判定阶段要把它交给 LLM。
        contributed_by: 哪几路召回把它送进了池子。**这个字段是本变更能否自证
            有效的关键** —— 若产出里所有候选都只由 dense 贡献,说明池化没起
            作用,新方法退化成了第一代。
        best_rank: 该 chunk 在各贡献路径中的最好名次(1-based)。仅用于诊断与
            稳定排序,**不参与相关性判定** —— 用名次决定相关性正是要摆脱的东西。
    """

    chunk_id: str
    text: str
    contributed_by: List[str] = field(default_factory=list)
    best_rank: int = 0


@dataclass
class PoolResult:
    """一次池化的产出。

    Attributes:
        candidates: 去重后的候选列表。
        route_counts: 各路各自召回了多少条(去重前)。某路为 0 表示它这次没贡献。
        dense_top_k_ids: 纯 dense 的前若干条,用于算 ``dense_jaccard``。
        errors: 各路的失败原因(路径名 -> 错误消息)。某路失败不阻断池化。
    """

    candidates: List[PooledCandidate] = field(default_factory=list)
    route_counts: Dict[str, int] = field(default_factory=dict)
    dense_top_k_ids: List[str] = field(default_factory=list)
    errors: Dict[str, str] = field(default_factory=dict)


def dense_jaccard(labeled_ids: Sequence[str], dense_top_k_ids: Sequence[str]) -> float:
    """算「标注结果」与「纯 dense top-K」的 Jaccard 相似度。

    这是本变更的**自检指标**:如果新方法产出的标准答案与第一代的纯 dense top-K
    高度重合,说明池化或判定其实没起作用 —— 新方法在形式上换了,实质上还是
    dense-anchored。这种失效**不会有任何报错**,只会让人以为问题已经修好了,
    所以必须显式量出来。

    两个都为空时返回 0.0(而不是 1.0):空集与空集"完全重合"在这里是无意义的
    巧合,报 1.0 会触发一个误导性的告警。

    Args:
        labeled_ids: 判定为相关的 chunk id。
        dense_top_k_ids: 纯 dense 检索的前 K 条 chunk id。

    Returns:
        Jaccard 相似度 ``|A∩B| / |A∪B|``,范围 [0.0, 1.0]。
    """
    a = set(labeled_ids)
    b = set(dense_top_k_ids)
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def check_dense_overlap(
    labeled_ids: Sequence[str],
    dense_top_k_ids: Sequence[str],
    threshold: float,
) -> Optional[str]:
    """重合度超阈值时生成告警文本,否则返回 None。

    **告警不阻断产出** —— 它是需要人看的信号,不是错误。可能的原因有好几种
    (语料本身 dense 就够用、判定模型过于保守、池化配置退化成单路),都需要人
    结合上下文判断,程序无法自动区分。

    Args:
        labeled_ids: 判定为相关的 chunk id。
        dense_top_k_ids: 纯 dense 检索的前 K 条 chunk id。
        threshold: Jaccard 上限,来自 ``evaluation.labeling.dense_overlap_warn``。

    Returns:
        告警文本,或 None(未超阈值)。
    """
    score = dense_jaccard(labeled_ids, dense_top_k_ids)
    if score <= threshold:
        return None
    return (
        f"labeled chunks overlap with pure-dense top-{len(dense_top_k_ids)} at "
        f"Jaccard={score:.3f} (> {threshold}). The pooled + LLM-judged labels are "
        "nearly identical to what the first-generation dense-only backfill would "
        "have produced, so this run may not have removed the dense anchoring it "
        "exists to remove. Check: (a) are at least two pool routes actually "
        "returning results, (b) is the judge rejecting anything at all, "
        "(c) or is dense genuinely sufficient for this corpus?"
    )


class ChunkPooler:
    """把多路召回的结果并成一个候选池。

    三个检索组件通过构造注入,便于测试与替换(宪法原则一:经抽象接口访问,
    不 import 具体实现)。

    Example:
        >>> pooler = ChunkPooler(settings)
        >>> result = pooler.pool("如何配置保证金计算方式？")
        >>> {c.chunk_id: c.contributed_by for c in result.candidates}
    """

    def __init__(
        self,
        settings: Settings,
        dense_retriever: Optional[Any] = None,
        sparse_retriever: Optional[Any] = None,
        reranker: Optional[Any] = None,
        query_processor: Optional[Any] = None,
    ) -> None:
        """构造池化器。

        Args:
            settings: 应用配置,读 ``evaluation.labeling.pool_top_n_*``。
            dense_retriever: 稠密检索器;未提供则自行构造。
            sparse_retriever: 稀疏检索器;未提供则自行构造。
            reranker: 重排器;未提供且启用重排路时自行构造。
            query_processor: 查询预处理器,用于给 sparse 提取关键词;未提供则
                自行构造。**必须走它**而不是自己切词 —— 查询端与索引端的切分
                口径必须共用 ``src/core/text/tokenizer.py``,两端漂移的失败是
                静默的(不报错,只是召回恒为空)。

        Raises:
            ValueError: settings 为 None。
        """
        if settings is None:
            raise ValueError("Settings cannot be None")

        self._settings = settings
        cfg = settings.evaluation.labeling

        self._top_n_dense = cfg.pool_top_n_dense
        self._top_n_sparse = cfg.pool_top_n_sparse
        self._top_n_rerank = cfg.pool_top_n_rerank

        if query_processor is not None:
            self._query_processor = query_processor
        else:
            from src.core.query_engine.query_processor import QueryProcessor

            self._query_processor = QueryProcessor()

        if dense_retriever is not None:
            self._dense_retriever = dense_retriever
        else:
            from src.core.query_engine.dense_retriever import DenseRetriever

            self._dense_retriever = DenseRetriever(settings)

        if sparse_retriever is not None:
            self._sparse_retriever = sparse_retriever
        else:
            from src.core.query_engine.sparse_retriever import SparseRetriever

            self._sparse_retriever = SparseRetriever(settings)

        # 重排路按需构造：pool_top_n_rerank == 0 时不碰它，这样没装
        # optional extra `.[rerank]` 的环境也能正常标注。
        self._reranker = reranker
        if self._reranker is None and self._top_n_rerank > 0:
            from src.core.query_engine.reranker import Reranker

            self._reranker = Reranker(settings)

    def pool(self, query: str) -> PoolResult:
        """对一个 query 做三路池化。

        某一路失败或返回空不会中断流程 —— 标注一轮要跑几十条 case,一路的瞬时
        故障不该让整轮白跑。失败原因记入 ``errors``,由调用方决定是否告警。

        Args:
            query: 问题文本。**用 query 而非 ground_truth**,见模块 docstring。

        Returns:
            去重后的候选池,每个候选带贡献来源。

        Raises:
            ValueError: query 为空。
        """
        if not query or not query.strip():
            raise ValueError("Query cannot be empty")

        result = PoolResult()
        # chunk_id -> PooledCandidate，用于去重时合并 contributed_by
        merged: Dict[str, PooledCandidate] = {}

        dense_results = self._retrieve_dense(query, result)
        self._merge(merged, dense_results, ROUTE_DENSE)
        result.route_counts[ROUTE_DENSE] = len(dense_results)
        result.dense_top_k_ids = [r.chunk_id for r in dense_results]

        sparse_results = self._retrieve_sparse(query, result)
        self._merge(merged, sparse_results, ROUTE_SPARSE)
        result.route_counts[ROUTE_SPARSE] = len(sparse_results)

        rerank_results = self._retrieve_rerank(query, dense_results, sparse_results, result)
        self._merge(merged, rerank_results, ROUTE_RERANK)
        result.route_counts[ROUTE_RERANK] = len(rerank_results)

        # 输出顺序按 best_rank 升序，同名次按 chunk_id 保证确定性 ——
        # 顺序本身不影响判定，但确定的顺序让产出可复现、可 diff。
        result.candidates = sorted(
            merged.values(), key=lambda c: (c.best_rank, c.chunk_id)
        )

        logger.info(
            "pooled %d unique candidates for query %r (dense=%d sparse=%d rerank=%d)",
            len(result.candidates),
            query[:50],
            result.route_counts.get(ROUTE_DENSE, 0),
            result.route_counts.get(ROUTE_SPARSE, 0),
            result.route_counts.get(ROUTE_RERANK, 0),
        )
        return result

    # ── 各路召回 ─────────────────────────────────────────────────────────

    def _retrieve_dense(self, query: str, result: PoolResult) -> List[RetrievalResult]:
        if self._top_n_dense <= 0:
            return []
        try:
            return list(
                self._dense_retriever.retrieve(query, top_k=self._top_n_dense)
            )
        except Exception as exc:  # noqa: BLE001 —— 一路失败不阻断整轮标注
            logger.warning("dense route failed for query %r: %s", query[:50], exc)
            result.errors[ROUTE_DENSE] = str(exc)
            return []

    def _retrieve_sparse(self, query: str, result: PoolResult) -> List[RetrievalResult]:
        if self._top_n_sparse <= 0:
            return []
        try:
            # 关键词必须经 QueryProcessor 提取 —— 它用共享的 tokenizer，
            # 自己切一份会让查询端与索引端口径漂移，而那种失败是静默的。
            processed = self._query_processor.process(query)
            return list(
                self._sparse_retriever.retrieve(
                    processed.keywords, top_k=self._top_n_sparse
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("sparse route failed for query %r: %s", query[:50], exc)
            result.errors[ROUTE_SPARSE] = str(exc)
            return []

    def _retrieve_rerank(
        self,
        query: str,
        dense_results: Sequence[RetrievalResult],
        sparse_results: Sequence[RetrievalResult],
        result: PoolResult,
    ) -> List[RetrievalResult]:
        """重排路:对已召回的候选重新排序,取前 N。

        重排不产生新候选(它只是重新排序),所以这一路的价值在于**改变名次** ——
        被它提到前 N 的 chunk 会因此进池,而在 dense/sparse 各自的 top-N 里可能
        排不进去。这正是「让敢改变名次的路径也有发言权」。
        """
        if self._top_n_rerank <= 0 or self._reranker is None:
            return []

        # 用两路的并集作为重排输入（去重，保持首次出现的顺序）
        seen: set[str] = set()
        candidates: List[RetrievalResult] = []
        for r in list(dense_results) + list(sparse_results):
            if r.chunk_id not in seen:
                seen.add(r.chunk_id)
                candidates.append(r)

        if not candidates:
            return []

        try:
            reranked = self._reranker.rerank(query, candidates)
            return list(reranked)[: self._top_n_rerank]
        except Exception as exc:  # noqa: BLE001
            logger.warning("rerank route failed for query %r: %s", query[:50], exc)
            result.errors[ROUTE_RERANK] = str(exc)
            return []

    # ── 合并去重 ─────────────────────────────────────────────────────────

    @staticmethod
    def _merge(
        merged: Dict[str, PooledCandidate],
        results: Sequence[RetrievalResult],
        route: str,
    ) -> None:
        """把一路的结果并进池子,记录贡献来源与最好名次。

        同一个 chunk 被多路召回时,``contributed_by`` 累加(不覆盖)——
        「dense 和 sparse 都认为它相关」是有信息量的,不能丢。
        """
        for rank, r in enumerate(results, start=1):
            existing = merged.get(r.chunk_id)
            if existing is None:
                merged[r.chunk_id] = PooledCandidate(
                    chunk_id=r.chunk_id,
                    text=r.text,
                    contributed_by=[route],
                    best_rank=rank,
                )
            else:
                if route not in existing.contributed_by:
                    existing.contributed_by.append(route)
                existing.best_rank = min(existing.best_rank, rank)
