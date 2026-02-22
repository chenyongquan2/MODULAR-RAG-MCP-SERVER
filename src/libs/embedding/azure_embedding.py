"""Azure OpenAI Embedding provider implementation.

This module provides integration with Azure OpenAI Service Embedding API,
supporting deployed embedding models like text-embedding-ada-002, text-embedding-3-small.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, List, Optional

from openai import AzureOpenAI

from src.libs.embedding.base_embedding import BaseEmbedding
from src.observability.logger import get_logger

if TYPE_CHECKING:
    from src.core.settings import Settings

logger = get_logger(__name__)


class AzureEmbedding(BaseEmbedding):
    """Azure OpenAI Embedding provider implementation.

    Supports Azure OpenAI Service with deployed embedding models. Requires
    Azure-specific configuration (endpoint, api-version, deployment_name).

    Design Principles Applied:
    - Pluggable: Implements BaseEmbedding interface for seamless swapping.
    - Config-Driven: Azure endpoint, api-version, and deployment from settings.
    - Fail-Fast: Validates Azure-specific configuration on initialization.
    - Observable: Logs API calls and errors.
    """

    # Model dimension mappings (same as OpenAI models)
    MODEL_DIMENSIONS = {
        "text-embedding-3-small": 1536,
        "text-embedding-3-large": 3072,
        "text-embedding-ada-002": 1536,
    }

    def __init__(self, settings: Settings, **kwargs: Any):
        """Initialize Azure OpenAI Embedding provider.

        Args:
            settings: Application settings containing Embedding configuration.
            **kwargs: Optional overrides (model, azure_endpoint, api_key, etc.).

        Raises:
            ValueError: If required Azure-specific configuration is missing.
        """
        self.settings = settings

        # Extract Azure-specific configuration
        self.azure_endpoint = kwargs.get("azure_endpoint") or getattr(
            settings.embedding, "azure_endpoint", None
        )
        self.api_key = kwargs.get("api_key") or getattr(
            settings.embedding, "api_key", None
        )
        self.api_version = kwargs.get("api_version") or getattr(
            settings.embedding, "api_version", "2024-02-01"
        )
        self.model = kwargs.get("model") or getattr(
            settings.embedding, "model", "text-embedding-3-small"
        )
        self.batch_size = kwargs.get("batch_size", 100)

        # Validate required Azure configuration
        if not self.azure_endpoint:
            raise ValueError(
                "Azure endpoint is required. "
                "Set 'embedding.azure_endpoint' in settings.yaml."
            )
        if not self.api_key:
            raise ValueError(
                "Azure API key is required. "
                "Set 'embedding.api_key' in settings.yaml or set AZURE_OPENAI_API_KEY env var."
            )

        # Initialize Azure OpenAI client
        try:
            self.client = AzureOpenAI(
                azure_endpoint=self.azure_endpoint,
                api_key=self.api_key,
                api_version=self.api_version,
            )
            logger.info(
                f"Initialized Azure OpenAI Embedding with model: {self.model}, "
                f"endpoint: {self.azure_endpoint}"
            )
        except Exception as e:
            raise RuntimeError(
                f"Failed to initialize Azure OpenAI client: {e}"
            ) from e

    def embed(
        self,
        texts: List[str],
        trace: Optional[Any] = None,
        **kwargs: Any,
    ) -> List[List[float]]:
        """Embed a list of texts into dense vectors using Azure OpenAI API.

        Args:
            texts: List of text strings to embed. Must be non-empty.
            trace: Optional TraceContext for observability (reserved for Stage F).
            **kwargs: Optional parameters (dimensions, encoding_format, etc.).

        Returns:
            A list of embedding vectors. Each vector is a list of floats.

        Raises:
            ValueError: If texts list is empty or contains invalid entries.
            RuntimeError: If the Azure OpenAI API call fails.

        Example:
            >>> embedding = AzureEmbedding(settings)
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

                # Call Azure OpenAI API
                # Note: Azure uses deployment name as model parameter
                response = self.client.embeddings.create(
                    model=self.model,  # This is the deployment name in Azure
                    input=batch,
                    **kwargs,
                )

                # Extract embeddings from response
                batch_embeddings = [item.embedding for item in response.data]
                all_embeddings.extend(batch_embeddings)

                if trace:
                    trace.record_stage(
                        stage_name="azure_embedding",
                        data={
                            "provider": "azure",
                            "model": self.model,
                            "endpoint": self.azure_endpoint,
                            "batch_size": len(batch),
                            "total_texts": len(texts),
                        },
                    )

            logger.debug(
                f"Successfully embedded {len(texts)} texts using Azure OpenAI {self.model}"
            )
            return all_embeddings

        except Exception as e:
            error_msg = (
                f"Azure OpenAI Embedding API call failed "
                f"(endpoint: {self.azure_endpoint}, model: {self.model}): {e}"
            )
            logger.error(error_msg)
            raise RuntimeError(error_msg) from e

    def get_model_name(self) -> str:
        """Get the model name used by this provider.

        Returns:
            The Azure deployment name / model identifier string.
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
