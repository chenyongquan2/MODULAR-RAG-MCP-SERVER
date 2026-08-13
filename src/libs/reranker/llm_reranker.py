"""LLM-based reranker implementation.

This module implements a reranker that uses a Large Language Model (LLM)
to score candidate passages based on their relevance to a query. The LLM
is prompted to rate each candidate on a 0-10 scale, which is then used
to reorder the results.

Design Principles Applied:
- Pluggable: Inherits from BaseReranker for seamless swapping.
- Config-Driven: Uses LLMFactory to instantiate the configured LLM.
- Observable: Accepts optional TraceContext for observability integration.
- Fault-Tolerant: Falls back to original order on LLM failure.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from src.observability.logger import get_logger
from src.libs.llm.base_llm import BaseLLM
from src.libs.llm.llm_factory import LLMFactory
from src.libs.reranker.base_reranker import BaseReranker

if TYPE_CHECKING:
    from src.core.settings import Settings

logger = get_logger(__name__)


class LLMReranker(BaseReranker):
    """LLM-based reranker using relevance scoring.

    This reranker prompts an LLM to score each candidate passage on a 0-10
    relevance scale. The candidates are then reordered by their LLM scores.

    The reranker gracefully degrades to the original order if the LLM call
    fails, ensuring system resilience.

    Attributes:
        settings: The application settings.
        llm: The LLM instance used for scoring.
        prompt_template: The prompt template with {query} and {passage} placeholders.
        backend_name: Fixed to "llm".
        model_name: The LLM model identifier.
    """

    def __init__(
        self,
        settings: Settings,
        llm: Optional[BaseLLM] = None,
        prompt_path: Optional[str] = None,
    ):
        """Initialize the LLM reranker.

        Args:
            settings: The application settings containing LLM configuration.
            llm: Optional LLM instance (for testing/dependency injection).
            prompt_path: Optional path to the prompt template file.
                Defaults to "config/prompts/rerank.txt".
        """
        self.settings = settings
        self.llm = llm or LLMFactory.create(settings)
        self.prompt_template = self._load_prompt(prompt_path)
        self.backend_name = "llm"
        self.model_name = self.llm.get_model_name()

    def _load_prompt(self, prompt_path: Optional[str] = None) -> str:
        """Load the prompt template from file with fallback.

        Args:
            prompt_path: Path to the prompt template file.
                Defaults to "config/prompts/rerank.txt".

        Returns:
            The prompt template string with {query} and {passage} placeholders.
        """
        if prompt_path is None:
            prompt_path = "config/prompts/rerank.txt"

        try:
            with open(prompt_path, "r", encoding="utf-8") as f:
                template = f.read()
                logger.info(f"Loaded rerank prompt template from {prompt_path}")
                return template
        except FileNotFoundError:
            logger.warning(
                f"Prompt file not found: {prompt_path}, using fallback template"
            )
            # Fallback default template
            return """You are a relevance scoring assistant. Given a query and a candidate text passage, rate how relevant the passage is to the query.

Score from 0 to 10:
- 0: Completely irrelevant
- 5: Somewhat relevant
- 10: Highly relevant and directly answers the query

Query: {query}

Passage: {passage}

Relevance score (0-10):"""

    def rerank(
        self,
        query: str,
        candidates: List[Dict[str, Any]],
        trace: Optional[Any] = None,
        **kwargs: Any,
    ) -> List[Dict[str, Any]]:
        """Rerank candidates using LLM relevance scoring.

        Each candidate is scored by the LLM on a 0-10 scale, then the list
        is reordered by descending LLM score.

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
            - 'rerank_score': The LLM relevance score (0-1 normalized)
            - 'original_score': The pre-rerank score
            - 'reranked_by': "llm"

            If LLM scoring fails, returns the original order with:
            - 'reranked_by': "none"
            - 'rerank_fallback_reason': Error message

        Raises:
            ValueError: If inputs fail validation.
        """
        # Handle empty candidates early (before validation)
        if not candidates:
            return []

        # Validate inputs
        self.validate_inputs(query, candidates)

        try:
            # Score each candidate using LLM
            scored_candidates = []
            for idx, candidate in enumerate(candidates):
                text = candidate.get("text", "")

                # Construct prompt (truncate passage to avoid token limits)
                prompt = self.prompt_template.format(
                    query=query, passage=text[:2000]  # Max 2000 chars
                )

                # Call LLM (using chat API)
                response = self.llm.chat(
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=10,  # Only need a number
                    temperature=0.0,  # Deterministic output
                )

                # Parse score from response
                llm_score = self._parse_score(response)

                if llm_score is None:
                    logger.warning(
                        f"Failed to parse LLM score for candidate {idx}, "
                        f"using original score"
                    )
                    llm_score = candidate.get("score", 0.0)

                # Add scored candidate
                scored_candidates.append(
                    {
                        **candidate,
                        "rerank_score": llm_score,
                        "original_score": candidate.get("score", 0.0),
                        "reranked_by": "llm",
                    }
                )

            # Sort by LLM score (descending)
            scored_candidates.sort(key=lambda x: x["rerank_score"], reverse=True)

            # Record trace (if provided)
            if trace:
                trace.record_stage(
                    "rerank_llm",
                    method="llm",
                    provider=self.llm.get_backend_name(),
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

            logger.info(f"LLM reranking completed: {len(scored_candidates)} candidates")
            return scored_candidates

        except Exception as e:
            # Graceful degradation: return original order on failure
            logger.error(
                f"LLM reranking failed: {e}, falling back to original order"
            )

            if trace:
                trace.record_stage(
                    "rerank_llm",
                    method="llm",
                    provider=self.llm.get_backend_name(),
                    error=str(e),
                    fallback=True,
                )

            # Mark as fallback
            for candidate in candidates:
                candidate["reranked_by"] = "none"
                candidate["rerank_fallback_reason"] = str(e)

            return candidates

    def _parse_score(self, response: str) -> Optional[float]:
        """Parse relevance score from LLM response.

        Supports multiple formats:
        - "7"
        - "Score: 7"
        - "Relevance score: 7/10"
        - "8.5"

        Args:
            response: The LLM response text.

        Returns:
            Normalized score in [0, 1] range, or None if parsing fails.
        """
        # Extract first numeric value (integer or decimal)
        match = re.search(r"(\d+\.?\d*)", response)
        if match:
            try:
                score = float(match.group(1))
                # Normalize to [0, 1] (assume raw score is 0-10)
                if score > 1.0:
                    score = score / 10.0
                # Clamp to [0, 1]
                return max(0.0, min(1.0, score))
            except ValueError:
                return None
        return None

    def supports_batch_scoring(self) -> bool:
        """LLM 后端支持分批打分。

        对本后端来说超时兜底的价值最大:每条候选一次**独立串行**的网关调用,
        40 条候选就是 40 次往返 —— 一旦网关变慢,整条查询会被拖死。分批让
        Core 层能在批的间隙止损,已打分的部分照样生效。
        """
        return True

    def score_batch(
        self,
        query: str,
        candidates: List[Dict[str, Any]],
    ) -> List[float]:
        """为一批候选打分(每条一次 LLM 调用)。

        解析失败的候选沿用其重排前的分数 —— 与 ``rerank()`` 的行为一致,
        避免一条解析失败就把该候选打到末位。

        Args:
            query: 查询文本。
            candidates: 本批候选,每条需含 ``text``,可含 ``score``。

        Returns:
            与 ``candidates`` 等长、顺序一一对应的分数(已归一化到 [0, 1])。
        """
        scores: List[float] = []
        for candidate in candidates:
            prompt = self.prompt_template.format(
                query=query, passage=candidate.get("text", "")[:2000]
            )
            response = self.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=10,
                temperature=0.0,
            )
            parsed = self._parse_score(response)
            scores.append(
                parsed if parsed is not None else float(candidate.get("score", 0.0))
            )
        return scores

    def get_backend_name(self) -> str:
        """Return the backend identifier.

        Returns:
            "llm"
        """
        return self.backend_name
