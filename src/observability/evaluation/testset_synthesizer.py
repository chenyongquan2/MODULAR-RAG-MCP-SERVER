"""TestsetSynthesizer — 包装 RAGAS TestsetGenerator 合成候选金标 (T019, FR-004).

实现 spec § FR-004 "测试集生成流程 MUST 从已摄入的真实 MT5 语料自动合成
至少 100 条候选 (question, ground_truth) 对" + research § Decision 5
(distribution).

设计:
- 从项目 vector store 拉 N 个真实 chunks 当作 RAGAS 合成的语料源
- 通过 _ragas_wrappers 复用 LLMFactory / EmbeddingFactory(provider-agnostic)
- 输出含 ``_synthesis_metadata`` 与 candidate cases 的 dict;每个 case 含
  partial tags(精修阶段补齐 content_type 等);留 expected_chunk_ids 由 backfill
  阶段填(US2 step B3)

使用方式:
    >>> synth = TestsetSynthesizer(settings)
    >>> candidate = synth.synthesize(
    ...     collection="mt5_docs_chinese", lang="zh", target_count=100
    ... )
    >>> # candidate["test_cases"] is a list of partial cases
    >>> # candidate["_synthesis_metadata"] tracks generator/judge/embedding ids
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Optional

from src.observability.logger import get_logger

if TYPE_CHECKING:
    from src.core.settings import Settings


logger = get_logger(__name__)


# RAGAS 0.1.x 的标准三类 evolution 名(简化字符串接口,内部映射到 ragas
# 的 SimpleEvolution / ReasoningEvolution / MultiContextEvolution 实例)
DEFAULT_DISTRIBUTION: dict[str, float] = {
    "simple": 0.5,
    "reasoning": 0.3,
    "multi_context": 0.2,
}


class TestsetSynthesizer:
    """RAGAS TestsetGenerator 的项目侧包装(provider-agnostic)。"""

    # 阻止 pytest 把这个类当成测试类(类名以 Test 开头会被 pytest 默认收集)
    __test__ = False

    def __init__(self, settings: "Settings") -> None:
        """初始化合成器(延迟构建 RAGAS judge/embedding,直到 synthesize 触发)。"""
        self._settings = settings
        self._generator: Any = None  # ragas.testset.generator.TestsetGenerator

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def synthesize(
        self,
        collection: str,
        lang: str,
        target_count: int = 100,
        distribution: Optional[dict[str, float]] = None,
        chunk_sample_size: Optional[int] = None,
        source_filter: Optional[str] = None,
    ) -> dict[str, Any]:
        """合成候选测试集。

        Args:
            collection: 项目 vector store 中的 collection 名(中文/英文 MT5)。
            lang: ``"zh"`` 或 ``"en"``,写入 candidate 的顶层 language 字段。
            target_count: 目标合成数(默认 100;精修后通常缩到 ≥ 40)。
            distribution: 难度分布,key ∈ {simple, reasoning, multi_context},
                value 求和应 ≈ 1.0。默认 50/30/20。
            chunk_sample_size: 从 collection 取多少 chunk 作为合成语料。
                None 时取 ``min(target_count * 5, collection.count)`` —— 经验值,
                让 RAGAS 有足够的多样性可挑。
            source_filter: 可选 substring 过滤;只保留 ``metadata.source`` 含此
                子串的 chunks(用于混合语种 collection 中按文件名筛选,
                例如 ``"Chinese.chm"`` / ``"English.chm"``)。默认 None = 不过滤。

        Returns:
            ``{"_schema_version": 1, "language": ..., "_synthesis_metadata": {...},
              "test_cases": [...]}`` 形式的 candidate dict。

        Raises:
            ValueError: 配置非法(distribution 总和远离 1.0、target_count <= 0、
                collection 不存在或为空、过滤后无 chunks)。
            RuntimeError: RAGAS 合成失败。
        """
        if target_count <= 0:
            raise ValueError(f"target_count must be > 0, got {target_count}")
        dist = self._validate_distribution(distribution or DEFAULT_DISTRIBUTION)

        # source_filter 设置时,匹配的 chunks 可能集中在 collection 末尾(例如
        # 中英混合 collection 中英文 chunks 在中文之后);保险起见拉取 None 表示
        # 全量(_fetch_chunks 内部会用 col.count() 做上限)。无过滤场景仍是 *5。
        fetch_limit = chunk_sample_size or (
            None if source_filter else target_count * 5
        )
        chunks = self._fetch_chunks(collection, fetch_limit, source_filter=source_filter)
        if not chunks:
            extra = (
                f" (with source_filter='{source_filter}')" if source_filter else ""
            )
            raise ValueError(
                f"collection '{collection}' contains no chunks{extra}; "
                "please run scripts/ingest.py first to populate it, or relax "
                "the source_filter substring."
            )

        documents = self._chunks_to_langchain_docs(chunks)

        self._ensure_generator()
        ragas_distributions = self._build_ragas_distributions(dist)

        try:
            from datasets import Dataset
            testset = self._generator.generate_with_langchain_docs(
                documents=documents,
                test_size=target_count,
                distributions=ragas_distributions,
                raise_exceptions=False,  # 单 case 失败不应让整个 100 条都丢
            )
        except Exception as exc:
            raise RuntimeError(f"RAGAS testset synthesis failed: {exc}") from exc

        candidate = self._testset_to_candidate(testset, lang=lang, distribution=dist)
        logger.info(
            "Synthesized %d candidates for lang=%s collection=%s (target was %d)",
            len(candidate["test_cases"]),
            lang,
            collection,
            target_count,
        )
        return candidate

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _ensure_generator(self) -> None:
        """构建 RAGAS TestsetGenerator(generator_llm + critic_llm + embeddings)。

        生成器与 critic 可以共用同一个 LLM 实例(RAGAS 允许),减少模型差异。
        """
        if self._generator is not None:
            return

        from ragas.testset.generator import TestsetGenerator

        from src.observability.evaluation._ragas_wrappers import (
            build_ragas_embedding,
            build_ragas_judge,
        )

        # 复用 wrapper:LangchainLLMWrapper / LangchainEmbeddingsWrapper
        # TestsetGenerator.__init__ 期望 BaseRagasLLM / BaseRagasEmbeddings(已包装)
        judge = build_ragas_judge(self._settings)
        embedding = build_ragas_embedding(self._settings)

        # InMemoryDocumentStore 需要 splitter+embeddings+extractor 全部填上
        # (extractor 也用同一个 judge wrapper,保持 provider-agnostic)
        self._generator = TestsetGenerator(
            generator_llm=judge,
            critic_llm=judge,  # 共用,降低 LLM 调用差异
            embeddings=embedding,
            docstore=self._build_docstore(embedding=embedding, judge=judge),
        )

    def _build_docstore(self, embedding: Any, judge: Any) -> Any:
        """构建 RAGAS 的 InMemoryDocumentStore。

        RAGAS 0.1.x 的 InMemoryDocumentStore 需要 ``splitter`` + ``embeddings``
        + ``extractor``(KeyphraseExtractor 用 LLM 抽取关键短语作为种子)。
        三者缺一会在 generate 时报"Extractor must be set"。

        所有依赖都用项目复用的 judge / embedding wrapper,保持 provider-agnostic。
        """
        from ragas.testset.docstore import InMemoryDocumentStore
        from ragas.testset.extractor import KeyphraseExtractor
        from langchain_text_splitters import RecursiveCharacterTextSplitter

        splitter = RecursiveCharacterTextSplitter(chunk_size=1024, chunk_overlap=100)
        extractor = KeyphraseExtractor(llm=judge)
        return InMemoryDocumentStore(
            splitter=splitter,
            embeddings=embedding,
            extractor=extractor,
        )

    def _fetch_chunks(
        self,
        collection: str,
        limit: Optional[int],
        source_filter: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """从 vector store 拉取 chunks 用作合成语料。

        直接通过 chromadb 客户端读取(本工具是数据准备脚本,不走 query 链路;
        provider-agnostic 约束适用于 query path,不适用于 ingestion-time / 数据
        准备工具,符合 spec § Architecture stability rule)。

        Args:
            collection: ChromaDB collection 名。
            limit: 上限拉取量。
            source_filter: 可选 substring,只保留 metadata.source 含此子串
                的 chunks(用于混合语种 collection 按文件名分流)。
        """
        try:
            import chromadb
        except ImportError as exc:
            raise RuntimeError(
                "chromadb required for testset synthesis; install via "
                "pip install -e \".[dev]\""
            ) from exc

        client = chromadb.PersistentClient(
            path=self._settings.vector_store.persist_path
        )
        try:
            col = client.get_collection(collection)
        except Exception as exc:
            raise ValueError(
                f"collection '{collection}' not found in vector store: {exc}"
            ) from exc

        count = col.count()
        if count == 0:
            return []

        # ChromaDB get(limit=N) 不支持 random sampling;按需多取以便过滤
        # limit=None 表示拉全集(用于 source_filter 在 collection 末尾的场景)
        n = count if limit is None else min(limit, count)
        result = col.get(limit=n, include=["documents", "metadatas"])
        ids = result.get("ids", [])
        docs = result.get("documents", []) or []
        metas = result.get("metadatas", []) or []

        chunks: list[dict[str, Any]] = []
        for cid, text, meta in zip(ids, docs, metas):
            if not text or not isinstance(text, str) or not text.strip():
                continue
            meta_dict = dict(meta) if meta else {}
            if source_filter:
                # 检查多个候选 metadata 字段:source / source_path 是物理文件名,
                # collection 是项目内"逻辑 collection 名"标签。只要任一字段含
                # source_filter 子串即认为匹配。
                src = str(meta_dict.get("source") or meta_dict.get("source_path") or "")
                logical_col = str(meta_dict.get("collection") or "")
                if source_filter not in src and source_filter not in logical_col:
                    continue
            chunks.append({
                "id": cid,
                "text": text,
                "metadata": meta_dict,
            })
        logger.info(
            "Fetched %d non-empty chunks from collection '%s' (collection size: %d, source_filter=%r)",
            len(chunks),
            collection,
            count,
            source_filter,
        )
        return chunks

    @staticmethod
    def _chunks_to_langchain_docs(chunks: list[dict[str, Any]]) -> list[Any]:
        """把项目 chunk dicts 转成 LangChain Documents(RAGAS 需要的输入格式)。"""
        from langchain_core.documents import Document

        return [
            Document(
                page_content=c["text"],
                metadata={
                    "source": c.get("metadata", {}).get("source", c["id"]),
                    "chunk_id": c["id"],
                    **{
                        k: v for k, v in c.get("metadata", {}).items()
                        if k not in ("source",)
                    },
                },
            )
            for c in chunks
        ]

    @staticmethod
    def _validate_distribution(dist: dict[str, float]) -> dict[str, float]:
        """校验 distribution dict;允许少量浮点误差。"""
        valid_keys = {"simple", "reasoning", "multi_context"}
        unknown = set(dist.keys()) - valid_keys
        if unknown:
            raise ValueError(
                f"distribution contains unknown keys: {sorted(unknown)}; "
                f"valid options: {sorted(valid_keys)}"
            )
        # 缺失 key 视作 0(允许只给 simple+reasoning)
        normalized = {k: float(dist.get(k, 0.0)) for k in valid_keys}
        total = sum(normalized.values())
        if not 0.95 <= total <= 1.05:
            raise ValueError(
                f"distribution values must sum to ~1.0 (got {total:.3f}): "
                f"{normalized}"
            )
        return normalized

    @staticmethod
    def _build_ragas_distributions(dist: dict[str, float]) -> dict[Any, float]:
        """把字符串 distribution 映射到 RAGAS 的 evolution 实例。"""
        from ragas.testset.evolutions import multi_context, reasoning, simple

        mapping = {
            "simple": simple,
            "reasoning": reasoning,
            "multi_context": multi_context,
        }
        # 只把非零项加入(RAGAS 不接受 0 weight)
        return {mapping[k]: v for k, v in dist.items() if v > 0.0 and k in mapping}

    def _testset_to_candidate(
        self,
        testset: Any,
        lang: str,
        distribution: dict[str, float],
    ) -> dict[str, Any]:
        """把 RAGAS testset 对象转成项目 candidate JSON schema。"""
        from src.observability.evaluation._ragas_wrappers import (
            get_embedding_identifier,
            get_judge_identifier,
        )

        # RAGAS 0.1.x testset 有 to_pandas() / test_data 等接口;不同子版本可能
        # 略有差异,这里多路径兜底
        rows: list[dict[str, Any]] = []
        if hasattr(testset, "to_pandas"):
            df = testset.to_pandas()
            rows = df.to_dict(orient="records")
        elif hasattr(testset, "test_data"):
            rows = [
                {
                    "question": getattr(td, "question", ""),
                    "ground_truth": getattr(td, "ground_truth", ""),
                    "contexts": getattr(td, "contexts", []),
                    "evolution_type": getattr(td, "evolution_type", "simple"),
                }
                for td in testset.test_data
            ]
        else:
            rows = list(testset)

        test_cases = []
        for row in rows:
            question = str(row.get("question") or row.get("user_input") or "").strip()
            if not question:
                continue
            ground_truth = str(
                row.get("ground_truth") or row.get("answer") or row.get("reference") or ""
            ).strip()
            contexts = row.get("contexts") or row.get("reference_contexts") or []
            if isinstance(contexts, str):
                contexts = [contexts]
            evolution_type = str(row.get("evolution_type") or "simple").strip()
            # RAGAS evolution_type 与我们的 difficulty 对齐
            difficulty_map = {
                "simple": "simple",
                "reasoning": "reasoning",
                "multi_context": "multi_context",
            }
            difficulty = difficulty_map.get(evolution_type.lower(), "simple")

            test_cases.append({
                "query": question,
                "expected_chunk_ids": [],  # 由 backfill 阶段补齐 (US2 step B3)
                "expected_sources": [],
                "ground_truth": ground_truth,
                "_synth_contexts": list(contexts),  # 临时字段,refine 阶段可参考
                "tags": {
                    # content_type 由精修阶段判断(text/code/table/mixed),先占位
                    "content_type": "text",
                    "difficulty": difficulty,
                    "language": lang,
                    "doc_version": "v1",
                },
            })

        return {
            "_schema_version": 1,
            "language": lang,
            "_synthesis_metadata": {
                "generator": "ragas.testset.TestsetGenerator",
                "ragas_version": self._ragas_version(),
                "judge_llm_identifier": get_judge_identifier(self._settings),
                "embedding_identifier": get_embedding_identifier(self._settings),
                "distribution": dict(distribution),
                "synthesized_at": datetime.now(timezone.utc).isoformat(),
            },
            "test_cases": test_cases,
        }

    @staticmethod
    def _ragas_version() -> str:
        try:
            import ragas
            return str(getattr(ragas, "__version__", "unknown"))
        except ImportError:
            return "unavailable"
