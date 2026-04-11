"""OpenAI Embedding provider implementation.

This module provides integration with OpenAI's Embedding API,
supporting models like text-embedding-3-small, text-embedding-3-large, text-embedding-ada-002.
"""

from __future__ import annotations

import time
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
        "text-embedding-v4": 1024,
    }

    # Model batch size limits (text-embedding-v4 has a strict limit of 10)
    MODEL_BATCH_SIZES = {
        "text-embedding-v4": 10,  # Qwen text-embedding-v4 限制 batch_size <= 10
        "text-embedding-3-small": 500,  # 支持 batch_size=500，每文本耗时约 0.026s
        "text-embedding-3-large": 500,  # 支持 batch_size=500
        "text-embedding-ada-002": 500,  # 支持 batch_size=500
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
        # 根据模型类型设置合适的 batch_size（如果未在 kwargs 中指定）
        default_batch_size = self.MODEL_BATCH_SIZES.get(self.model, 100)
        self.batch_size = kwargs.get("batch_size", default_batch_size)

        # Validate required configuration
        if not self.api_key:
            raise ValueError(
                "OpenAI API key is required. "
                "Set 'embedding.api_key' in settings.yaml or set OPENAI_API_KEY env var."
            )

        # Get base_url from settings or kwargs (supports custom OpenAI-compatible endpoints)
        # 使用 or None 确保空字符串也被处理为 None
        self.base_url = kwargs.get("base_url") or getattr(
            settings.embedding, "base_url", None
        ) or None

        # Initialize OpenAI client
        try:
            client_kwargs = {"api_key": self.api_key}
            if self.base_url:
                client_kwargs["base_url"] = self.base_url.rstrip("/")
            self.client = OpenAI(**client_kwargs)
            logger.info(f"Initialized OpenAI Embedding with model: {self.model}, base_url: {self.base_url or 'default'}")
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
        total_batches = (len(texts) + self.batch_size - 1) // self.batch_size

        logger.info(f"Starting embedding: {len(texts)} texts in {total_batches} batches (batch_size={self.batch_size})")

        try:
            start_time = time.perf_counter()

            for i in range(0, len(texts), self.batch_size):
                batch = texts[i : i + self.batch_size]
                batch_index = i // self.batch_size

                # Call OpenAI API
                response = self.client.embeddings.create(
                    model=self.model,
                    input=batch,
                    **kwargs,
                )

                # Extract embeddings from response
                batch_embeddings = [item.embedding for item in response.data]
                all_embeddings.extend(batch_embeddings)

                # 每处理 5 个批次或最后一个批次输出进度日志
                if (batch_index + 1) % 5 == 0 or batch_index == total_batches - 1:
                    texts_processed = min((batch_index + 1) * self.batch_size, len(texts))
                    logger.info(
                        f"Embedding progress: {batch_index + 1}/{total_batches} batches "
                        f"({texts_processed}/{len(texts)} texts)"
                    )

                if trace:
                    trace.record_stage(
                        "openai_embedding",
                        provider="openai",
                        model=self.model,
                        batch_size=len(batch),
                        total_texts=len(texts),
                    )

            elapsed = time.perf_counter() - start_time
            logger.info(
                f"Embedding completed: {len(texts)} texts in {elapsed:.1f}s "
                f"(avg {elapsed/len(texts)*1000:.1f}ms per text)"
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

    def get_max_batch_size(self) -> int:
        """Get the maximum batch size supported by this provider.

        Returns:
            The maximum number of texts that can be embedded in a single API call.
        """
        return self.MODEL_BATCH_SIZES.get(self.model, 100)
