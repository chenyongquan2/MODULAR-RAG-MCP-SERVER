"""结果融合 (RRF 算法)。

本模块实现了 Reciprocal Rank Fusion (RRF) 算法，用于融合多个
检索结果列表的排名。RRF 是一种无参数的方法，通过对不同检索
方法的结果进行排名聚合来提高整体检索质量。

算法公式：
    RRF(d) = Σ (1 / (k + rank(d)))

其中：
- d 是文档/chunk
- rank(d) 是文档在某个检索结果列表中的排名位置（从1开始）
- k 是一个常数（默认为60），用于平滑处理
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional

from src.core.types import RetrievalResult

if TYPE_CHECKING:
    from src.core.settings import Settings


class Fusion:
    """Reciprocal Rank Fusion (RRF) for result merging.

    This class implements the RRF algorithm to combine multiple ranked
    retrieval result lists into a single unified ranking.

    Design Principles Applied:
    - Stateless: No internal state, purely functional algorithm.
    - Deterministic: Same inputs always produce same outputs.
    - Graceful Degradation: Handles empty result lists gracefully.

    Example:
        >>> fusion = Fusion()
        >>> dense_results = [RetrievalResult(chunk_id="1", score=0.9, ...),
        ...                  RetrievalResult(chunk_id="2", score=0.8, ...)]
        >>> sparse_results = [RetrievalResult(chunk_id="2", score=0.7, ...),
        ...                    RetrievalResult(chunk_id="1", score=0.6, ...)]
        >>> fused = fusion.fuse([dense_results, sparse_results], top_k=5)
        >>> [r.chunk_id for r in fused]
        ['2', '1']
    """

    DEFAULT_K = 60

    def __init__(self, k: Optional[int] = None) -> None:
        """Initialize Fusion with RRF k parameter.

        Args:
            k: The RRF smoothing parameter. Higher values give more weight
               to lower-ranked results. Defaults to 60.

        Note:
            Common k values: 60 (default), 1 (aggressive), 100 (conservative)
        """
        self._k = k if k is not None else self.DEFAULT_K

    def fuse(
        self,
        result_lists: List[List[RetrievalResult]],
        top_k: Optional[int] = None,
    ) -> List[RetrievalResult]:
        """Fuse multiple ranked result lists using RRF.

        Args:
            result_lists: List of retrieval result lists to fuse.
            top_k: Number of top results to return. If None, returns all fused results.

        Returns:
            List of RetrievalResult sorted by RRF score (descending).

        Note:
            - Empty result lists are ignored.
            - Duplicate chunk_ids across lists are merged (scores summed).
            - Original metadata and text from the highest-scoring result is preserved.
        """
        if not result_lists:
            return []

        chunk_scores: Dict[str, float] = {}
        chunk_data: Dict[str, RetrievalResult] = {}

        for result_list in result_lists:
            if not result_list:
                continue
            
            # start=1 只影响 enumerate 产生的序号（index / rank）从几开始，不会影响遍历元素本身的顺序或起始位置。
            # enumerate() 用来在遍历列表的同时拿到“索引/序号”
            # enumerate(iterable, start=1) 的本质是：给你遍历到的每个元素配一个“计数器”，
            # 这个计数器从 1 开始递增，但元素仍然是按原来的顺序从第一个元素开始取。
            # rank在这里就是index的位置，从1开始递增，表示当前元素在这个列表中的排名位置。
            # rank=1 表示"第1名"，人类容易理解
            for rank, result in enumerate(result_list, start=1):
                if not result.chunk_id:
                    continue

                rrf_score = 1.0 / (self._k + rank)

                if result.chunk_id in chunk_scores:
                    # 同一 chunk_id 的 text/metadata 在 dense/sparse 中相同，无需更新
                    chunk_scores[result.chunk_id] += rrf_score
                else:
                    chunk_scores[result.chunk_id] = rrf_score
                    chunk_data[result.chunk_id] = result

        fused_results: List[RetrievalResult] = []
        for chunk_id, rrf_score in chunk_scores.items():
            original = chunk_data[chunk_id]
            fused_results.append(
                RetrievalResult(
                    chunk_id=original.chunk_id,
                    score=rrf_score,
                    text=original.text,
                    metadata=original.metadata,
                )
            )

        fused_results.sort(key=lambda x: x.score, reverse=True)

        if top_k is not None and top_k > 0:
            fused_results = fused_results[:top_k]

        return fused_results


class HybridSearch:
    """混合检索引擎 (Dense + Sparse + RRF).

    This class orchestrates the complete hybrid search pipeline:
    1. Process query (keyword extraction, filters)
    2. Parallel dense and sparse retrieval
    3. RRF fusion of results
    4. Optional metadata filtering
    5. Return top-k results

    Design Principles Applied:
    - Pluggable: Each component can be replaced independently.
    - Fail-Fast: Validates inputs with clear error messages.
    - Graceful Degradation: If one retrieval path fails, uses the other.
    - Dependency Injection: Components are injected for testability.

    Example:
        >>> hybrid = HybridSearch(settings, query_processor, dense, sparse, fusion)
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
        """Initialize HybridSearch.

        Args:
            settings: Application settings (optional for testing).
            query_processor: Optional QueryProcessor (created if not provided).
            dense_retriever: Optional DenseRetriever (created if not provided).
            sparse_retriever: Optional SparseRetriever (created if not provided).
            fusion: Optional Fusion instance (created if not provided).
            reranker: Optional Reranker (created if not provided).

        Note:
            If settings is None, all retrievers must be provided explicitly.
        """
        self._settings = settings

        if query_processor is not None:
            self._query_processor = query_processor
        else:
            from src.core.query_engine.query_processor import QueryProcessor, QueryProcessorConfig
            config = QueryProcessorConfig()
            self._query_processor = QueryProcessor(config=config)

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
            self._fusion = Fusion()

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
        """Execute hybrid search pipeline.

        Args:
            query: The search query text.
            top_k: Number of results to return.
            filters: Optional metadata filters.
            trace: Optional TraceContext for observability.

        Returns:
            List of RetrievalResult sorted by fused score (descending).

        Raises:
            ValueError: If query is empty or top_k is invalid.
        """
        if not query or not query.strip():
            raise ValueError("Query cannot be empty")

        effective_top_k = top_k if top_k is not None else self._default_top_k

        if effective_top_k <= 0:
            raise ValueError("top_k must be a positive integer")

        processed_query = self._query_processor.process(query)
        keywords = processed_query.keywords

        dense_results: List[RetrievalResult] = []
        sparse_results: List[RetrievalResult] = []
        dense_error: Optional[str] = None
        sparse_error: Optional[str] = None

        try:
            dense_results = self._dense_retriever.retrieve(
                query, top_k=effective_top_k, filters=filters, trace=trace
            )
        except Exception as e:
            dense_error = str(e)

        try:
            sparse_results = self._sparse_retriever.retrieve(
                keywords, top_k=effective_top_k, trace=trace
            )
        except Exception as e:
            sparse_error = str(e)

        if not dense_results and not sparse_results:
            return []

        fused_results = self._fusion.fuse(
            [dense_results, sparse_results],
            top_k=effective_top_k * 2,
        )

        if filters:
            fused_results = self._apply_metadata_filters(fused_results, filters)

        try:
            reranked_results = self._reranker.rerank(
                query, fused_results, trace=trace
            )
            return reranked_results[:effective_top_k]
        except Exception:
            return fused_results[:effective_top_k]

    def _apply_metadata_filters(
        self,
        results: List[RetrievalResult],
        filters: Dict[str, Any],
    ) -> List[RetrievalResult]:
        """Apply metadata filters to results.

        Args:
            results: List of retrieval results to filter.
            filters: Dictionary of metadata filters.

        Returns:
            Filtered list of RetrievalResult.
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
