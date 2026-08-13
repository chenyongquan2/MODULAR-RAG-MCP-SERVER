"""配置加载与校验 (Settings)。

读取 config/settings.yaml，解析为 Settings 数据结构，并在启动时校验关键字段存在。

支持环境变量注入：
- 自动加载 .env 文件
- 支持 ${ENV_VAR} 格式的环境变量引用
- 优先级：环境变量 > .env 文件 > settings.yaml
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Literal, Optional

import yaml

# 尝试加载 .env 文件
try:
    from dotenv import load_dotenv
    # 从项目根目录加载 .env 文件
    _project_root = Path(__file__).parent.parent.parent
    _env_file = _project_root / ".env"
    if _env_file.exists():
        load_dotenv(_env_file)
except ImportError:
    pass  # python-dotenv 未安装，跳过


# ---------------------------------------------------------------------------
# Settings 数据结构
# ---------------------------------------------------------------------------


@dataclass
class LLMSettings:
    """LLM 配置。

    Attributes:
        provider: LLM provider(azure | openai | ollama | deepseek | glm)
        model: 模型标识
        azure_endpoint: Azure 专用端点
        api_key: API key(支持 ${VAR} 环境变量注入)
        base_url: API base URL(OpenAI 兼容端点)
        request_timeout_sec: 单次 LLM 调用超时(秒)。此前顶层 LLM 没有这个字段,
            client 用 SDK 默认值,配置改不动 —— 而 42 条金标的批量评估里一次
            网关抖动就会让整轮白跑(feature-004 T035 实测)。
        max_retries: 单次调用的自动重试次数。同上,批量任务需要能扛住瞬时故障。
    """

    provider: str  # azure | openai | ollama | deepseek | glm
    model: str
    azure_endpoint: str = ""
    # repr=False:防止密钥被 dataclass 默认 repr 打进 traceback / 日志 / 断言输出
    api_key: str = field(default="", repr=False)
    base_url: str = ""
    request_timeout_sec: int = 120
    max_retries: int = 3


@dataclass
class EmbeddingSettings:
    """Embedding 配置。"""

    provider: str  # openai | azure | ollama | glm | bge
    model: str
    # repr=False:防止密钥被 dataclass 默认 repr 打进 traceback / 日志 / 断言输出
    api_key: str = field(default="", repr=False)
    base_url: str = ""


@dataclass
class VisionLLMSettings:
    """Vision LLM 配置。"""

    provider: str  # azure
    model: str


@dataclass
class VectorStoreSettings:
    """向量存储配置。

    Attributes:
        backend: 向量库后端标识（当前仅 chroma）。
        persist_path: 向量库持久化目录。
        collection_name: 当前生效的集合名。**dense 与 sparse 两路共用这一个真源** ——
            ``DenseRetriever`` 经 ``VectorStoreFactory`` 用它决定打开哪个物理集合,
            ``SparseRetriever`` 用它决定加载哪个关键词索引文件。切换集合只改这一个值。
        bm25_index_path: 关键词索引文件所在目录。此前由 ``sparse_retriever`` 用
            ``getattr(..., "bm25_index_path", "data/db/bm25")`` 读取,而该字段并不存在
            于本 dataclass —— 属于宪法原则三禁止的"静默回退默认值"。Feature-004 补为
            正式字段。
        bm25_index_format_version: 关键词索引磁盘格式版本。加载时严格校验,不匹配
            立即抛错而非静默降级(见 specs/004-retrieval-infra-fix/contracts/
            bm25_index.schema.md)。
    """

    backend: str  # chroma
    persist_path: str = "./data/db/chroma"
    collection_name: str = "default"  # 集合名称，默认 "default"
    bm25_index_path: str = "./data/db/bm25"
    bm25_index_format_version: int = 2


@dataclass
class RetrievalSettings:
    """检索配置。

    Attributes:
        sparse_backend: 稀疏检索后端标识。
        fusion_algorithm: 融合算法标识(当前仅 rrf)。
        top_k_dense: dense 路召回数量。
        top_k_sparse: sparse 路召回数量。
        top_k_final: 最终返回数量。
        rrf_k: 融合平滑参数,控制排名靠后结果的衰减速度(feature-005 T001)。
            此前硬编码在 ``Fusion.DEFAULT_K``,且 ``Fusion()`` 构造时不读任何
            配置 —— 属宪法原则二禁止的硬编码可调参数。默认值保持 60,确保
            升级后行为逐条不变。

            **为什么必须 > 0**:``k=0`` 时第 1 名得分 1/1、第 2 名 1/2,
            衰减过陡,第 1 名的分量几乎压过其后全部结果之和,融合退化为
            「谁排第一谁赢」,失去平滑意义。
        fusion_weights: 各检索路径在融合中的相对分量(feature-005 T001)。
            键为路径名(``dense`` / ``sparse``),值为非负数。

            **只有相对比例有意义**:``{dense: 1.0, sparse: 0.5}`` 与
            ``{dense: 2.0, sparse: 1.0}`` 产出完全相同的排序 —— 所有得分
            等比缩放,而排序对单调变换不变。因此写比值即可,绝对值无意义。

            配置中缺失的路径缺省为 1.0(新增检索路径时不强制所有部署同步
            改配置);单条路径为 0 合法,等价于关闭该路。
    """

    sparse_backend: str = "bm25"
    fusion_algorithm: str = "rrf"
    top_k_dense: int = 20
    top_k_sparse: int = 20
    top_k_final: int = 10
    rrf_k: int = 60
    fusion_weights: Dict[str, float] = field(
        default_factory=lambda: {"dense": 1.0, "sparse": 1.0}
    )


@dataclass
class QuerySettings:
    """查询响应相关配置。

    控制 MCP 工具 ``query_knowledge_hub`` 返回响应的"响应组装层"行为，
    与 ``RetrievalSettings``（召回阶段）和 ``RerankSettings``（重排阶段）
    相互独立。

    Attributes:
        max_images_per_response: 单次响应返回图片数量上限（正整数，默认 10）。
            检索到的图片超过此数时，按命中 chunk 的 rerank 顺序截取前 N 张。
            设为较大值会增加 MCP 响应体积；0 或负数在 load_settings 时会被拒绝。
    """

    max_images_per_response: int = 10


@dataclass
class RerankSettings:
    """重排配置。

    重排(rerank)是混合检索的第二阶段:dense/sparse 两路召回并融合出候选后,
    用更贵但更准的模型对候选做精细重新排序。与召回用的 bi-encoder 不同,
    cross-encoder 把 query 与文档拼接后一起过 Transformer,精度更高但无法
    预计算,所以只能对少量候选实时打分 —— 这正是 `top_m` 存在的理由。

    Attributes:
        backend: 重排后端。见 VALID_RERANK_BACKENDS。
            - none: 不重排,直接用融合结果
            - cross_encoder: 本地交叉编码器(sentence-transformers),零 token
            - llm: 大模型逐条打分,每条候选一次独立调用,慢且贵
        model: 模型标识。`backend != "none"` 时**必填** —— 刻意不设隐式默认值,
            否则配置留空会静默用上一个可能对语料无效的模型(此前的兜底默认值
            `cross-encoder/ms-marco-MiniLM-L-6-v2` 是纯英文模型,对中文语料
            完全无效且不报错)。
        top_m: 送入重排后端的候选数上限。超出部分按原名次追加在重排结果之后,
            不参与重排但也不丢弃。这是 `llm` 后端唯一能约束调用次数与 token
            消耗的旋钮,也是 `cross_encoder` 后端约束推理耗时的旋钮。
        timeout_sec: 单次重排的总耗时上限(秒)。超时保留已评分部分的排序,
            未评分部分保持原名次追加。cross-encoder 是同步 CPU 推理,没有
            HTTP 客户端那种现成的超时参数,只能靠分批 + 批间计时实现。
        batch_size: 分批推理的批大小。同时决定超时检查的粒度 —— 批越大,
            超时判定越粗(最坏情况会超出 timeout_sec 一个批次的推理时间)。
    """

    backend: str = "none"
    model: str = ""
    top_m: int = 30
    timeout_sec: float = 30.0
    batch_size: int = 8


@dataclass
class SplitterSettings:
    """文本切分配置。"""

    strategy: str = "recursive"
    chunk_size: int = 1000
    chunk_overlap: int = 200


@dataclass
class LoaderSettings:
    """文档加载配置。"""

    provider: str = "pdf"               # pdf | markdown | chm（向后兼容保留）
    extract_images: bool = True         # 是否提取 PDF 中的图片
    max_image_size: int = 2048          # 最大图片尺寸（像素）
    enable_ocr: bool = False            # 是否启用 OCR（扫描版 PDF 需开启，速度约慢 5x）
    enable_table_structure: bool = True # 是否识别表格结构并输出 Markdown 表格语法


@dataclass
class ChunkRefinerSettings:
    """Chunk 精炼配置。"""

    use_llm: bool = False


@dataclass
class MetadataEnricherSettings:
    """元数据增强配置。"""

    use_llm: bool = False


@dataclass
class ImageCaptionerSettings:
    """图片描述生成配置。"""

    enabled: bool = False
    use_fallback: bool = True


@dataclass
class TextEnricherSettings:
    """文本增强器配置。

    用于控制图片描述融合到正文的行为。
    """

    enabled: bool = True
    caption_format: str = "[图片描述: {caption}]"


@dataclass
class IngestionSettings:
    """摄取管道配置。"""

    chunk_refiner: ChunkRefinerSettings = field(
        default_factory=ChunkRefinerSettings
    )
    metadata_enricher: MetadataEnricherSettings = field(
        default_factory=MetadataEnricherSettings
    )
    image_captioner: ImageCaptionerSettings = field(
        default_factory=ImageCaptionerSettings
    )
    text_enricher: TextEnricherSettings = field(
        default_factory=TextEnricherSettings
    )


@dataclass
class JudgeLLMSettings:
    """RAGAS Judge LLM 配置 (FR-016)。

    复用 LLMFactory 注册的 5 个 provider(glm/azure/openai/ollama/deepseek);
    切换 Judge 不需修改评估代码,仅需改本配置后重启。

    Attributes:
        provider: LLM provider(glm/azure/openai/ollama/deepseek)
        model: 模型标识(如 "glm-4")
        api_key: API key(支持 ${VAR} 环境变量注入)
        base_url: API base URL(可选,如 OpenAI 兼容端点)
        temperature: 采样温度(0.0 表示完全确定;Judge 推荐 0.0 以提高判分稳定性)
        request_timeout_sec: 单次 LLM 调用超时(秒)
    """

    provider: str = "glm"
    model: str = "glm-4"
    # repr=False:防止密钥被 dataclass 默认 repr 打进 traceback / 日志 / 断言输出
    api_key: str = field(default="", repr=False)
    base_url: Optional[str] = None
    temperature: float = 0.0
    request_timeout_sec: int = 60


@dataclass
class ScreeningLLMSettings:
    """金标精修的预筛 LLM 配置 (Feature-003 FR-009)。

    仅 ``scripts/refine_testset.py --auto-mode`` 使用。与 JudgeLLMSettings 结构
    对称,同样复用 LLMFactory 注册的 provider,切换预筛模型不需改代码。

    **provider / model 默认为空 = 未启用**。默认交互模式不读本配置,故加载期
    不强制两者非空——否则所有未配置本节的既有用法都会启动失败(违反 FR-004)。
    非空校验推迟到 CLI 入口(仅 --auto-mode 时),见
    specs/003-testset-refine-automation/contracts/settings.screening.schema.md § 3。

    FR-002 要求预筛模型与合成端(evaluation.judge_llm)**异源**,判据是完整
    标识串 ``"<provider>:<model>"`` 不相等而非 provider 不相等。该校验在 CLI
    入口读取 candidate 后执行,不在本处。

    Attributes:
        provider: LLM provider(glm/azure/openai/ollama/deepseek);空 = 未启用
        model: 模型标识;空 = 未启用
        api_key: API key(支持 ${VAR} 环境变量注入)
        base_url: API base URL(可选,如 OpenAI 兼容端点)
        temperature: 采样温度(判定应尽量确定,推荐 0.0)
        request_timeout_sec: 单次 LLM 调用超时(秒)
        keep_threshold: keep 判定且置信度 ≥ 此值 → 自动保留
        drop_threshold: drop 判定且置信度 ≥ 此值 → 自动丢弃
        borderline_ratio_warn: borderline 占比超此值告警(FR-011)
        sample_ratio: 抽样自检比例(FR-006,源自 Feature-001 SC-002)
        compliance_gate: 抽样合规率门控(FR-007,源自 SC-002)

    Note:
        阈值默认值是初始猜测。不同模型的置信度标度不可互换,换预筛模型后必须
        重新校准——与 FR-013「换 Judge 后阈值失效」是同一回事。
    """

    provider: str = ""
    model: str = ""
    # repr=False:dataclass 默认 repr 会把 api_key 原样打进 traceback / 日志 /
    # pytest 断言输出。实测一次断言失败就把完整密钥打到了控制台。
    api_key: str = field(default="", repr=False)
    base_url: Optional[str] = None
    temperature: float = 0.0
    request_timeout_sec: int = 60
    keep_threshold: float = 0.80
    drop_threshold: float = 0.80
    borderline_ratio_warn: float = 0.40
    sample_ratio: float = 0.10
    compliance_gate: float = 0.90

    def is_enabled(self) -> bool:
        """provider 与 model 均非空时视为已配置(可用于 --auto-mode)。"""
        return bool(self.provider.strip()) and bool(self.model.strip())

    def thresholds_snapshot(self) -> dict[str, float]:
        """返回阈值快照(写入金标 _review_metadata.thresholds_snapshot)。

        FR-005 要求阈值随金标落盘,使换模型后的历史金标仍可追溯当时判定条件。
        """
        return {
            "keep_threshold": self.keep_threshold,
            "drop_threshold": self.drop_threshold,
            "borderline_ratio_warn": self.borderline_ratio_warn,
            "sample_ratio": self.sample_ratio,
            "compliance_gate": self.compliance_gate,
        }


@dataclass
class EvaluationEmbeddingSettings:
    """评估流程使用的 embedding 配置 (FR-017)。

    所有字段为空时表示"复用顶层 settings.embedding 配置"(避免 train-eval skew)。
    复用 EmbeddingFactory 注册的 provider(bge/openai/azure/ollama/glm)。

    Attributes:
        provider: embedding provider(空 = 复用顶层)
        model: embedding 模型标识(空 = 复用顶层)
        api_key: API key(支持 ${VAR} 环境变量注入)
        base_url: API base URL(可选)
    """

    provider: str = ""
    model: str = ""
    # repr=False:防止密钥被 dataclass 默认 repr 打进 traceback / 日志 / 断言输出
    api_key: str = field(default="", repr=False)
    base_url: Optional[str] = None


@dataclass
class AcceptanceThresholds:
    """8 项主聚合指标的 pass/fail 阈值 (FR-013)。

    默认值为 spec § FR-013 锁定的业界参考值(2026-04-25 clarify 决议)。
    用户可在 settings.yaml 中覆盖任一字段;未覆盖字段使用本默认值。

    切换 Judge LLM 后建议重新校准本阈值——见 spec.md § Assumptions
    "Judge 切换与阈值校准"。
    """

    ragas__context_recall: float = 0.70
    ragas__context_precision: float = 0.65
    ragas__faithfulness: float = 0.85
    ragas__answer_relevancy: float = 0.75
    custom__hit_rate: float = 0.60
    custom__mrr: float = 0.55
    custom__recall: float = 0.70
    custom__ndcg: float = 0.55

    def to_dict(self) -> dict[str, float]:
        """返回 8 项阈值的快照字典(用于 EvaluationReport.acceptance_thresholds_snapshot)。"""
        return {
            "ragas__context_recall": self.ragas__context_recall,
            "ragas__context_precision": self.ragas__context_precision,
            "ragas__faithfulness": self.ragas__faithfulness,
            "ragas__answer_relevancy": self.ragas__answer_relevancy,
            "custom__hit_rate": self.custom__hit_rate,
            "custom__mrr": self.custom__mrr,
            "custom__recall": self.custom__recall,
            "custom__ndcg": self.custom__ndcg,
        }


@dataclass
class LabelingLLMSettings:
    """金标标注的判定 LLM 配置 (change retriever-agnostic-golden-labels)。

    仅 ``scripts/label_golden_chunks.py`` 使用。与 JudgeLLMSettings /
    ScreeningLLMSettings 结构对称,同样复用 LLMFactory 注册的 provider,
    换判定模型不需改代码。

    **provider / model 默认为空 = 未启用**。非空校验推迟到 CLI 入口 ——
    否则所有不做标注的既有用法都会启动失败(与 ScreeningLLMSettings 同理)。

    **为什么不复用 screening_llm**:两者的异源对象相同(都要 ≠ 合成端
    ``judge_llm``),但**阈值标度不同** —— 预筛问的是「这条 case 该不该留」,
    标注问的是「这个 chunk 相关到什么程度」。共用一份配置会让两处校准互相
    干扰,而「换模型必须重新校准」正是本项目已记录的陷阱。

    异源判据是完整标识串 ``"<provider>:<model>"`` 不相等,**不是 provider 不
    相等** —— 实测某 candidate 的 judge 标识为 ``"glm:minimax/minimax-m2.7"``,
    provider 名义是 glm 但模型经 OpenAI 兼容端点路由到 minimax。该校验在 CLI
    入口读取 candidate 后执行(需要 candidate 里的合成端标识),不在本处。

    Attributes:
        provider: LLM provider(glm/azure/openai/ollama/deepseek);空 = 未启用
        model: 模型标识;空 = 未启用
        api_key: API key(支持 ${VAR} 环境变量注入)
        base_url: API base URL(可选,如 OpenAI 兼容端点)
        temperature: 采样温度(判定应尽量确定,推荐 0.0)
        request_timeout_sec: 单次 LLM 调用超时(秒)
        max_retries: 单次调用的自动重试次数。网关实测存在常态性超时,
            标注要发上千次调用,没有重试会让整轮频繁中断
    """

    provider: str = ""
    model: str = ""
    # repr=False:dataclass 默认 repr 会把 api_key 原样打进 traceback / 日志 /
    # pytest 断言输出。实测一次断言失败就把完整密钥打到了控制台。
    api_key: str = field(default="", repr=False)
    base_url: Optional[str] = None
    temperature: float = 0.0
    request_timeout_sec: int = 60
    max_retries: int = 3

    def is_enabled(self) -> bool:
        """provider 与 model 均非空才算启用。"""
        return bool(self.provider.strip()) and bool(self.model.strip())


@dataclass
class LabelingSettings:
    """金标标注配置 (change retriever-agnostic-golden-labels)。

    本节控制「哪些 chunk 算作某个问题的正确答案」这个基准是怎么造出来的。

    背景 —— 第一代金标的 ``expected_chunk_ids`` 由 ``backfill_chunk_ids.py``
    把 ground_truth 编码后查 dense top-5 回填,即**标准答案就是 embedding 认为
    最像答案的那几条**。后果是所有召回类指标都锚定在 dense 一路上:2026-08-13
    的重排 A/B 实测 MRR 从 0.4914 掉到 0.3668,而同一模型在集成测试里每次都能
    把故意放在末位的相关段落提到首位 —— 模型在做正确的事,指标却在跌。

    本节的做法:多路召回各取 top-N 取并集(池化),再让 LLM 逐条判定分级相关度。
    没有任何一路能垄断标准答案。

    Attributes:
        pool_top_n_dense: 稠密检索取多少条进候选池。
        pool_top_n_sparse: 稀疏检索(BM25)取多少条进候选池。
        pool_top_n_rerank: 重排后顺序取多少条进候选池。**0 = 不启用该路** ——
            重排依赖是 optional extra(`.[rerank]`),默认置 0 保证核心安装
            即可标注。
        relevance_threshold: 分级相关度 >= 此值纳入 expected_chunk_ids。
            分级含义:0 无关 / 1 沾边 / 2 部分支撑 / 3 直接回答。
        max_judgements: 单次标注的判定调用上限。达到即停止并写出部分结果,
            元数据记录被跳过的候选数 —— **不静默截断**。按池化后每 case 约
            25-40 个候选估算,中英金标 48 条 case 约需 1200-1900 次调用。
        judge_failure_warn_ratio: 判定失败(输出无法解析)比例超此值告警。
            与「模型整体不可用」严格区分 —— 后者应显式失败而非告警。
        dense_overlap_warn: 产出与「纯 dense top-5」的 Jaccard 超此值告警,
            提示池化或判定疑似未生效。这守的是「新方法到底有没有起作用」。
        human_agreement_warn: 人工抽检一致率低于此值告警。

    Note:
        ``relevance_threshold`` / ``human_agreement_warn`` 的默认值是初始猜测。
        不同判定模型的标度不可互换,换模型后必须重新校准 —— 与「换 Judge 后
        acceptance_thresholds 失效」是同一回事。
    """

    pool_top_n_dense: int = 20
    pool_top_n_sparse: int = 20
    pool_top_n_rerank: int = 0
    relevance_threshold: int = 2
    max_judgements: int = 2000
    judge_failure_warn_ratio: float = 0.10
    dense_overlap_warn: float = 0.90
    human_agreement_warn: float = 0.80


@dataclass
class EvaluationSettings:
    """评估配置(Feature-001 后扩展)。

    详见 specs/001-rag-acceptance/data-model.md § 1.1 与
    specs/001-rag-acceptance/contracts/settings.evaluation.schema.md。

    Attributes:
        schema_version: YAML 中的 _schema_version 字段(本 build 仅支持 1)
        backends: 启用的评估后端(custom 永久启用,ragas 视场景启用)
        golden_test_set: 占位金标路径(US1 阶段使用)
        golden_test_sets_by_lang: 中英分语种金标(US2 完成后填充)
        judge_llm: Judge LLM 配置(ragas backend 启用时必须填)
        screening_llm: 金标精修预筛 LLM 配置(Feature-003;默认空 = 未启用)
        embedding: 评估期 embedding 配置(默认空 = 复用 production)
        acceptance_thresholds: 8 项主聚合指标的 pass/fail 阈值
        by_tag_dimensions: 切片维度白名单(MVP 仅支持 content_type / difficulty)
        tag_slice_min_samples: 切片样本量下限(< 此值的切片标 null + _skipped_reason)
        report_archive_dir: 评估报告归档目录
        baseline_store_path: 基线标记单文件路径
        chunk_id_validation: 评估前是否校验 expected_chunk_ids 在 vector store 中存在
    """

    schema_version: int = 1
    backends: list[str] = field(default_factory=lambda: ["custom"])
    golden_test_set: str = "./tests/fixtures/golden_test_set.json"
    golden_test_sets_by_lang: dict[str, str] = field(default_factory=dict)
    judge_llm: JudgeLLMSettings = field(default_factory=JudgeLLMSettings)
    screening_llm: ScreeningLLMSettings = field(default_factory=ScreeningLLMSettings)
    labeling_llm: LabelingLLMSettings = field(default_factory=LabelingLLMSettings)
    labeling: LabelingSettings = field(default_factory=LabelingSettings)
    embedding: EvaluationEmbeddingSettings = field(default_factory=EvaluationEmbeddingSettings)
    acceptance_thresholds: AcceptanceThresholds = field(default_factory=AcceptanceThresholds)
    by_tag_dimensions: list[str] = field(default_factory=lambda: ["content_type", "difficulty"])
    tag_slice_min_samples: int = 5
    report_archive_dir: str = "./logs/evaluation_reports"
    baseline_store_path: str = "./logs/baselines.json"
    chunk_id_validation: bool = True


@dataclass
class ObservabilitySettings:
    """可观测性配置。"""

    enabled: bool = True
    log_file: str = "./logs/traces.jsonl"


# 允许的 transport 类型，集中定义以避免各处字符串字面量散落
TransportType = Literal["stdio", "sse"]
VALID_TRANSPORTS: frozenset[str] = frozenset({"stdio", "sse"})

# 允许的重排后端，与 src/libs/reranker/reranker_factory.py 的注册表保持一致。
# 集中定义在此是为了让启动期校验不必 import factory 就能挡掉拼错的后端名
# （真正的「后端是否可用」探测在 RerankerFactory.probe_backend，见 T-2.2）。
RerankBackendType = Literal["none", "cross_encoder", "llm"]
VALID_RERANK_BACKENDS: frozenset[str] = frozenset({"none", "cross_encoder", "llm"})


@dataclass
class MCPServerSettings:
    """MCP Server 传输层配置。"""

    transport: str = "stdio"  # 见 TransportType，取值 "stdio" | "sse"
    host: str = "127.0.0.1"
    port: int = 8000
    sse_path: str = "/sse"
    message_path: str = "/messages/"


@dataclass
class Settings:
    """全局配置，对应 config/settings.yaml 的完整结构。"""

    llm: LLMSettings
    embedding: EmbeddingSettings
    vision_llm: VisionLLMSettings
    vector_store: VectorStoreSettings
    loader: LoaderSettings = field(default_factory=LoaderSettings)
    retrieval: RetrievalSettings = field(default_factory=RetrievalSettings)
    query: QuerySettings = field(default_factory=QuerySettings)
    rerank: RerankSettings = field(default_factory=RerankSettings)
    splitter: SplitterSettings = field(default_factory=SplitterSettings)
    ingestion: IngestionSettings = field(default_factory=IngestionSettings)
    evaluation: EvaluationSettings = field(default_factory=EvaluationSettings)
    observability: ObservabilitySettings = field(
        default_factory=ObservabilitySettings
    )
    mcp_server: MCPServerSettings = field(default_factory=MCPServerSettings)


# ---------------------------------------------------------------------------
# 必填字段定义（用 dotted path 描述）
# ---------------------------------------------------------------------------

_REQUIRED_FIELDS: list[tuple[str, ...]] = [
    ("llm", "provider"),
    ("llm", "model"),
    ("embedding", "provider"),
    ("embedding", "model"),
    ("vector_store", "backend"),
]


# ---------------------------------------------------------------------------
# 异常
# ---------------------------------------------------------------------------


class SettingsError(Exception):
    """配置加载或校验异常。"""


# ---------------------------------------------------------------------------
# 内部辅助
# ---------------------------------------------------------------------------

# 环境变量引用模式: ${VAR_NAME} 或 ${VAR_NAME:-default_value}
_ENV_VAR_PATTERN = re.compile(r"\$\{([^}:]+)(?::-([^}]*))?\}")


def _resolve_env_vars(value: Any) -> Any:
    """递归解析配置值中的环境变量引用。

    支持格式：
    - ${VAR_NAME} - 引用环境变量
    - ${VAR_NAME:-default} - 带默认值的环境变量引用

    Args:
        value: 配置值（可以是字符串、字典、列表等）

    Returns:
        解析后的值，环境变量引用被替换为实际值
    """
    if isinstance(value, str):
        def replace_env_var(match: re.Match) -> str:
            var_name = match.group(1)
            default_value = match.group(2)  # 可能为 None
            env_value = os.environ.get(var_name)
            if env_value is not None:
                return env_value
            if default_value is not None:
                return default_value
            # 环境变量不存在且无默认值，返回原字符串
            return match.group(0)

        return _ENV_VAR_PATTERN.sub(replace_env_var, value)

    elif isinstance(value, dict):
        return {k: _resolve_env_vars(v) for k, v in value.items()}

    elif isinstance(value, list):
        return [_resolve_env_vars(item) for item in value]

    return value


def _get_nested(data: dict[str, Any], keys: tuple[str, ...]) -> Any:
    """按 key 路径从嵌套字典取值，取不到返回 ``None``。"""
    current: Any = data
    for k in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(k)
    return current


def _build_sub_settings(
    raw: dict[str, Any] | None,
    cls: type,
    section_name: str,
) -> Any:
    """从原始字典构建子 dataclass 实例。

    如果 *raw* 为 ``None`` 或不是 dict，对有默认值的 section 返回默认实例，
    否则抛出 ``SettingsError``。
    """
    if raw is None or not isinstance(raw, dict):
        # 尝试无参构造（利用 dataclass 默认值）
        try:
            return cls()
        except TypeError:
            raise SettingsError(
                f"Missing required config section: '{section_name}'"
            )
    try:
        return cls(**{k: v for k, v in raw.items() if v is not None})
    except TypeError as exc:
        raise SettingsError(
            f"Incomplete fields in config section '{section_name}': {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# 公共 API
# ---------------------------------------------------------------------------


# 常用字段的环境变量映射
_ENV_FIELD_MAPPING: dict[tuple[str, ...], str] = {
    ("llm", "api_key"): "LLM_API_KEY",
    ("embedding", "api_key"): "EMBEDDING_API_KEY",
}


def _inject_env_vars(raw: dict[str, Any]) -> dict[str, Any]:
    """注入常用环境变量到配置。

    如果配置中某个字段为空且对应的环境变量存在，则自动注入。

    Args:
        raw: 原始配置字典

    Returns:
        注入环境变量后的配置字典
    """
    for field_path, env_var in _ENV_FIELD_MAPPING.items():
        # 获取当前值
        current: Any = raw
        for key in field_path[:-1]:
            if not isinstance(current, dict):
                break
            current = current.get(key)
            if current is None:
                break

        if isinstance(current, dict):
            last_key = field_path[-1]
            current_value = current.get(last_key)
            # 如果值为空或不存在，尝试从环境变量注入
            if current_value is None or (isinstance(current_value, str) and current_value.strip() == ""):
                env_value = os.environ.get(env_var)
                if env_value:
                    current[last_key] = env_value

    return raw


def load_settings(path: str = "config/settings.yaml") -> Settings:
    """读取 YAML 配置文件并返回 :class:`Settings` 实例。

    Args:
        path: YAML 配置文件路径，默认为 ``config/settings.yaml``。

    Returns:
        解析后的 Settings 对象。

    Raises:
        SettingsError: 文件不存在、YAML 格式错误、或必填字段缺失时抛出。
    """
    config_path = Path(path)
    if not config_path.exists():
        raise SettingsError(f"Config file not found: {config_path}")

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            raw: Any = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        raise SettingsError(f"Failed to parse YAML: {exc}") from exc

    if not isinstance(raw, dict):
        raise SettingsError("Config file content is not a valid YAML mapping")

    # 解析配置中的环境变量引用 ${VAR_NAME}
    raw = _resolve_env_vars(raw)

    # 注入常用环境变量
    raw = _inject_env_vars(raw)

    # 构建子 settings（处理 ingestion 内嵌结构）
    ingestion_raw = raw.get("ingestion") or {}
    chunk_refiner_raw = ingestion_raw.get("chunk_refiner") or {}
    metadata_enricher_raw = ingestion_raw.get("metadata_enricher") or {}
    image_captioner_raw = ingestion_raw.get("image_captioner") or {}
    text_enricher_raw = ingestion_raw.get("text_enricher") or {}
    ingestion_settings = IngestionSettings(
        chunk_refiner=_build_sub_settings(
            chunk_refiner_raw, ChunkRefinerSettings, "ingestion.chunk_refiner"
        ),
        metadata_enricher=_build_sub_settings(
            metadata_enricher_raw, MetadataEnricherSettings, "ingestion.metadata_enricher"
        ),
        image_captioner=_build_sub_settings(
            image_captioner_raw, ImageCaptionerSettings, "ingestion.image_captioner"
        ),
        text_enricher=_build_sub_settings(
            text_enricher_raw, TextEnricherSettings, "ingestion.text_enricher"
        ),
    )

    # 构建 evaluation 嵌套结构 (Feature-001 引入 judge_llm / embedding /
    # acceptance_thresholds 三个子 dataclass,需手动构造,沿用 ingestion 模式)
    evaluation_raw = raw.get("evaluation") or {}
    # YAML 中可写 _schema_version,Python 字段名不能以 _ 开头,做一次映射
    if "_schema_version" in evaluation_raw and "schema_version" not in evaluation_raw:
        evaluation_raw["schema_version"] = evaluation_raw.pop("_schema_version")
    judge_llm_raw = evaluation_raw.get("judge_llm") or {}
    screening_llm_raw = evaluation_raw.get("screening_llm") or {}
    labeling_llm_raw = evaluation_raw.get("labeling_llm") or {}
    labeling_raw = evaluation_raw.get("labeling") or {}
    eval_embedding_raw = evaluation_raw.get("embedding") or {}
    acceptance_thresholds_raw = evaluation_raw.get("acceptance_thresholds") or {}
    # 顶层 EvaluationSettings 字段(去掉嵌套子段,后续显式注入)
    eval_top_raw = {
        k: v for k, v in evaluation_raw.items()
        if k not in {
            "judge_llm",
            "screening_llm",
            "labeling_llm",
            "labeling",
            "embedding",
            "acceptance_thresholds",
        }
    }
    evaluation_settings = EvaluationSettings(
        **{k: v for k, v in eval_top_raw.items() if v is not None}
    )
    evaluation_settings.judge_llm = _build_sub_settings(
        judge_llm_raw, JudgeLLMSettings, "evaluation.judge_llm"
    )
    evaluation_settings.screening_llm = _build_sub_settings(
        screening_llm_raw, ScreeningLLMSettings, "evaluation.screening_llm"
    )
    evaluation_settings.labeling_llm = _build_sub_settings(
        labeling_llm_raw, LabelingLLMSettings, "evaluation.labeling_llm"
    )
    evaluation_settings.labeling = _build_sub_settings(
        labeling_raw, LabelingSettings, "evaluation.labeling"
    )
    evaluation_settings.embedding = _build_sub_settings(
        eval_embedding_raw, EvaluationEmbeddingSettings, "evaluation.embedding"
    )
    evaluation_settings.acceptance_thresholds = _build_sub_settings(
        acceptance_thresholds_raw, AcceptanceThresholds, "evaluation.acceptance_thresholds"
    )

    settings = Settings(
        llm=_build_sub_settings(raw.get("llm"), LLMSettings, "llm"),
        embedding=_build_sub_settings(
            raw.get("embedding"), EmbeddingSettings, "embedding"
        ),
        vision_llm=_build_sub_settings(
            raw.get("vision_llm"), VisionLLMSettings, "vision_llm"
        ),
        vector_store=_build_sub_settings(
            raw.get("vector_store"), VectorStoreSettings, "vector_store"
        ),
        loader=_build_sub_settings(
            raw.get("loader"), LoaderSettings, "loader"
        ),
        retrieval=_build_sub_settings(
            raw.get("retrieval"), RetrievalSettings, "retrieval"
        ),
        query=_build_sub_settings(
            raw.get("query"), QuerySettings, "query"
        ),
        rerank=_build_sub_settings(
            raw.get("rerank"), RerankSettings, "rerank"
        ),
        splitter=_build_sub_settings(
            raw.get("splitter"), SplitterSettings, "splitter"
        ),
        ingestion=ingestion_settings,
        evaluation=evaluation_settings,
        observability=_build_sub_settings(
            raw.get("observability"), ObservabilitySettings, "observability"
        ),
        mcp_server=_build_sub_settings(
            raw.get("mcp_server"), MCPServerSettings, "mcp_server"
        ),
    )

    validate_settings(settings)
    return settings


def _validate_rerank_settings(rerank: RerankSettings) -> None:
    """校验重排配置(change activate-cross-encoder-rerank,宪法原则三:启动期快速失败)。

    这里每一条都刻意在启动期硬失败,而不是运行期兜底 —— 共同点是**违反后
    不会有任何报错**,用户以为重排在跑,实际拿到的是一次普通检索。这类静默
    失败最难排查:分数变化可以归因于任何环节,只有启动期报错能把问题钉在
    配置上。

    注意本函数**不探测后端依赖是否可用**(那需要 import 具体库,会把库名
    硬编码进 src/core/,违反宪法原则一 provider 无关性)。依赖探测由
    `RerankerFactory.probe_backend` 承担,在 load_settings 里单独调用。

    Args:
        rerank: 待校验的重排配置。

    Raises:
        SettingsError: 任一参数非法时。
    """
    backend = rerank.backend
    if backend not in VALID_RERANK_BACKENDS:
        raise SettingsError(
            f"Invalid rerank.backend: {backend!r}. "
            f"Expected one of: {sorted(VALID_RERANK_BACKENDS)}"
        )

    # backend != none 时 model 必填。刻意不留隐式默认值 —— 一个「配置留空就
    # 悄悄用纯英文模型」的兜底会让中文语料的重排完全无效且不报错。
    if backend != "none" and not rerank.model.strip():
        raise SettingsError(
            f"rerank.model is required when rerank.backend is {backend!r}, "
            "but it is empty. There is deliberately no implicit default: a "
            "silently-defaulted model can be wrong for your corpus (e.g. an "
            "English-only cross-encoder scores Chinese passages as noise "
            "without any error). Recommended for cross_encoder: "
            "'BAAI/bge-reranker-base' (bilingual zh/en, runs locally, no tokens)."
        )

    # top_m / batch_size:正整数。bool 要单独挡 —— isinstance(True, int) 为真,
    # 不挡的话 YAML 写成 `top_m: true` 会被当作 1 静默通过。
    for name, value in (("top_m", rerank.top_m), ("batch_size", rerank.batch_size)):
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise SettingsError(
                f"Invalid rerank.{name}: {value!r}. Expected a positive integer"
            )

    # timeout_sec:正数(允许小数)。<= 0 会让每次重排都立刻「超时」并退化为
    # 原序返回 —— 又一种不报错的静默失效。
    timeout = rerank.timeout_sec
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
        raise SettingsError(
            f"Invalid rerank.timeout_sec: {timeout!r}. Expected a positive number"
        )
    if timeout <= 0:
        raise SettingsError(
            f"Invalid rerank.timeout_sec: {timeout}. Expected a positive number "
            "(a non-positive timeout makes every rerank expire immediately and "
            "silently degrade to the original order)"
        )


def _probe_rerank_backend(rerank: RerankSettings) -> None:
    """探测重排后端的运行依赖是否可用(T-2.2,宪法原则三)。

    与 `_validate_rerank_settings` 分开是因为两者的知识边界不同:前者只看
    配置值本身,不需要知道任何 provider 细节;本函数要判断「这个后端的依赖
    装了没」,而那属于 provider 知识 —— 按宪法原则一,`src/core/` 不得 import
    具体 provider 实现,所以实际探测委托给 `RerankerFactory.probe_backend`,
    本函数只负责把它的 `ValueError` 转成本模块统一的 `SettingsError`。

    `backend: none` 时直接跳过 —— 默认配置不该因为一次 import 就把 factory
    及其下游(可能相当重的 torch 依赖链)拉进内存。

    Args:
        rerank: 已通过 `_validate_rerank_settings` 的重排配置。

    Raises:
        SettingsError: 后端依赖不可用时。消息里带可执行的安装命令。
    """
    if rerank.backend == "none":
        return

    # 局部 import:避免模块顶层依赖 libs 层,也避免 backend=none 时白白加载
    from src.libs.reranker.reranker_factory import RerankerFactory

    try:
        RerankerFactory.probe_backend(rerank.backend)
    except ValueError as e:
        # 转成本模块统一的异常类型,让调用方只需处理一种配置异常。
        # 这不是「吞掉异常后静默回退」—— 原因链用 from e 完整保留。
        raise SettingsError(f"Invalid rerank.backend: {e}") from e


def _validate_fusion_settings(retrieval: RetrievalSettings) -> None:
    """校验融合参数(spec feature-005 T002,宪法原则三:启动期快速失败)。

    这些校验刻意在启动期硬失败而非运行时静默兜底,理由见各分支注释 ——
    共同点是**违反后不会有任何报错**,只是检索效果悄悄变差或排序失去意义。

    Args:
        retrieval: 待校验的检索配置。

    Raises:
        SettingsError: 任一参数非法时。
    """
    # rrf_k:必须是正整数。bool 要单独挡掉 —— Python 里 isinstance(True, int)
    # 为真,不挡的话 YAML 写成 `rrf_k: true` 会被当作 k=1 静默通过。
    k = retrieval.rrf_k
    if not isinstance(k, int) or isinstance(k, bool) or k < 1:
        raise SettingsError(
            f"Invalid retrieval.rrf_k: {k!r}. Expected a positive integer "
            "(k=0 makes rank-1 dominate all other results combined, "
            "losing the smoothing that RRF exists for)"
        )

    weights = retrieval.fusion_weights
    if not isinstance(weights, dict):
        raise SettingsError(
            f"Invalid retrieval.fusion_weights: {weights!r}. Expected a mapping "
            "of route name to non-negative number"
        )

    for route, weight in weights.items():
        if isinstance(weight, bool) or not isinstance(weight, (int, float)):
            raise SettingsError(
                f"Invalid retrieval.fusion_weights['{route}']: {weight!r}. "
                "Expected a non-negative number"
            )
        if weight < 0:
            raise SettingsError(
                f"Invalid retrieval.fusion_weights['{route}']: {weight}. "
                "Weights must be non-negative"
            )

    # 全零权重必须拒绝:所有融合得分归零后,排序完全由字典遍历顺序决定,
    # 检索结果实际上变成随机的 —— 而这不会抛任何异常、不会有任何日志。
    # 单条路径为 0 是合法的(等价于关闭该路)。
    if weights and not any(float(w) > 0 for w in weights.values()):
        raise SettingsError(
            "Invalid retrieval.fusion_weights: all weights are zero. "
            "Every fused score would collapse to 0 and ordering would become "
            "arbitrary, with no error raised at runtime. "
            "Set at least one route to a positive weight"
        )


def validate_settings(settings: Settings) -> None:
    """校验 Settings 中的必填字段。

    Args:
        settings: 待校验的 Settings 实例。

    Raises:
        SettingsError: 某个必填字段为空或缺失时抛出，错误信息包含字段路径。
    """
    for field_path in _REQUIRED_FIELDS:
        # 沿 dataclass 属性链取值
        obj: Any = settings
        for attr in field_path:
            obj = getattr(obj, attr, None)
            if obj is None:
                break

        dotted = ".".join(field_path)
        if obj is None or (isinstance(obj, str) and obj.strip() == ""):
            raise SettingsError(
                f"Required config field is missing or empty: '{dotted}'"
            )

    transport = settings.mcp_server.transport
    if transport not in VALID_TRANSPORTS:
        raise SettingsError(
            f"Invalid mcp_server.transport: {transport!r}. "
            f"Expected one of: {sorted(VALID_TRANSPORTS)}"
        )

    if not (1 <= settings.mcp_server.port <= 65535):
        raise SettingsError(
            "Invalid mcp_server.port: "
            f"{settings.mcp_server.port}. Expected 1-65535"
        )

    # 融合参数校验（spec feature-005 T002）
    _validate_fusion_settings(settings.retrieval)

    # 关键词索引格式版本校验（spec feature-004 T001）
    # 该值决定 BM25Indexer.load() 接受哪一版磁盘格式。配成非正整数会让
    # 版本校验失去意义，因此在启动期就拒绝，而不是等到加载索引时才发现。
    fmt_version = settings.vector_store.bm25_index_format_version
    if not isinstance(fmt_version, int) or isinstance(fmt_version, bool) or fmt_version < 1:
        raise SettingsError(
            "Invalid vector_store.bm25_index_format_version: "
            f"{fmt_version!r}. Expected a positive integer"
        )

    # 重排配置校验（change activate-cross-encoder-rerank T-2.1 / T-2.2）
    _validate_rerank_settings(settings.rerank)
    _probe_rerank_backend(settings.rerank)

    # 查询响应配置校验（spec feature-002 FR-004）
    if settings.query.max_images_per_response <= 0:
        raise SettingsError(
            "Invalid query.max_images_per_response: "
            f"{settings.query.max_images_per_response}. Expected a positive integer (> 0)."
        )

    # Feature-001 评估配置校验
    _validate_evaluation_settings(settings)

    # 金标标注配置校验（change retriever-agnostic-golden-labels T-1.1）
    _validate_labeling_settings(settings.evaluation.labeling)


# ---------------------------------------------------------------------------
# Feature-001: evaluation 段启动期校验 (宪法 § III 快速失败)
# ---------------------------------------------------------------------------

# LLMFactory / EmbeddingFactory 注册的 provider 白名单
# 与 src/libs/llm/llm_factory.py + src/libs/embedding/embedding_factory.py 保持一致;
# 后续若新增 provider,需同步更新本白名单
_VALID_LLM_PROVIDERS: frozenset[str] = frozenset(
    {"glm", "azure", "openai", "ollama", "deepseek"}
)
_VALID_EMBEDDING_PROVIDERS: frozenset[str] = frozenset(
    {"bge", "openai", "azure", "ollama", "glm"}
)
# evaluation.backends 白名单
_VALID_EVAL_BACKENDS: frozenset[str] = frozenset({"custom", "ragas"})
# evaluation.by_tag_dimensions 白名单 (MVP 仅支持 content_type / difficulty)
_VALID_BY_TAG_DIMENSIONS: frozenset[str] = frozenset({"content_type", "difficulty"})
# acceptance_thresholds 必含的 8 个 metric key
_REQUIRED_THRESHOLD_KEYS: frozenset[str] = frozenset({
    "ragas__context_recall",
    "ragas__context_precision",
    "ragas__faithfulness",
    "ragas__answer_relevancy",
    "custom__hit_rate",
    "custom__mrr",
    "custom__recall",
    "custom__ndcg",
})


def _validate_labeling_settings(labeling: LabelingSettings) -> None:
    """校验金标标注配置(change retriever-agnostic-golden-labels,宪法原则三)。

    最重要的一条是**至少两路池化**:如果只有一路 > 0,候选池就完全由那一路
    决定,那条路径永远「全对」,其他路径找到的正确结果连进入标准答案的机会都
    没有 —— 这正是第一代纯 dense top-5 回填造成的偏差,本变更的全部意义就在
    于消除它。只配一路等于把新方法退化成旧方法,**而且不会有任何报错**。

    Args:
        labeling: 待校验的标注配置。

    Raises:
        SettingsError: 任一参数非法时。
    """
    pool_fields = (
        ("pool_top_n_dense", labeling.pool_top_n_dense),
        ("pool_top_n_sparse", labeling.pool_top_n_sparse),
        ("pool_top_n_rerank", labeling.pool_top_n_rerank),
    )
    # bool 要单独挡 —— isinstance(True, int) 为真,YAML 写 `pool_top_n_dense: true`
    # 会被当作 1 静默通过(池子只有 1 条候选)。
    for name, value in pool_fields:
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise SettingsError(
                f"Invalid evaluation.labeling.{name}: {value!r}. "
                "Expected a non-negative integer (0 disables that route)"
            )

    enabled_routes = [name for name, value in pool_fields if value > 0]
    if len(enabled_routes) < 2:
        raise SettingsError(
            "evaluation.labeling requires at least TWO retrieval routes with "
            f"pool_top_n_* > 0, but only {len(enabled_routes)} enabled "
            f"({enabled_routes or 'none'}). A single-route pool lets that route "
            "monopolise the ground truth — it would always score perfectly while "
            "other routes never get a chance to contribute, which is exactly the "
            "dense-anchored bias this change exists to remove. Single-route "
            "pooling degrades the new method back to the old one, silently."
        )

    threshold = labeling.relevance_threshold
    if not isinstance(threshold, int) or isinstance(threshold, bool) or threshold not in (1, 2, 3):
        raise SettingsError(
            f"Invalid evaluation.labeling.relevance_threshold: {threshold!r}. "
            "Expected 1, 2 or 3 (grades: 0 irrelevant / 1 tangential / "
            "2 partially supports / 3 directly answers). 0 would accept every "
            "candidate in the pool as ground truth"
        )

    max_judgements = labeling.max_judgements
    if (
        not isinstance(max_judgements, int)
        or isinstance(max_judgements, bool)
        or max_judgements < 1
    ):
        raise SettingsError(
            f"Invalid evaluation.labeling.max_judgements: {max_judgements!r}. "
            "Expected a positive integer"
        )

    ratio_fields = (
        ("judge_failure_warn_ratio", labeling.judge_failure_warn_ratio),
        ("dense_overlap_warn", labeling.dense_overlap_warn),
        ("human_agreement_warn", labeling.human_agreement_warn),
    )
    for name, value in ratio_fields:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise SettingsError(
                f"Invalid evaluation.labeling.{name}: {value!r}. "
                "Expected a number in [0.0, 1.0]"
            )
        if not (0.0 <= value <= 1.0):
            raise SettingsError(
                f"Invalid evaluation.labeling.{name}: {value}. "
                "Expected a ratio in [0.0, 1.0]"
            )


def _validate_evaluation_settings(settings: Settings) -> None:
    """Feature-001 评估配置启动期校验。

    实现见 specs/001-rag-acceptance/contracts/settings.evaluation.schema.md
    § Field Validation Rules 中列出的全部规则。任一规则失败立即抛
    ``SettingsError``(宪法 § III 快速失败原则)。

    Args:
        settings: 已加载但未校验的 Settings 实例。

    Raises:
        SettingsError: 任一校验规则失败。
    """
    eval_s = settings.evaluation

    # _schema_version >= 1
    if eval_s.schema_version < 1:
        raise SettingsError(
            f"evaluation._schema_version={eval_s.schema_version} invalid (>= 1 required)"
        )

    # backends 元素白名单
    invalid_backends = [b for b in eval_s.backends if b not in _VALID_EVAL_BACKENDS]
    if invalid_backends:
        raise SettingsError(
            f"evaluation.backends contains unknown backend: {invalid_backends!r}. "
            f"Valid options: {sorted(_VALID_EVAL_BACKENDS)}"
        )

    # ragas 启用时 judge_llm.provider / model 必填
    if "ragas" in eval_s.backends:
        if not eval_s.judge_llm.provider.strip():
            raise SettingsError(
                "evaluation.backends contains 'ragas' but evaluation.judge_llm.provider "
                "is empty. Configure judge_llm or remove 'ragas' from backends."
            )
        if not eval_s.judge_llm.model.strip():
            raise SettingsError(
                "evaluation.judge_llm.model cannot be empty when 'ragas' is enabled."
            )

    # judge_llm.provider 在 LLMFactory 注册列表
    if eval_s.judge_llm.provider and eval_s.judge_llm.provider not in _VALID_LLM_PROVIDERS:
        raise SettingsError(
            f"evaluation.judge_llm.provider={eval_s.judge_llm.provider!r} not in "
            f"LLMFactory registry. Valid options: {sorted(_VALID_LLM_PROVIDERS)}"
        )

    # judge_llm.temperature ∈ [0, 2]
    if not 0.0 <= eval_s.judge_llm.temperature <= 2.0:
        raise SettingsError(
            f"evaluation.judge_llm.temperature={eval_s.judge_llm.temperature} "
            "out of range [0, 2]"
        )

    # judge_llm.request_timeout_sec > 0
    if eval_s.judge_llm.request_timeout_sec <= 0:
        raise SettingsError(
            f"evaluation.judge_llm.request_timeout_sec={eval_s.judge_llm.request_timeout_sec} "
            "must be > 0"
        )

    # --- screening_llm (Feature-003) -------------------------------------
    # 注意:这里**不**校验 provider/model 非空。默认交互模式不需要预筛模型,
    # 若在加载期强制要求,所有未配置本节的既有用法都会启动失败(违反 FR-004)。
    # 非空校验推迟到 refine_testset.py 的 --auto-mode 入口。
    # 这与上方 judge_llm「仅 ragas 启用时才要求非空」是同一处理原则。
    screening = eval_s.screening_llm

    # provider 非空时须在 LLMFactory 注册列表内
    if screening.provider and screening.provider not in _VALID_LLM_PROVIDERS:
        raise SettingsError(
            f"evaluation.screening_llm.provider={screening.provider!r} not in "
            f"LLMFactory registry. Valid options: {sorted(_VALID_LLM_PROVIDERS)}"
        )

    # temperature ∈ [0, 2]
    if not 0.0 <= screening.temperature <= 2.0:
        raise SettingsError(
            f"evaluation.screening_llm.temperature={screening.temperature} "
            "must be within [0.0, 2.0]"
        )

    # request_timeout_sec > 0
    if screening.request_timeout_sec <= 0:
        raise SettingsError(
            f"evaluation.screening_llm.request_timeout_sec={screening.request_timeout_sec} "
            "must be > 0"
        )

    # 5 个比例/阈值字段 ∈ (0.0, 1.0]
    for _field_name in (
        "keep_threshold",
        "drop_threshold",
        "borderline_ratio_warn",
        "sample_ratio",
        "compliance_gate",
    ):
        _value = getattr(screening, _field_name)
        if not 0.0 < _value <= 1.0:
            raise SettingsError(
                f"evaluation.screening_llm.{_field_name}={_value} "
                "must be within (0.0, 1.0]"
            )

    # embedding.provider 在 EmbeddingFactory 注册列表 (空表示复用顶层)
    if eval_s.embedding.provider and eval_s.embedding.provider not in _VALID_EMBEDDING_PROVIDERS:
        raise SettingsError(
            f"evaluation.embedding.provider={eval_s.embedding.provider!r} not in "
            f"EmbeddingFactory registry. Valid options: {sorted(_VALID_EMBEDDING_PROVIDERS)}"
        )

    # acceptance_thresholds 每项 ∈ [0, 1]
    thresholds_dict = eval_s.acceptance_thresholds.to_dict()
    # 校验完整性 (dataclass 默认值保证存在,但若用户用 ** 解包传部分字段会触发)
    missing = _REQUIRED_THRESHOLD_KEYS - set(thresholds_dict.keys())
    if missing:
        raise SettingsError(
            f"evaluation.acceptance_thresholds missing keys: {sorted(missing)}"
        )
    # 校验取值范围
    for key, value in thresholds_dict.items():
        if not isinstance(value, (int, float)):
            raise SettingsError(
                f"evaluation.acceptance_thresholds.{key} must be a number, "
                f"got {type(value).__name__}"
            )
        if not 0.0 <= float(value) <= 1.0:
            raise SettingsError(
                f"evaluation.acceptance_thresholds.{key}={value} out of range [0, 1]"
            )

    # by_tag_dimensions 必须 ⊆ 白名单
    invalid_dims = [d for d in eval_s.by_tag_dimensions if d not in _VALID_BY_TAG_DIMENSIONS]
    if invalid_dims:
        raise SettingsError(
            f"evaluation.by_tag_dimensions contains unknown dimension: {invalid_dims!r}. "
            f"Valid options: {sorted(_VALID_BY_TAG_DIMENSIONS)}"
        )

    # tag_slice_min_samples >= 1
    if eval_s.tag_slice_min_samples < 1:
        raise SettingsError(
            f"evaluation.tag_slice_min_samples={eval_s.tag_slice_min_samples} must be >= 1"
        )

    # report_archive_dir 父目录可写
    archive_parent = Path(eval_s.report_archive_dir).parent
    _ensure_writable_parent(archive_parent, "evaluation.report_archive_dir")

    # baseline_store_path 父目录可写
    baseline_parent = Path(eval_s.baseline_store_path).parent
    _ensure_writable_parent(baseline_parent, "evaluation.baseline_store_path")

    # chunk_id_validation 必须是 bool
    if not isinstance(eval_s.chunk_id_validation, bool):
        raise SettingsError(
            f"evaluation.chunk_id_validation must be bool, "
            f"got {type(eval_s.chunk_id_validation).__name__}"
        )


def _ensure_writable_parent(parent: Path, field_path: str) -> None:
    """确认 parent 目录存在且可写;不存在时尝试创建一次。

    Args:
        parent: 待检查的父目录 Path。
        field_path: 用于错误消息的配置字段路径(如 "evaluation.report_archive_dir")。

    Raises:
        SettingsError: 父目录不可写或无法创建。
    """
    if not parent.exists():
        try:
            parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise SettingsError(
                f"{field_path} parent not writable: {parent} ({exc})"
            ) from exc
    elif not os.access(str(parent), os.W_OK):
        raise SettingsError(f"{field_path} parent not writable: {parent}")
