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

        # Extract configuration
        self.model_name = getattr(
            settings.rerank, "model", "cross-encoder/ms-marco-MiniLM-L-6-v2"
        )
        self.max_length = kwargs.get("max_length", 512)
        self.batch_size = kwargs.get("batch_size", 32)

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
                raise ImportError(
                    "sentence-transformers is required for Cross-Encoder reranking. "
                    "Install it with: pip install sentence-transformers"
                ) from e
            except Exception as e:
                raise RuntimeError(
                    f"Failed to load Cross-Encoder model '{self.model_name}': {e}"
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

    def get_backend_name(self) -> str:
        """Return the backend identifier.

        Returns:
            "cross_encoder"
        """
        return self.backend_name
