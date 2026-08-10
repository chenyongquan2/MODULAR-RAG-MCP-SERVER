"""GLM (ZhipuAI) LLM provider implementation.

This module provides integration with ZhipuAI's GLM API,
supporting models like glm-4, glm-4-flash, glm-4-plus, etc.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, List, Optional

from openai import OpenAI

from src.libs.llm.base_llm import BaseLLM
from src.observability.logger import get_logger

if TYPE_CHECKING:
    from src.core.settings import Settings

logger = get_logger(__name__)


class GLMLLM(BaseLLM):
    """GLM (ZhipuAI) LLM provider implementation.

    Supports ZhipuAI GLM API with models like glm-4, glm-4-flash, glm-4-plus.
    Configuration is driven by settings.yaml.

    Design Principles Applied:
    - Pluggable: Implements BaseLLM interface for seamless swapping.
    - Config-Driven: API key and model from settings.
    - Fail-Fast: Validates configuration on initialization.
    - Observable: Logs API calls and errors.
    """

    DEFAULT_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"

    def __init__(self, settings: Settings, **kwargs: Any):
        """Initialize GLM LLM provider.

        Args:
            settings: Application settings containing LLM configuration.
            **kwargs: Optional overrides (model, api_key, base_url, etc.).

        Raises:
            ValueError: If required configuration is missing.
        """
        self.settings = settings

        self.api_key = kwargs.get("api_key") or getattr(
            settings.llm, "api_key", None
        )
        self.model = kwargs.get("model") or getattr(settings.llm, "model", "glm-4")
        self.base_url = kwargs.get("base_url") or getattr(
            settings.llm, "base_url", self.DEFAULT_BASE_URL
        )

        if not self.api_key:
            raise ValueError(
                "GLM API key is required. "
                "Set 'llm.api_key' in settings.yaml or set ZHIPUAI_API_KEY env var."
            )

        # feature-004 T035:显式传 timeout / max_retries。
        #
        # 此前这里只传 api_key + base_url,settings 里的超时配置根本没接进来 ——
        # 属于"声明了但不起作用"的死配置。后果在批量任务上很实际:42 条金标的
        # 评估里任意一次网关抖动就让整轮中止(评估器遇首个答案生成失败即
        # fail-fast),前面跑掉的一小时全部白费。
        self._client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=float(getattr(settings.llm, "request_timeout_sec", 120)),
            max_retries=int(getattr(settings.llm, "max_retries", 3)),
        )

        logger.info("GLM LLM initialized: model=%s, base_url=%s", self.model, self.base_url)

    def chat(
        self,
        messages: List[dict[str, str]],
        trace: Optional[Any] = None,
        **kwargs: Any,
    ) -> str:
        """Generate a chat completion using GLM API.

        Args:
            messages: List of message dictionaries with 'role' and 'content'.
            trace: Optional TraceContext for observability (reserved).
            **kwargs: Additional parameters (temperature, max_tokens, etc.).

        Returns:
            The generated response text.

        Raises:
            RuntimeError: If the API call fails.
        """
        # trace is reserved for observability, not passed to API
        # Use pop() to remove and capture the value if present
        _ = kwargs.pop("trace", None)

        try:
            response = self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                **kwargs,
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            logger.error("GLM API call failed: %s", e)
            raise RuntimeError(f"GLM API call failed: {e}") from e

    def get_model_name(self) -> str:
        """Get the model name.

        Returns:
            The model name string.
        """
        return self.model

    def get_backend_name(self) -> str:
        """Get the backend name.

        Returns:
            The backend name 'glm'.
        """
        return "glm"
