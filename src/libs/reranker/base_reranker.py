"""Abstract base class for Reranker providers.

This module defines the pluggable interface for reranking backends,
enabling seamless switching between different strategies (LLM-based,
Cross-Encoder, None/passthrough) through configuration-driven instantiation.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class BaseReranker(ABC):
    """Abstract base class for Reranker providers.

    All Reranker implementations must inherit from this class and implement
    the rerank() method. This ensures consistent interface across different
    backends (LLM, Cross-Encoder, None, etc.).

    Design Principles Applied:
    - Pluggable: Subclasses can be swapped without changing upstream code.
    - Observable: Accepts optional TraceContext for observability integration.
    - Config-Driven: Instances are created via factory based on settings.
    """

    @abstractmethod
    def rerank(
        self,
        query: str,
        candidates: List[Dict[str, Any]],
        trace: Optional[Any] = None,
        **kwargs: Any,
    ) -> List[Dict[str, Any]]:
        """Rerank a list of candidates based on relevance to the query.

        Each candidate is a dict containing at minimum:
        - 'id': str — unique identifier
        - 'text': str — the text content to evaluate
        - 'score': float — the original retrieval score

        The returned list preserves the same dict structure but reorders
        and may update the 'score' field.

        Args:
            query: The original query text.
            candidates: List of candidate dicts to rerank.
            trace: Optional TraceContext for observability (reserved for Stage F).
            **kwargs: Backend-specific parameters.

        Returns:
            A list of candidate dicts, reranked by relevance (most relevant first).
            Each dict retains its original fields but may have updated scores.

        Raises:
            ValueError: If query is empty or candidates list is invalid.
            RuntimeError: If the reranking operation fails.

        Example:
            >>> ranked = reranker.rerank("What is RAG?", [
            ...     {"id": "1", "text": "RAG is...", "score": 0.8},
            ...     {"id": "2", "text": "Unrelated", "score": 0.9},
            ... ])
            >>> ranked[0]["id"]
            '1'
        """
        pass

    def validate_inputs(
        self,
        query: str,
        candidates: List[Dict[str, Any]],
    ) -> None:
        """Validate reranking inputs.

        Args:
            query: The query string to validate.
            candidates: The candidates list to validate.

        Raises:
            ValueError: If query is empty or candidates are invalid.
        """
        if not isinstance(query, str) or not query.strip():
            raise ValueError("Query must be a non-empty string")
        if not candidates:
            raise ValueError("Candidates list cannot be empty")
        required_fields = {"id", "text", "score"}
        for i, candidate in enumerate(candidates):
            if not isinstance(candidate, dict):
                raise ValueError(
                    f"Candidate at index {i} is not a dict "
                    f"(type: {type(candidate).__name__})"
                )
            missing_fields = required_fields - set(candidate.keys())
            if missing_fields:
                raise ValueError(
                    f"Candidate at index {i} is missing required fields: "
                    f"{sorted(missing_fields)}"
                )

    def get_backend_name(self) -> str:
        """Get the backend name used by this provider.

        Returns:
            The backend identifier string.

        Raises:
            NotImplementedError: If the subclass doesn't override this method.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement get_backend_name() method"
        )

    # ── 分批打分（可选能力，用于超时兜底）────────────────────────────────
    #
    # 为什么需要这个接口（change activate-cross-encoder-rerank T-3.2）：
    #
    # cross-encoder 是**同步 CPU 推理**，没有 HTTP 客户端那种现成的超时参数
    # 可传。而 Python 里能中断一段正在跑的同步计算的手段都不可用：
    #   - signal.alarm  → Windows 不支持，且非主线程无效
    #   - 工作线程 + join(timeout) → 超时后线程仍在跑，无法中断 torch 推理，
    #     只会泄漏线程并继续吃 CPU
    #
    # 唯一可行的办法是**把工作切成小批，在批的间隙检查已耗时**。所以后端要
    # 暴露「给我这一批，返回这一批的分数」的能力，由 Core 层控制节奏与停止。
    #
    # 声明为 optional 而非 abstractmethod：`NoneReranker` 这类不打分的后端
    # 没有实现它的意义，且已有的第三方后端不该因为新增接口而全部失效。
    # Core 层用 `supports_batch_scoring()` 探测，不支持则退回整体调用。

    def supports_batch_scoring(self) -> bool:
        """本后端是否支持分批打分（从而支持超时兜底）。

        Returns:
            默认 False。支持分批的后端需同时重写本方法与 ``score_batch``。
        """
        return False

    def score_batch(
        self,
        query: str,
        candidates: List[Dict[str, Any]],
    ) -> List[float]:
        """为一批候选打分，不排序。

        Args:
            query: 查询文本。
            candidates: 本批候选（已由 Core 层切好）。

        Returns:
            与 ``candidates`` 等长、顺序一一对应的分数列表。分数越大越相关，
            **不要求归一化** —— 归一化会让跨批分数不可比，而分批的全部意义
            就在于各批分数要能放在一起排序。

        Raises:
            NotImplementedError: 后端未实现分批打分。
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} does not support batch scoring"
        )


class NoneReranker(BaseReranker):
    """Passthrough reranker that preserves the original candidate order.

    Used as a default fallback when no reranking is configured or when
    the reranking backend is unavailable.
    """

    def __init__(self, settings: Any = None, **kwargs: Any):
        """Initialize NoneReranker.

        Args:
            settings: Optional settings (unused).
            **kwargs: Additional parameters (unused).
        """
        self.settings = settings

    def rerank(
        self,
        query: str,
        candidates: List[Dict[str, Any]],
        trace: Optional[Any] = None,
        **kwargs: Any,
    ) -> List[Dict[str, Any]]:
        """Return candidates in their original order without modification."""
        self.validate_inputs(query, candidates)
        return list(candidates)

    def get_backend_name(self) -> str:
        """Return 'none' as the backend name."""
        return "none"
