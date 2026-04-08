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

from src.core.types import RetrievalResult

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
            from src.core.query_engine.fusion import Fusion
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
        """执行混合检索流程。

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

        if not dense_results and not sparse_results:
            return []

        # 4) Fusion 阶段打点
        if trace is not None:
            trace.start_stage("fusion")

        fused_results = self._fusion.fuse(
            [dense_results, sparse_results],
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
                },
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
