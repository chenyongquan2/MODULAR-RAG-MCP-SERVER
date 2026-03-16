"""BGE-M3 Embedding provider implementation.

This module provides integration with BAAI's BGE-M3 embedding model
via OpenAI-compatible API endpoints (compatible with v1/embeddings).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, List, Optional

from openai import OpenAI

from src.libs.embedding.base_embedding import BaseEmbedding
from src.observability.logger import get_logger

if TYPE_CHECKING:
    from src.core.settings import Settings

logger = get_logger(__name__)


class BGEEmbedding(BaseEmbedding):
    """BGE-M3 Embedding provider implementation.

    Supports BAAI's BGE-M3 model via OpenAI-compatible API.
    BGE-M3 is a multilingual embedding model with 1024 dimensions.

    Design Principles Applied:
    - Pluggable: Implements BaseEmbedding interface for seamless swapping.
    - Config-Driven: API key and model from settings.
    - Fail-Fast: Validates configuration on initialization.
    - Observable: Logs API calls and errors.
    """

    # Model dimension mappings for BGE models
    MODEL_DIMENSIONS = {
        "bge-m3": 1024,
        "BAAI/bge-m3": 1024,
        "bge-small-zh-v1.5": 512,
        "bge-large-zh-v1.5": 1024,
    }

    def __init__(self, settings: Settings, **kwargs: Any):
        """Initialize BGE Embedding provider.

        Args:
            settings: Application settings containing Embedding configuration.
            **kwargs: Optional overrides (model, api_key, base_url, batch_size, etc.).

        Raises:
            ValueError: If required configuration is missing.
        """
        self.settings = settings

        # Extract configuration with fallback to kwargs
        self.api_key = kwargs.get("api_key") or getattr(
            settings.embedding, "api_key", None
        )
        self.model = kwargs.get("model") or getattr(
            settings.embedding, "model", "bge-m3"
        )

        # Get base_url from settings or kwargs
        base_url_from_settings = getattr(
            settings.embedding, "base_url", None
        )
        self.base_url = kwargs.get("base_url") or base_url_from_settings
        if self.base_url:
            # 确保移除尾部的斜杠
            self.base_url = self.base_url.rstrip("/")

        self.batch_size = kwargs.get("batch_size", 100)  # Default batch limit

        # Validate required configuration
        if not self.api_key:
            raise ValueError(
                "BGE API key is required. "
                "Set 'embedding.api_key' in settings.yaml."
            )

        if not self.base_url:
            raise ValueError(
                "BGE base_url is required. "
                "Set 'embedding.base_url' in settings.yaml."
            )

        # Initialize OpenAI-compatible client with custom base_url
        # 智能处理 base_url：如果已包含 /v1 则不再添加
        final_base_url = self.base_url
        if not final_base_url.endswith("/v1"):
            final_base_url = f"{final_base_url}/v1"

        try:
            self.client = OpenAI(
                api_key=self.api_key,
                base_url=final_base_url
            )
            logger.info(
                f"Initialized BGE Embedding with model: {self.model}, "
                f"base_url: {final_base_url}"
            )
        except Exception as e:
            raise RuntimeError(f"Failed to initialize BGE client: {e}") from e

    def embed(
        self,
        texts: List[str],
        trace: Optional[Any] = None,
        **kwargs: Any,
    ) -> List[List[float]]:
        """Embed a list of texts into dense vectors using BGE API.

        Args:
            texts: List of text strings to embed. Must be non-empty.
            trace: Optional TraceContext for observability (reserved for Stage F).
            **kwargs: Optional parameters (encoding_format, etc.).

        Returns:
            A list of embedding vectors. Each vector is a list of floats.

        Raises:
            ValueError: If texts list is empty or contains invalid entries.
            RuntimeError: If BGE API call fails.

        Example:
            >>> embedding = BGEEmbedding(settings)
            >>> vectors = embedding.embed(["Hello world", "你好世界"])
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

                # Call BGE API via OpenAI-compatible endpoint
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
                        stage_name="bge_embedding",
                        data={
                            "provider": "bge",
                            "model": self.model,
                            "batch_size": len(batch),
                            "total_texts": len(texts),
                        },
                    )

            logger.debug(
                f"Successfully embedded {len(texts)} texts using BGE {self.model}"
            )
            return all_embeddings

        except Exception as e:
            error_msg = f"BGE Embedding API call failed: {e}"
            logger.error(error_msg)
            raise RuntimeError(error_msg) from e

    def get_model_name(self) -> str:
        """Get model name used by this provider.

        Returns:
            The BGE model identifier string.
        """
        return self.model

    def get_dimension(self) -> int:
        """Get embedding vector dimension.

        Returns:
            The number of dimensions in embedding vectors.

        Note:
            Returns dimension based on model. If model is not
            recognized, returns 1024 as default dimension for BGE-M3.
        """
        return self.MODEL_DIMENSIONS.get(self.model, 1024)

    def get_backend_name(self) -> str:
        """Get the backend name.

        Returns:
            The backend name 'bge'.
        """
        return "bge"
