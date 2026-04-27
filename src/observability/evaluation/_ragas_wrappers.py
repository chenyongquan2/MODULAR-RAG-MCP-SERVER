"""RAGAS 与项目 LLMFactory / EmbeddingFactory 的适配包装层 (Feature-001)。

实现 spec § FR-016 / FR-017 与 research.md § Decision 2 / Decision 6:
通过 LangChain BaseLanguageModel / Embeddings 接口,把项目 BaseLLM /
BaseEmbedding 实例适配成 RAGAS 期待的 BaseRagasLLM / BaseRagasEmbeddings,
让 RAGAS 4 项 metrics 可以使用项目配置的 Judge LLM 与 embedding,而不绑定
具体 provider 也不依赖环境变量直读。

宪法 § I Provider 无关性:本模块只 import LLMFactory / EmbeddingFactory,
不直接 import 任何 provider 实现(glm/openai/azure/...)。

宪法 § II 配置驱动:Judge / embedding 的所有参数来自 settings.yaml 的
evaluation.judge_llm.* / evaluation.embedding.*,见
config/settings.yaml + src/core/settings.py 的 JudgeLLMSettings /
EvaluationEmbeddingSettings。

依赖(可选 import):本模块的两个 build 函数对 ragas / langchain_core 做
延迟 import(只在调用时才加载),从而允许仅做 custom 评估的场景下不必安装
RAGAS 也能 import 本模块的兄弟模块(eval_runner 等)。
"""

from __future__ import annotations

import copy as _copy_module
from typing import TYPE_CHECKING, Any, List

from src.observability.logger import get_logger

if TYPE_CHECKING:
    from src.core.settings import Settings

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Judge LLM 包装 (FR-016, research § Decision 2)
# ---------------------------------------------------------------------------


def build_ragas_judge(settings: "Settings") -> Any:
    """构建 RAGAS 期待的 Judge LLM 包装实例。

    步骤:
        1. 用 ``settings.evaluation.judge_llm.*`` 字段构造一个临时 LLMSettings
           副本,通过 LLMFactory 创建项目 BaseLLM 实例(provider-agnostic)
        2. 把项目 BaseLLM 适配成 LangChain BaseLanguageModel 子类(只需实现
           ``_call(prompt) -> str``,内部调用 BaseLLM.chat() 单轮对话)
        3. 用 ragas.llms.LangchainLLMWrapper 进一步适配为 RAGAS 期待的
           BaseRagasLLM 接口

    Args:
        settings: 全局 Settings 实例,需含 evaluation.judge_llm.* 配置。

    Returns:
        ragas.llms.BaseRagasLLM 实例(实际为 LangchainLLMWrapper);
        可直接赋给 RAGAS metric 的 ``.llm`` 属性。

    Raises:
        ImportError: ragas / langchain_core 缺失时
        ValueError: 配置非法(由 LLMFactory.create 触发)
    """
    # 延迟 import:允许 custom-only 评估场景下不必安装 ragas
    try:
        from langchain_core.language_models.llms import LLM as _LangChainLLM
        from ragas.llms import LangchainLLMWrapper as _LangchainLLMWrapper
    except ImportError as exc:
        raise ImportError(
            "build_ragas_judge requires 'ragas' and 'langchain-core'. "
            "Install via `pip install -e \".[dev]\"` (本 feature 在 pyproject.toml "
            "中已固定 ragas==0.1.21 + langchain-openai)。"
        ) from exc

    from src.core.settings import LLMSettings as _LLMSettings
    from src.libs.llm.llm_factory import LLMFactory

    eval_judge = settings.evaluation.judge_llm

    # 把 evaluation.judge_llm.* 投影成顶层 LLMSettings,让 LLMFactory 复用
    # 项目既有 provider 注册(glm/azure/openai/ollama/deepseek)
    judge_llm_settings = _LLMSettings(
        provider=eval_judge.provider,
        model=eval_judge.model,
        api_key=eval_judge.api_key,
        base_url=eval_judge.base_url or "",
    )

    # 浅拷贝顶层 settings,把 .llm 替换为 judge_llm 配置
    # (LLMFactory.create() 通常只读 settings.llm,不读其他段)
    judge_settings = _copy_module.copy(settings)
    judge_settings.llm = judge_llm_settings

    project_llm = LLMFactory.create(judge_settings)

    class _ProjectLLMAsLangChain(_LangChainLLM):
        """把项目 BaseLLM 适配为 LangChain BaseLLM。

        RAGAS 在 0.1.x 内部用 .invoke() / .agenerate() 调用,LangChain BaseLLM
        会把这些转换为对 _call() 的调用,所以只需实现 _call。
        """

        @property
        def _llm_type(self) -> str:
            return f"project-llm-{eval_judge.provider}"

        def _call(
            self,
            prompt: str,
            stop: Any = None,
            run_manager: Any = None,
            **kwargs: Any,
        ) -> str:
            messages = [{"role": "user", "content": prompt}]
            chat_kwargs: dict[str, Any] = {}
            if eval_judge.temperature is not None:
                chat_kwargs["temperature"] = eval_judge.temperature
            chat_kwargs.update(kwargs)
            return project_llm.chat(messages, **chat_kwargs)

    langchain_llm = _ProjectLLMAsLangChain()
    logger.info(
        "Built RAGAS judge wrapper: provider=%s, model=%s",
        eval_judge.provider,
        eval_judge.model,
    )
    return _LangchainLLMWrapper(langchain_llm)


# ---------------------------------------------------------------------------
# Embedding 包装 (FR-017, research § Decision 6)
# ---------------------------------------------------------------------------


def build_ragas_embedding(settings: "Settings") -> Any:
    """构建 RAGAS 期待的 Embedding 包装实例。

    与 build_ragas_judge 同思路:把项目 BaseEmbedding 适配为 LangChain
    Embeddings 子类,再用 ragas 的 LangchainEmbeddingsWrapper 包一层。

    默认行为:``settings.evaluation.embedding`` 全空时,**复用顶层
    settings.embedding 配置**(避免 train-eval skew,见 spec § FR-017)。

    Args:
        settings: 全局 Settings 实例。

    Returns:
        ragas.embeddings.BaseRagasEmbeddings 实例(实际为
        LangchainEmbeddingsWrapper);可赋给 RAGAS metric 的 ``.embeddings``。

    Raises:
        ImportError: ragas / langchain_core 缺失时
        ValueError: 配置非法
    """
    try:
        from langchain_core.embeddings import Embeddings as _LangChainEmbeddings
        from ragas.embeddings import (
            LangchainEmbeddingsWrapper as _LangchainEmbeddingsWrapper,
        )
    except ImportError as exc:
        raise ImportError(
            "build_ragas_embedding requires 'ragas' and 'langchain-core'."
        ) from exc

    from src.core.settings import EmbeddingSettings as _EmbeddingSettings
    from src.libs.embedding.embedding_factory import EmbeddingFactory

    eval_embedding = settings.evaluation.embedding

    # 默认空 = 复用顶层 production embedding (FR-017)
    use_provider = eval_embedding.provider or settings.embedding.provider
    use_model = eval_embedding.model or settings.embedding.model
    use_api_key = eval_embedding.api_key or settings.embedding.api_key
    use_base_url = eval_embedding.base_url or settings.embedding.base_url or ""

    embedding_settings = _EmbeddingSettings(
        provider=use_provider,
        model=use_model,
        api_key=use_api_key,
        base_url=use_base_url,
    )

    eval_settings_clone = _copy_module.copy(settings)
    eval_settings_clone.embedding = embedding_settings

    project_embedding = EmbeddingFactory.create(eval_settings_clone)

    class _ProjectEmbeddingAsLangChain(_LangChainEmbeddings):
        """把项目 BaseEmbedding 适配为 LangChain Embeddings。

        LangChain Embeddings 协议要求实现 embed_documents / embed_query。
        """

        def embed_documents(self, texts: List[str]) -> List[List[float]]:
            return project_embedding.embed(texts)

        def embed_query(self, text: str) -> List[float]:
            return project_embedding.embed([text])[0]

    langchain_embeddings = _ProjectEmbeddingAsLangChain()
    logger.info(
        "Built RAGAS embedding wrapper: provider=%s, model=%s",
        use_provider,
        use_model,
    )
    return _LangchainEmbeddingsWrapper(langchain_embeddings)


# ---------------------------------------------------------------------------
# Identifier 助手(供 EvaluationReport 的 judge_llm_identifier /
# embedding_identifier 字段使用)
# ---------------------------------------------------------------------------


def get_judge_identifier(settings: "Settings") -> str:
    """返回 ``"<provider>:<model>"`` 形式的 Judge LLM 标识。"""
    return f"{settings.evaluation.judge_llm.provider}:{settings.evaluation.judge_llm.model}"


def get_embedding_identifier(settings: "Settings") -> str:
    """返回 ``"<provider>:<model>"`` 形式的 embedding 标识(默认空时复用顶层)。"""
    eval_emb = settings.evaluation.embedding
    provider = eval_emb.provider or settings.embedding.provider
    model = eval_emb.model or settings.embedding.model
    return f"{provider}:{model}"
