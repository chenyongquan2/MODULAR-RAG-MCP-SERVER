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
from typing import TYPE_CHECKING, Any, List, Optional

from src.observability.logger import get_logger

if TYPE_CHECKING:
    from src.core.settings import Settings
    from src.observability.evaluation.judge_call_collector import JudgeCallCollector

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# 子配置节 → 项目 BaseLLM(Judge / Screening 共用, Feature-003 T004 抽出)
# ---------------------------------------------------------------------------


def build_project_llm_from_sub_settings(settings: "Settings", sub: Any) -> Any:
    """把 ``evaluation`` 下的某个子 LLM 配置节投影成顶层 LLMSettings 并创建实例。

    ``LLMFactory.create()`` 只读 ``settings.llm.provider``,且 ``override_kwargs``
    是透传给 provider 构造函数的,**无法用来覆写 provider**。因此想用一个与顶层
    不同的 provider,唯一的办法是浅拷贝 settings 并替换 ``.llm`` 子节。

    本函数由 :func:`build_ragas_judge`(``evaluation.judge_llm``)与 Feature-003
    的预筛流程(``evaluation.screening_llm``)共用 —— 两者需求同构,抽出以免第三次
    复制同样的投影逻辑。

    Args:
        settings: 全局 Settings 实例。
        sub: 子配置节,需具备 ``provider`` / ``model`` / ``api_key`` / ``base_url``
            四个属性(``JudgeLLMSettings`` 与 ``ScreeningLLMSettings`` 均满足)。

    Returns:
        项目 ``BaseLLM`` 实例(由 ``LLMFactory`` 按 ``sub.provider`` 创建)。

    Raises:
        ValueError: provider 未注册或配置非法(由 ``LLMFactory.create`` 抛出)。

    Note:
        宪法 § I:本函数只经 ``LLMFactory`` 创建实例,不 import 任何具体 provider。
    """
    from src.core.settings import LLMSettings as _LLMSettings
    from src.libs.llm.llm_factory import LLMFactory

    sub_llm_settings = _LLMSettings(
        provider=sub.provider,
        model=sub.model,
        api_key=sub.api_key,
        base_url=sub.base_url or "",
    )

    # 浅拷贝顶层 settings,把 .llm 替换为子配置节
    # (LLMFactory.create() 只读 settings.llm,不读其他段)
    projected = _copy_module.copy(settings)
    projected.llm = sub_llm_settings

    return LLMFactory.create(projected)


# ---------------------------------------------------------------------------
# Judge LLM 包装 (FR-016, research § Decision 2)
# ---------------------------------------------------------------------------


def build_ragas_judge(
    settings: "Settings",
    collector: Optional["JudgeCallCollector"] = None,
) -> Any:
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
        collector: (change evaluation-degradation-governance)judge 调用结果
            采集器。显式传入而非全局状态(硬约束 4)。为 ``None`` 时不采集,
            行为与本能力落地之前完全一致。

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

    eval_judge = settings.evaluation.judge_llm

    # 把 evaluation.judge_llm.* 投影成顶层 LLMSettings,让 LLMFactory 复用
    # 项目既有 provider 注册(glm/azure/openai/ollama/deepseek)。
    # 投影逻辑已抽成共享函数,与 Feature-003 的预筛流程共用。
    project_llm = build_project_llm_from_sub_settings(settings, eval_judge)

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
            # 注:judge 路径**刻意不传** max_tokens。曾怀疑它是降级主因(labeling
            # 路径正因这个参数给少了出现过空响应),但 T-3.1 归因否证了这条:
            # 595 次成功判定调用**零空响应**,最长响应 3378 字符,模型在自由书写。
            # 加一个不解决任何问题的配置项 = 下一个死配置(见 acceptance.md § 线索 1)。
            chat_kwargs.update(kwargs)
            # change evaluation-degradation-governance T-2.1:
            # 这里是**唯一**还能看到 judge 原始响应的地方 —— 再往上走
            # RAGAS 就把它吞掉、只留一个 NaN 了。采集器显式传入(非全局
            # 状态,硬约束 4),collector 为 None 时行为与改造前完全一致。
            if collector is None:
                return project_llm.chat(messages, **chat_kwargs)
            try:
                response = project_llm.chat(messages, **chat_kwargs)
            except Exception as exc:
                collector.record_failure(exc)
                raise
            collector.record_success(response)
            return response

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
# Batched docstore(性能优化, 2026-04-28)
# ---------------------------------------------------------------------------


def _make_batched_docstore_class() -> Any:
    """返回 ``BatchedInMemoryDocumentStore`` 类(延迟构建,避免顶层 import ragas)。

    重写 ``add_nodes`` 把 N 次单条 embed_text 改为一次批量 embed_documents:

    原 RAGAS 行为:
        for node: executor.submit(embed_text, node.text)  # N 次 1-text HTTP
    实测:5000 nodes ~50 min(asyncio 线程池束缚到 ~1.4 it/s)

    优化后行为:
        embeddings.embed_documents([all node texts])  # 1-2 次批量 HTTP
        executor.submit(extractor.extract, node)      # keyphrase 仍并发
    实测:5000 nodes embed 阶段 ~1 min(60x);extract 不变。

    Returns:
        BatchedInMemoryDocumentStore 类(继承自 InMemoryDocumentStore)。
    """
    from ragas.exceptions import ExceptionInRunner
    from ragas.executor import Executor
    from ragas.testset.docstore import InMemoryDocumentStore
    import numpy as np

    class BatchedInMemoryDocumentStore(InMemoryDocumentStore):
        """覆盖 ``add_nodes`` 让 embedding 一次批量调用,而非 per-node 串行。"""

        def add_nodes(self, nodes: Any, show_progress: bool = True) -> None:
            assert self.embeddings is not None, "Embeddings must be set"
            assert self.extractor is not None, "Extractor must be set"

            # 分两阶段:embedding 批量;keyphrase 仍并发(LLM 调用)
            # ----------- 阶段 1: embedding 批量 -----------
            need_embed_indices: list[int] = []
            need_embed_texts: list[str] = []
            for i, n in enumerate(nodes):
                if n.embedding is None:
                    need_embed_indices.append(i)
                    need_embed_texts.append(n.page_content)

            if need_embed_texts:
                logger.info(
                    "BatchedDocstore: embed_documents batch call (%d texts)",
                    len(need_embed_texts),
                )
                # 调用 wrapper 的 embed_documents → 项目 BaseEmbedding.embed
                # → openai_embedding 批量(一次 HTTP, 最多 500/批, 自动分批)
                embeddings_list = self.embeddings.embed_documents(need_embed_texts)
                for idx, emb in zip(need_embed_indices, embeddings_list):
                    nodes[idx].embedding = emb

            # ----------- 阶段 2: keyphrase 提取(并发,LLM) -----------
            need_extract_indices: list[int] = []
            executor = Executor(
                desc="extracting keyphrases",
                keep_progress_bar=False,
                raise_exceptions=True,
                run_config=self.run_config,
            )
            for i, n in enumerate(nodes):
                if not n.keyphrases:
                    need_extract_indices.append(i)
                    executor.submit(
                        self.extractor.extract,
                        n,
                        name=f"keyphrase-extraction[{i}]",
                    )

            if need_extract_indices:
                results = executor.results()
                if not results:
                    raise ExceptionInRunner()
                for k, idx in enumerate(need_extract_indices):
                    nodes[idx].keyphrases = results[k]

            # ----------- 阶段 3: 落库(沿用父类逻辑) -----------
            for n in nodes:
                if n.embedding is not None and n.keyphrases != []:
                    self.nodes.append(n)
                    self.node_map[n.doc_id] = n
                    assert isinstance(
                        n.embedding, (list, np.ndarray)
                    ), "Embedding must be list or np.ndarray"
                    self.node_embeddings_list.append(n.embedding)

            self.calculate_nodes_docs_similarity()
            self.set_node_relataionships()

    return BatchedInMemoryDocumentStore


# 模块级延迟绑定:第一次 import BatchedInMemoryDocumentStore 时才触发构建
def __getattr__(name: str) -> Any:
    if name == "BatchedInMemoryDocumentStore":
        cls = _make_batched_docstore_class()
        # 缓存到模块命名空间,后续 import 直接拿
        globals()[name] = cls
        return cls
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# ---------------------------------------------------------------------------
# Identifier 助手(供 EvaluationReport 的 judge_llm_identifier /
# embedding_identifier 字段使用)
# ---------------------------------------------------------------------------


def get_judge_identifier(settings: "Settings") -> str:
    """返回 ``"<provider>:<model>"`` 形式的 Judge LLM 标识。"""
    return f"{settings.evaluation.judge_llm.provider}:{settings.evaluation.judge_llm.model}"


def get_screening_identifier(settings: "Settings") -> str:
    """返回 ``"<provider>:<model>"`` 形式的预筛 LLM 标识 (Feature-003 FR-002)。

    与 :func:`get_judge_identifier` 同格式,使「预筛端 vs 合成端」可直接比对。
    合成端把 ``get_judge_identifier()`` 的结果写入 candidate 的
    ``_synthesis_metadata.judge_llm_identifier``,故同源判据是两个标识串相等。

    Note:
        判据必须是**完整标识串**相等,不能只比 provider。实测某 candidate 的
        judge 标识为 ``"glm:minimax/minimax-m2.7"`` —— provider 名义是 ``glm``
        但模型经 OpenAI 兼容端点路由到 minimax;若只比 provider,真正异源的
        ``glm:glm-4.6`` 会被误判为同源而遭拒绝。
    """
    screening = settings.evaluation.screening_llm
    return f"{screening.provider}:{screening.model}"


def get_embedding_identifier(settings: "Settings") -> str:
    """返回 ``"<provider>:<model>"`` 形式的 embedding 标识(默认空时复用顶层)。"""
    eval_emb = settings.evaluation.embedding
    provider = eval_emb.provider or settings.embedding.provider
    model = eval_emb.model or settings.embedding.model
    return f"{provider}:{model}"
