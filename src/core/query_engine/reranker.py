"""重排序模块 (None/CrossEncoder/LLM)。

本模块实现了 Core 层重排序编排器，负责接入 libs.reranker 后端，
并提供失败/超时回退机制，确保不影响最终返回结果。

当 reranker 不可用时，保持原始排名顺序并标记 fallback=true。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional

from src.core.types import RetrievalResult

if TYPE_CHECKING:
    from src.core.settings import Settings


class Reranker:
    """Core 层重排序编排器。

    负责调用 libs.reranker 后端对检索结果进行重排序，
    并在失败时提供 graceful degradation。

    Design Principles Applied:
    - Fail-Fast Validation: 验证输入参数
    - Graceful Degradation: 任何 reranker 异常都回退到原始顺序
    - Observability: 在 metadata 中标记 rerank 相关状态

    Example:
        >>> reranker = Reranker(settings)
        >>> results = reranker.rerank(query, candidates)
    """

    def __init__(
        self,
        settings: Settings,
        reranker_backend: Optional[Any] = None,
    ) -> None:
        """Initialize Reranker.

        Args:
            settings: Application settings containing rerank configuration.
            reranker_backend: Optional reranker backend instance (created from factory if not provided).

        Raises:
            ValueError: If settings is None.
        """
        if settings is None:
            raise ValueError("Settings cannot be None")

        self._settings = settings

        if reranker_backend is not None:
            self._reranker = reranker_backend
        else:
            from src.libs.reranker.reranker_factory import RerankerFactory

            self._reranker = RerankerFactory.create(settings)

    def rerank(
        self,
        query: str,
        candidates: List[RetrievalResult],
        trace: Optional[Any] = None,
    ) -> List[RetrievalResult]:
        """Rerank candidates using the configured reranker backend.

        Args:
            query: The original search query.
            candidates: List of RetrievalResult to rerank.
            trace: Optional TraceContext for observability.

        Returns:
            List of RetrievalResult sorted by reranked score (descending).
            If reranking fails, returns candidates in original order with
            metadata['rerank_fallback'] = True.
        """
        if not candidates:
            return []

        if not query or not query.strip():
            return candidates

        if trace is not None:
            trace.start_stage("rerank")

        candidates_dicts: List[Dict[str, Any]] = [
            {
                "id": r.chunk_id,
                "text": r.text,
                "score": r.score,
                "_retrieval_result": r,
            }
            for r in candidates
        ]

        rerank_output_count = len(candidates)
        fallback = False

        try:
            reranked_dicts = self._reranker.rerank(query, candidates_dicts, trace=trace)

            results: List[RetrievalResult] = []
            for d in reranked_dicts:
                original = d.get("_retrieval_result")
                if original and isinstance(original, RetrievalResult):
                    if "rerank_fallback" in original.metadata:
                        del original.metadata["rerank_fallback"]
                    original.metadata["reranked"] = True
                    results.append(original)
                else:
                    results.append(
                        RetrievalResult(
                            chunk_id=d.get("id", ""),
                            score=d.get("score", 0.0),
                            text=d.get("text", ""),
                            metadata={"reranked": True},
                        )
                    )

            rerank_output_count = len(results)
            return results

        except Exception:
            fallback = True
            for result in candidates:
                result.metadata["rerank_fallback"] = True
            return candidates
        finally:
            if trace is not None:
                trace.finish_stage(
                    "rerank",
                    {
                        "method": self._reranker.__class__.__name__,
                        "input_count": len(candidates),
                        "output_count": rerank_output_count,
                        "fallback": fallback,
                    },
                )
