"""OpenAI Embedding provider implementation.

This module provides integration with OpenAI's Embedding API,
supporting models like text-embedding-3-small, text-embedding-3-large, text-embedding-ada-002.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, List, Optional

from openai import OpenAI

from src.libs.embedding.base_embedding import BaseEmbedding
from src.observability.logger import get_logger

if TYPE_CHECKING:
    from src.core.settings import Settings

logger = get_logger(__name__)


class OpenAIEmbedding(BaseEmbedding):
    """OpenAI Embedding provider implementation.

    Supports OpenAI Embedding API with models like text-embedding-3-small,
    text-embedding-3-large, text-embedding-ada-002. Configuration is driven
    by settings.yaml.

    Design Principles Applied:
    - Pluggable: Implements BaseEmbedding interface for seamless swapping.
    - Config-Driven: API key and model from settings.
    - Fail-Fast: Validates configuration on initialization.
    - Observable: Logs API calls and errors.
    """

    # Model dimension mappings for common OpenAI embedding models
    MODEL_DIMENSIONS = {
        "text-embedding-3-small": 1536,
        "text-embedding-3-large": 3072,
        "text-embedding-ada-002": 1536,
    }

    def __init__(self, settings: Settings, **kwargs: Any):
        """Initialize OpenAI Embedding provider.

        Args:
            settings: Application settings containing Embedding configuration.
            **kwargs: Optional overrides (model, api_key, batch_size, etc.).

        Raises:
            ValueError: If required configuration is missing.
        """
        self.settings = settings

        # Extract configuration with fallback to kwargs
        self.api_key = kwargs.get("api_key") or getattr(
            settings.embedding, "api_key", None
        )
        self.model = kwargs.get("model") or getattr(
            settings.embedding, "model", "text-embedding-3-small"
        )
        self.batch_size = kwargs.get("batch_size", 100)  # OpenAI batch limit

        # Validate required configuration
        if not self.api_key:
            raise ValueError(
                "OpenAI API key is required. "
                "Set 'embedding.api_key' in settings.yaml or set OPENAI_API_KEY env var."
            )

        # Initialize OpenAI client
        try:
            self.client = OpenAI(api_key=self.api_key)
            logger.info(f"Initialized OpenAI Embedding with model: {self.model}")
        except Exception as e:
            raise RuntimeError(f"Failed to initialize OpenAI client: {e}") from e

    def embed(
        self,
        texts: List[str],
        trace: Optional[Any] = None,
        **kwargs: Any,
    ) -> List[List[float]]:
        """Embed a list of texts into dense vectors using OpenAI API.

        Args:
            texts: List of text strings to embed. Must be non-empty.
            trace: Optional TraceContext for observability (reserved for Stage F).
            **kwargs: Optional parameters (dimensions, encoding_format, etc.).

        Returns:
            A list of embedding vectors. Each vector is a list of floats.

        Raises:
            ValueError: If texts list is empty or contains invalid entries.
            RuntimeError: If the OpenAI API call fails.

        Example:
            >>> embedding = OpenAIEmbedding(settings)
            >>> vectors = embedding.embed(["Hello world", "Foo bar"])
            >>> len(vectors) == 2
            True
        """
        # Validate input
        self.validate_texts(texts)

        # Handle empty input
        if not texts:
            raise ValueError("Texts list cannot be empty")

        # Batch processing for large inputs
        all_embeddings: List[List[float]] = []

        try:
            for i in range(0, len(texts), self.batch_size):
                batch = texts[i : i + self.batch_size]

                # Call OpenAI API
                response = self.client.embeddings.create(
                    model=self.model,
                    input=batch,
                    **kwargs,
                )

                # Extract embeddings from response
                batch_embeddings = [item.embedding for item in response.data]
                all_embeddings.extend(batch_embeddings)

                if trace:
                    trace.record_stage(
                        stage_name="openai_embedding",
                        data={
                            "provider": "openai",
                            "model": self.model,
                            "batch_size": len(batch),
                            "total_texts": len(texts),
                        },
                    )

            logger.debug(
                f"Successfully embedded {len(texts)} texts using OpenAI {self.model}"
            )
            return all_embeddings

        except Exception as e:
            error_msg = f"OpenAI Embedding API call failed: {e}"
            logger.error(error_msg)
            raise RuntimeError(error_msg) from e

    def get_model_name(self) -> str:
        """Get the model name used by this provider.

        Returns:
            The OpenAI model identifier string.
        """
        return self.model

    def get_dimension(self) -> int:
        """Get the embedding vector dimension.

        Returns:
            The number of dimensions in the embedding vectors.

        Note:
            Returns the dimension based on the model. If the model is not
            recognized, returns 1536 as the default dimension.
        """
        return self.MODEL_DIMENSIONS.get(self.model, 1536)
