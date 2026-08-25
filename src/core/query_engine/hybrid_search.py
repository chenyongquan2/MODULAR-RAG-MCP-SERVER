"""混合检索引擎 (Dense + Sparse + RRF)。

该模块负责编排完整的混合检索流程：
1. 查询预处理（关键词提取、过滤器解析）
2. 并行 Dense 和 Sparse 检索
3. RRF 结果融合
4. 可选的元数据过滤
5. 重排序优化
6. 返回 Top-K 结果

设计原则：
- Pluggable: 各组件可独立替换
- Fail-Fast: 输入验证 + 清晰的错误信息
- Graceful Degradation: 单一检索路径失败时使用另一路径
- Dependency Injection: 组件注入以提高可测试性
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional

from src.core.types import (
    ROUTE_DENSE,
    ROUTE_SPARSE,
    RetrievalResult,
    SearchOutcome,
)

if TYPE_CHECKING:
    from src.core.settings import Settings
    from src.core.query_engine.fusion import Fusion
    from src.core.query_engine.query_processor import QueryProcessor


class HybridSearch:
    """混合检索编排器。

    协调 Dense/Sparse 检索、RRF 融合和重排序的完整流程。

    Example:
        >>> hybrid = HybridSearch(settings)
        >>> results = hybrid.search("How to configure LLM?", top_k=10)
    """

    def __init__(
        self,
        settings: Optional[Settings] = None,
        query_processor: Optional[Any] = None,
        dense_retriever: Optional[Any] = None,
        sparse_retriever: Optional[Any] = None,
        fusion: Optional[Fusion] = None,
        reranker: Optional[Any] = None,
    ) -> None:
        """初始化混合检索引擎。

        Args:
            settings: 应用配置（测试时可为 None）。
            query_processor: 可选的查询预处理器（未提供时自动创建）。
            dense_retriever: 可选的稠密检索器（未提供时自动创建）。
            sparse_retriever: 可选的稀疏检索器（未提供时自动创建）。
            fusion: 可选的融合器（未提供时自动创建）。
            reranker: 可选的重排序器（未提供时自动创建）。

        Note:
            如果 settings 为 None，则所有检索器必须显式提供。
        """
        self._settings = settings

        if query_processor is not None:
            self._query_processor = query_processor
        else:
            from src.core.query_engine.query_processor import QueryProcessor, QueryProcessorConfig
            config = QueryProcessorConfig()
            # 查询改写器由工厂按配置创建（宪法原则一:不 import 具体实现）。
            # settings 为 None 时（纯替身构造的测试场景）走「不改写」。
            query_rewriter = None
            if settings is not None:
                from src.libs.query_rewriter.query_rewriter_factory import (
                    QueryRewriterFactory,
                )

                query_rewriter = QueryRewriterFactory.create(settings)
            self._query_processor = QueryProcessor(
                config=config, query_rewriter=query_rewriter
            )

        if dense_retriever is not None:
            self._dense_retriever = dense_retriever
        else:
            if settings is None:
                raise ValueError("settings must be provided if dense_retriever is not provided")
            from src.core.query_engine.dense_retriever import DenseRetriever
            self._dense_retriever = DenseRetriever(settings)

        if sparse_retriever is not None:
            self._sparse_retriever = sparse_retriever
        else:
            if settings is None:
                raise ValueError("settings must be provided if sparse_retriever is not provided")
            from src.core.query_engine.sparse_retriever import SparseRetriever
            self._sparse_retriever = SparseRetriever(settings)

        if fusion is not None:
            self._fusion = fusion
        else:
            from src.core.query_engine.fusion import Fusion

            # feature-005 T012:从配置构造，不再无参构造。
            # 此前 Fusion() 不读任何配置、k=60 硬编码在 DEFAULT_K，属宪法
            # 原则二禁止的硬编码可调参数。
            if settings is None:
                raise ValueError("settings must be provided if fusion is not provided")
            self._fusion = Fusion(
                k=settings.retrieval.rrf_k,
                weights=settings.retrieval.fusion_weights,
            )

        if reranker is not None:
            self._reranker = reranker
        else:
            if settings is None:
                raise ValueError("settings must be provided if reranker is not provided")
            from src.core.query_engine.reranker import Reranker
            self._reranker = Reranker(settings)

        default_top_k = 20
        if settings is not None:
            default_top_k = getattr(settings.retrieval, "top_k", 20)
        self._default_top_k = default_top_k

    def search(
        self,
        query: str,
        top_k: Optional[int] = None,
        filters: Optional[Dict[str, Any]] = None,
        trace: Optional[Any] = None,
    ) -> List[RetrievalResult]:
        """执行混合检索流程。

        这是检索的**主入口**，签名与返回类型自始未变 —— MCP server 与
        ``scripts/query.py`` 都在用它。需要各路各自的结果时用
        :meth:`search_with_routes`，本方法只是取它的最终结果。

        Args:
            query: 搜索查询文本。
            top_k: 返回结果数量。
            filters: 可选的元数据过滤器。
            trace: 可选的链路追踪上下文。

        Returns:
            按融合分数降序排列的 RetrievalResult 列表。

        Raises:
            ValueError: 如果 query 为空或 top_k 无效。
        """
        return self.search_with_routes(
            query, top_k=top_k, filters=filters, trace=trace
        ).results

    def search_with_routes(
        self,
        query: str,
        top_k: Optional[int] = None,
        filters: Optional[Dict[str, Any]] = None,
        trace: Optional[Any] = None,
    ) -> SearchOutcome:
        """执行混合检索，并把**各路各自的结果**一并返回。

        与 :meth:`search` 是同一条流程 —— 不重跑任何一次检索，只是把融合前
        本就已经拿到的两路结果也交出去（``SearchOutcome.routes``）。

        **为什么要有这个方法**：融合后的指标量不出单路的改善。稀疏路的生效
        权重只有稠密路的十分之一，只作用于稀疏路的改进在融合后几乎看不见，
        于是会被误判为「没有效果」。评估侧需要对每一路分别打分才能看见它。

        为什么不直接改 :meth:`search` 的返回类型：那是无谓的 breaking ——
        MCP server 与 ``scripts/query.py`` 只关心最终结果。

        Args:
            query: 搜索查询文本。
            top_k: 返回结果数量。
            filters: 可选的元数据过滤器。
            trace: 可选的链路追踪上下文。

        Returns:
            SearchOutcome —— ``results`` 是最终结果（与 :meth:`search` 相同），
            ``routes`` 是各路经同样元数据过滤、但**未经融合与重排**的有序结果。

        Raises:
            ValueError: 如果 query 为空或 top_k 无效。
        """
        if not query or not query.strip():
            raise ValueError("Query cannot be empty")

        effective_top_k = top_k if top_k is not None else self._default_top_k

        if effective_top_k <= 0:
            raise ValueError("top_k must be a positive integer")

        # 1) Query 预处理阶段打点
        if trace is not None:
            trace.start_stage("query_processing")

        processed_query = self._query_processor.process(query)
        keywords = processed_query.keywords

        if trace is not None:
            trace.finish_stage(
                "query_processing",
                {
                    "method": "query_processor",
                    "query": query,
                    "keywords": keywords,
                },
            )

        dense_results: List[RetrievalResult] = []
        sparse_results: List[RetrievalResult] = []
        dense_error: Optional[str] = None
        sparse_error: Optional[str] = None

        # 2) Dense 检索阶段打点
        if trace is not None:
            trace.start_stage("dense_retrieval")
        try:
            dense_results = self._dense_retriever.retrieve(
                query, top_k=effective_top_k, filters=filters, trace=trace
            )
        except Exception as e:
            dense_error = str(e)
        finally:
            if trace is not None:
                trace.finish_stage(
                    "dense_retrieval",
                    {
                        "method": self._dense_retriever.__class__.__name__,
                        "count": len(dense_results),
                        "error": dense_error,
                    },
                )

        # 3) Sparse 检索阶段打点
        if trace is not None:
            trace.start_stage("sparse_retrieval")
        try:
            sparse_results = self._sparse_retriever.retrieve(
                keywords, top_k=effective_top_k, trace=trace
            )
        except Exception as e:
            sparse_error = str(e)
        finally:
            if trace is not None:
                trace.finish_stage(
                    "sparse_retrieval",
                    {
                        "method": self._sparse_retriever.__class__.__name__,
                        "count": len(sparse_results),
                        "error": sparse_error,
                    },
                )

        # 各路自己的结果 —— 与最终结果**同样经过元数据过滤**，但不经融合与重排。
        #
        # 为什么也要过滤：不过滤的话两者口径不一致，分路径指标就不能与融合后
        # 指标对照，而「只留一路时两者应当相等」正是分路径指标唯一的自检手段。
        # 为什么不经融合与重排：那两步的作用恰恰是**改变名次**，混进来就量不出
        # 单路自身的质量了。
        def _route(items: List[RetrievalResult]) -> List[RetrievalResult]:
            return self._apply_metadata_filters(items, filters) if filters else list(items)

        # 键恒存在，值可能为空 —— 不省略键，否则「这一路没结果」与「根本没跑
        # 这一路」在数据上无法区分。
        routes: Dict[str, List[RetrievalResult]] = {
            ROUTE_DENSE: _route(dense_results),
            ROUTE_SPARSE: _route(sparse_results),
        }

        if not dense_results and not sparse_results:
            return SearchOutcome(results=[], routes=routes)

        # 4) Fusion 阶段打点
        if trace is not None:
            trace.start_stage("fusion")

        # feature-005 T013:按**命名映射**调用，权重靠键查找而非位置。
        # 此前传的是位置列表，靠下标区分两路 —— 而本文件与 fusion.py 曾经
        # 对这两路的顺序理解相反（fusion.py 的注释写作 [sparse, dense]）。
        # 等权时该错误无害，加权重后就是让 dense 拿到 sparse 权重的真 bug，
        # 且不会报错。
        #
        # ⚠️ 路径名用 ROUTE_DENSE / ROUTE_SPARSE 常量而非字面量：这三处
        # （fuse 的键、fusion_weights 的键、SearchOutcome.routes 的键）必须
        # 是同一个字符串。Fusion.weight_for() 查不到路径名会**静默回落 1.0**，
        # 于是校准出的权重被悄悄作废而系统照常运行、不报错。
        fused_results = self._fusion.fuse(
            {ROUTE_DENSE: dense_results, ROUTE_SPARSE: sparse_results},
            top_k=effective_top_k * 2,
        )

        if trace is not None:
            trace.finish_stage(
                "fusion",
                {
                    "method": self._fusion.__class__.__name__,
                    "input_dense": len(dense_results),
                    "input_sparse": len(sparse_results),
                    "output_count": len(fused_results),
                    # feature-005 T014 / FR-008:记录本次实际生效的权重。
                    # 没有它，事后无法判断某次检索用的什么配比 —— 而权重
                    # 配错不会报错，只会让效果悄悄变差。
                    "weights": getattr(self._fusion, "weights", None),
                    "rrf_k": getattr(self._fusion, "_k", None),
                },
            )

        if filters:
            fused_results = self._apply_metadata_filters(fused_results, filters)

        try:
            reranked_results = self._reranker.rerank(
                query, fused_results, trace=trace
            )
            final = reranked_results[:effective_top_k]
        except Exception:
            final = fused_results[:effective_top_k]

        return SearchOutcome(results=final, routes=routes)

    def _apply_metadata_filters(
        self,
        results: List[RetrievalResult],
        filters: Dict[str, Any],
    ) -> List[RetrievalResult]:
        """对结果应用元数据过滤器。

        Args:
            results: 待过滤的检索结果列表。
            filters: 元数据过滤器字典。

        Returns:
            过滤后的 RetrievalResult 列表。
        """
        if not filters:
            return results

        filtered: List[RetrievalResult] = []
        for result in results:
            metadata = result.metadata
            match = True
            for key, value in filters.items():
                if key not in metadata:
                    match = False
                    break
                if isinstance(value, list):
                    if metadata[key] not in value:
                        match = False
                        break
                elif metadata[key] != value:
                    match = False
                    break
            if match:
                filtered.append(result)

        return filtered
