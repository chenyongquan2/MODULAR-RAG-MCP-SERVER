"""Ollama Embedding provider implementation.

This module provides integration with Ollama's Embedding API,
supporting local models like nomic-embed-text, mxbai-embed-large, etc.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, List, Optional

import requests

from src.libs.embedding.base_embedding import BaseEmbedding
from src.observability.logger import get_logger

if TYPE_CHECKING:
    from src.core.settings import Settings

logger = get_logger(__name__)


class OllamaEmbedding(BaseEmbedding):
    """Ollama Embedding provider implementation.

    Supports Ollama Embedding API with local models like nomic-embed-text,
    mxbai-embed-large, etc. Configuration is driven by settings.yaml.

    Design Principles Applied:
    - Pluggable: Implements BaseEmbedding interface for seamless swapping.
    - Config-Driven: Base URL and model from settings.
    - Fail-Fast: Validates configuration on initialization.
    - Observable: Logs API calls and errors.
    """

    # Default model dimensions for common Ollama embedding models
    MODEL_DIMENSIONS = {
        "nomic-embed-text": 768,
        "mxbai-embed-large": 1024,
        "all-minilm": 384,
    }

    def __init__(self, settings: Settings, **kwargs: Any):
        """Initialize Ollama Embedding provider.

        Args:
            settings: Application settings containing Embedding configuration.
            **kwargs: Optional overrides (model, base_url, timeout, etc.).

        Raises:
            ValueError: If required configuration is missing.
        """
        self.settings = settings

        # Extract configuration with fallback to kwargs
        self.base_url = kwargs.get("base_url") or getattr(
            settings.embedding, "base_url", "http://localhost:11434"
        )
        self.model = kwargs.get("model") or getattr(
            settings.embedding, "model", "nomic-embed-text"
        )
        self.timeout = kwargs.get("timeout", 30)

        # Ensure base_url doesn't end with slash
        self.base_url = self.base_url.rstrip("/")

        # Build API endpoint
        self.api_endpoint = f"{self.base_url}/api/embeddings"

        logger.info(
            f"Initialized Ollama Embedding with model: {self.model} "
            f"at {self.base_url}"
        )

    def embed(
        self,
        texts: List[str],
        trace: Optional[Any] = None,
        **kwargs: Any,
    ) -> List[List[float]]:
        """Embed a list of texts into dense vectors using Ollama API.

        Args:
            texts: List of text strings to embed. Must be non-empty.
            trace: Optional TraceContext for observability (reserved for Stage F).
            **kwargs: Optional parameters.

        Returns:
            A list of embedding vectors. Each vector is a list of floats.

        Raises:
            ValueError: If texts list is empty or contains invalid entries.
            RuntimeError: If the Ollama API call fails.

        Example:
            >>> embedding = OllamaEmbedding(settings)
            >>> vectors = embedding.embed(["Hello world", "Foo bar"])
            >>> len(vectors) == 2
            True
        """
        # Validate input
        self.validate_texts(texts)

        # Handle empty input
        if not texts:
            raise ValueError("Texts list cannot be empty")

        all_embeddings: List[List[float]] = []

        try:
            # Ollama API requires individual requests per text
            for i, text in enumerate(texts):
                # Call Ollama API
                response = requests.post(
                    self.api_endpoint,
                    json={"model": self.model, "prompt": text},
                    timeout=self.timeout,
                )

                # Check response status
                response.raise_for_status()

                # Extract embedding from response
                response_data = response.json()
                embedding = response_data.get("embedding")

                if not embedding:
                    raise RuntimeError(
                        f"No embedding returned for text at index {i}"
                    )

                all_embeddings.append(embedding)

                if trace:
                    trace.record_stage(
                        "ollama_embedding",
                        provider="ollama",
                        model=self.model,
                        text_index=i,
                        total_texts=len(texts),
                    )

            logger.debug(
                f"Successfully embedded {len(texts)} texts using Ollama {self.model}"
            )
            return all_embeddings

        except requests.exceptions.ConnectionError as e:
            error_msg = (
                f"Failed to connect to Ollama service at {self.base_url}. "
                f"Ensure Ollama is running and accessible. Error: {e}"
            )
            logger.error(error_msg)
            raise RuntimeError(error_msg) from e

        except requests.exceptions.Timeout as e:
            error_msg = (
                f"Ollama API request timed out after {self.timeout}s. "
                f"Consider increasing the timeout or checking service health. "
                f"Error: {e}"
            )
            logger.error(error_msg)
            raise RuntimeError(error_msg) from e

        except requests.exceptions.HTTPError as e:
            error_msg = f"Ollama API HTTP error: {e}"
            logger.error(error_msg)
            raise RuntimeError(error_msg) from e

        except Exception as e:
            error_msg = f"Ollama Embedding API call failed: {e}"
            logger.error(error_msg)
            raise RuntimeError(error_msg) from e

    def get_model_name(self) -> str:
        """Get the model name used by this provider.

        Returns:
            The Ollama model identifier string.
        """
        return self.model

    def get_dimension(self) -> int:
        """Get the embedding vector dimension.

        Returns:
            The number of dimensions in the embedding vectors.

        Note:
            Returns the dimension based on the model. If the model is not
            recognized, returns 768 as the default dimension (nomic-embed-text).
        """
        return self.MODEL_DIMENSIONS.get(self.model, 768)
