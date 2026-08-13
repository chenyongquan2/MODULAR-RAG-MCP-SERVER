"""Cross-Encoder reranker implementation.

This module implements a reranker that uses Cross-Encoder models to score
query-candidate pairs. Cross-Encoders jointly encode the query and candidate
for more accurate relevance scoring compared to separate embeddings.

Design Principles Applied:
- Pluggable: Inherits from BaseReranker for seamless swapping.
- Config-Driven: Model name and parameters configurable via settings.
- Observable: Accepts optional TraceContext for observability integration.
- Fault-Tolerant: Falls back to original order on model failure.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional

from src.observability.logger import get_logger
from src.libs.reranker.base_reranker import BaseReranker

if TYPE_CHECKING:
    from src.core.settings import Settings

logger = get_logger(__name__)


class CrossEncoderReranker(BaseReranker):
    """Cross-Encoder reranker using sentence-transformers models.

    This reranker uses a Cross-Encoder model (e.g., ms-marco-MiniLM-L-6-v2)
    to score query-candidate pairs. Cross-Encoders jointly encode both inputs,
    providing more accurate relevance scores than bi-encoders.

    The reranker gracefully degrades to the original order if the model
    loading or inference fails, ensuring system resilience.

    Attributes:
        settings: The application settings.
        model_name: The Cross-Encoder model identifier.
        model: The loaded Cross-Encoder model (lazy-loaded).
        backend_name: Fixed to "cross_encoder".
        max_length: Maximum sequence length for tokenization.
        batch_size: Batch size for inference.
    """

    def __init__(
        self,
        settings: Settings,
        model: Optional[Any] = None,
        **kwargs: Any,
    ):
        """Initialize the Cross-Encoder reranker.

        Args:
            settings: The application settings containing reranker configuration.
            model: Optional pre-loaded model instance (for testing/dependency injection).
            **kwargs: Additional parameters (e.g., max_length, batch_size).

        Note:
            The model is lazy-loaded on first use to avoid startup overhead.
        """
        self.settings = settings
        self._model = model  # For dependency injection (testing)
        self.backend_name = "cross_encoder"

        # 模型名直接读配置，**不设隐式兜底**。
        #
        # 此前这里是 getattr(settings.rerank, "model", "cross-encoder/ms-marco-
        # MiniLM-L-6-v2") —— 配置留空就悄悄用一个纯英文 MS MARCO 模型，对本
        # 项目一半语料（中文 MT5 文档）完全无效，而且不报错。这与 Feature-004
        # 修掉的 getattr(..., "bm25_index_path", default) 是同一个病：
        # 「看起来可配、实际取默认值」。现在由 load_settings 强制显式配置
        # （backend != none 时 model 必填），走到这里必然有值。
        self.model_name = settings.rerank.model

        # batch_size 从配置读（此前硬编码 32，属宪法原则二禁止的硬编码可调
        # 参数）。它同时决定 Core 层超时检查的粒度，所以必须可调。
        # kwargs 仍可覆盖，供测试与特殊场景使用。
        self.max_length = kwargs.get("max_length", 512)
        self.batch_size = kwargs.get("batch_size", settings.rerank.batch_size)

    @property
    def model(self) -> Any:
        """Lazy-load the Cross-Encoder model.

        Returns:
            The loaded CrossEncoder instance.

        Raises:
            ImportError: If sentence-transformers is not installed.
            RuntimeError: If model loading fails.
        """
        if self._model is None:
            try:
                from sentence_transformers import CrossEncoder

                logger.info(f"Loading Cross-Encoder model: {self.model_name}")
                self._model = CrossEncoder(
                    self.model_name,
                    max_length=self.max_length,
                )
                logger.info(f"Cross-Encoder model loaded successfully")
            except ImportError as e:
                # 依赖不可导入。正常情况下 RerankerFactory.probe_backend 已在
                # 启动期挡掉这种配置错误（T-2.2），走到这里通常意味着装了但
                # 装坏了（例如 Windows 上 torch 的 DLL 加载失败）—— find_spec
                # 找得到模块，真正 import 时才炸。
                raise ImportError(
                    "sentence-transformers is required for Cross-Encoder reranking. "
                    'Install it with: pip install -e ".[rerank]"'
                ) from e
            except Exception as e:
                # 依赖可用但模型加载失败。与上面的 ImportError 是两种不同的
                # 故障，错误消息必须能区分 —— 最常见的原因是首次运行时无法
                # 访问 HuggingFace 下载权重（约 1GB，一次性）。
                raise RuntimeError(
                    f"Failed to load Cross-Encoder model '{self.model_name}': {e}. "
                    "This is a MODEL WEIGHT FETCH failure, not a missing "
                    "dependency. Weights are downloaded from HuggingFace on "
                    "first use (~1GB, one-time; cached afterwards and fully "
                    "offline). If the download is blocked, set a mirror: "
                    "HF_ENDPOINT=https://hf-mirror.com"
                ) from e

        return self._model

    def rerank(
        self,
        query: str,
        candidates: List[Dict[str, Any]],
        trace: Optional[Any] = None,
        **kwargs: Any,
    ) -> List[Dict[str, Any]]:
        """Rerank candidates using Cross-Encoder relevance scoring.

        Each candidate is scored by the Cross-Encoder model, which jointly
        encodes the query and candidate text. Candidates are then sorted
        by descending score.

        Args:
            query: The user query.
            candidates: List of candidate dicts with at minimum:
                - 'id': unique identifier
                - 'text': passage text
                - 'score': original retrieval score
            trace: Optional TraceContext for observability.
            **kwargs: Additional parameters (unused).

        Returns:
            Reranked candidate list (most relevant first). Each candidate
            includes additional fields:
            - 'rerank_score': The Cross-Encoder relevance score (normalized)
            - 'original_score': The pre-rerank score
            - 'reranked_by': "cross_encoder"

            If Cross-Encoder scoring fails, returns the original order with:
            - 'reranked_by': "none"
            - 'rerank_fallback_reason': Error message

        Raises:
            ValueError: If inputs fail validation.
        """
        # Handle empty candidates early
        if not candidates:
            return []

        # Validate inputs
        self.validate_inputs(query, candidates)

        try:
            # Prepare query-candidate pairs
            pairs = [(query, candidate.get("text", "")) for candidate in candidates]

            # Score using Cross-Encoder model
            # Returns numpy array of scores (typically in range [-10, 10])
            raw_scores = self.model.predict(
                pairs,
                batch_size=self.batch_size,
                show_progress_bar=False,
            )

            # Normalize scores to [0, 1] using sigmoid-like transformation
            # This ensures scores are comparable across different models
            import numpy as np

            # Simple min-max normalization
            if len(raw_scores) > 1:
                min_score = float(np.min(raw_scores))
                max_score = float(np.max(raw_scores))
                if max_score > min_score:
                    normalized_scores = [
                        float((s - min_score) / (max_score - min_score))
                        for s in raw_scores
                    ]
                else:
                    # All scores are the same
                    normalized_scores = [0.5] * len(raw_scores)
            else:
                # Single candidate
                normalized_scores = [0.5]

            # Add scores to candidates
            scored_candidates = []
            for idx, candidate in enumerate(candidates):
                scored_candidates.append(
                    {
                        **candidate,
                        "rerank_score": normalized_scores[idx],
                        "original_score": candidate.get("score", 0.0),
                        "reranked_by": "cross_encoder",
                    }
                )

            # Sort by Cross-Encoder score (descending)
            scored_candidates.sort(key=lambda x: x["rerank_score"], reverse=True)

            # Record trace (if provided)
            if trace:
                trace.record_stage(
                    "rerank_cross_encoder",
                    method="cross_encoder",
                    provider="sentence_transformers",
                    model=self.model_name,
                    details={
                        "input_count": len(candidates),
                        "output_count": len(scored_candidates),
                        "score_range": (
                            [
                                scored_candidates[-1]["rerank_score"],
                                scored_candidates[0]["rerank_score"],
                            ]
                            if scored_candidates
                            else [0, 0]
                        ),
                    },
                )

            logger.info(
                f"Cross-Encoder reranking completed: {len(scored_candidates)} candidates"
            )
            return scored_candidates

        except ImportError as e:
            # sentence-transformers not installed
            logger.error(
                f"Cross-Encoder reranking failed (missing dependency): {e}, "
                f"falling back to original order"
            )

            if trace:
                trace.record_stage(
                    "rerank_cross_encoder",
                    method="cross_encoder",
                    provider="sentence_transformers",
                    error=str(e),
                    fallback=True,
                )

            # Mark as fallback
            for candidate in candidates:
                candidate["reranked_by"] = "none"
                candidate["rerank_fallback_reason"] = f"ImportError: {e}"

            return candidates

        except Exception as e:
            # Graceful degradation: return original order on failure
            logger.error(
                f"Cross-Encoder reranking failed: {e}, falling back to original order"
            )

            if trace:
                trace.record_stage(
                    "rerank_cross_encoder",
                    method="cross_encoder",
                    provider="sentence_transformers",
                    error=str(e),
                    fallback=True,
                )

            # Mark as fallback
            for candidate in candidates:
                candidate["reranked_by"] = "none"
                candidate["rerank_fallback_reason"] = str(e)

            return candidates

    def supports_batch_scoring(self) -> bool:
        """Cross-Encoder 支持分批打分，从而支持 Core 层的超时兜底。"""
        return True

    def score_batch(
        self,
        query: str,
        candidates: List[Dict[str, Any]],
    ) -> List[float]:
        """为一批候选打**原始**相关性分数，不排序、不归一化。

        与 ``rerank()`` 的关键差别是**不做 min-max 归一化**。归一化是按「本次
        看到的全部候选」算 min/max 的，如果对每一批各自归一化，各批的 0~1
        就不是同一把尺子，放在一起排序会得出错误名次 —— 而分批的全部意义就
        在于各批分数要能合并排序。所以这里返回模型原始 logit（可排序，但不是
        概率，不可跨样本比阈值）。

        Args:
            query: 查询文本。
            candidates: 本批候选，每条需含 ``text``。

        Returns:
            与 ``candidates`` 等长、顺序一一对应的原始分数。

        Raises:
            ImportError: sentence-transformers 不可导入（装了但装坏了）。
            RuntimeError: 模型权重加载失败。
        """
        if not candidates:
            return []

        pairs = [(query, candidate.get("text", "")) for candidate in candidates]
        raw_scores = self.model.predict(
            pairs,
            batch_size=len(pairs),  # Core 层已切好批，这里一次算完
            show_progress_bar=False,
        )
        return [float(s) for s in raw_scores]

    def get_backend_name(self) -> str:
        """Return the backend identifier.

        Returns:
            "cross_encoder"
        """
        return self.backend_name
