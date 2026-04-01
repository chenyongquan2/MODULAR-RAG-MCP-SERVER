"""GLM (ZhipuAI) Embedding provider implementation.

This module provides integration with ZhipuAI's Embedding API,
supporting models like embedding-2.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, List, Optional

from openai import OpenAI

from src.libs.embedding.base_embedding import BaseEmbedding
from src.observability.logger import get_logger

if TYPE_CHECKING:
    from src.core.settings import Settings

logger = get_logger(__name__)


class GLMEmbedding(BaseEmbedding):
    """GLM (ZhipuAI) Embedding provider implementation.

    Supports ZhipuAI Embedding API with models like embedding-2.
    Configuration is driven by settings.yaml.

    Design Principles Applied:
    - Pluggable: Implements BaseEmbedding interface for seamless swapping.
    - Config-Driven: API key and model from settings.
    - Fail-Fast: Validates configuration on initialization.
    - Observable: Logs API calls and errors.
    """

    DEFAULT_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"

    # GLM Embedding 模型维度对照表
    # embedding-2: 1024 维
    # embedding-3: 1024 维（基础版）
    # embedding-3-pro: 2048 维（专业版，更高精度）
    MODEL_DIMENSIONS = {
        "embedding-2": 1024,
        "embedding-3": 1024,
        "embedding-3-pro": 2048,
    }

    def __init__(self, settings: Settings, **kwargs: Any):
        """Initialize GLM Embedding provider.

        Args:
            settings: Application settings containing Embedding configuration.
            **kwargs: Optional overrides (model, api_key, base_url, etc.).

        Raises:
            ValueError: If required configuration is missing.
        """
        self.settings = settings

        self.api_key = kwargs.get("api_key") or getattr(
            settings.embedding, "api_key", None
        )
        self.model = kwargs.get("model") or getattr(
            settings.embedding, "model", "embedding-2"
        )
        self.base_url = kwargs.get("base_url") or getattr(
            settings.embedding, "base_url", self.DEFAULT_BASE_URL
        )
        self.batch_size = kwargs.get("batch_size", 10)

        if not self.api_key:
            raise ValueError(
                "GLM API key is required. "
                "Set 'embedding.api_key' in settings.yaml or set ZHIPUAI_API_KEY env var."
            )

        self._client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
        )

        logger.info("GLM Embedding initialized: model=%s, base_url=%s", self.model, self.base_url)

    def embed(
        self,
        texts: List[str],
        **kwargs: Any,
    ) -> List[List[float]]:
        """Generate embeddings for a list of texts using GLM API.

        Args:
            texts: List of text strings to embed.
            **kwargs: Additional parameters.

        Returns:
            List of embedding vectors (each vector is a list of floats).

        Raises:
            RuntimeError: If the API call fails.
        """
        if not texts:
            return []

        try:
            response = self._client.embeddings.create(
                model=self.model,
                input=texts,
            )
            embeddings = [item.embedding for item in response.data]
            return embeddings
        except Exception as e:
            logger.error("GLM Embedding API call failed: %s", e)
            raise RuntimeError(f"GLM Embedding API call failed: {e}") from e

    def get_model_name(self) -> str:
        """Get the model name.

        Returns:
            The model name string.
        """
        return self.model

    def get_embedding_dimension(self) -> int:
        """Get the embedding dimension for the current model.

        Returns:
            The embedding dimension (default 1024 for embedding-2).
        """
        return self.MODEL_DIMENSIONS.get(self.model, 1024)

    def get_backend_name(self) -> str:
        """Get the backend name.

        Returns:
            The backend name 'glm-embedding'.
        """
        return "glm-embedding"
