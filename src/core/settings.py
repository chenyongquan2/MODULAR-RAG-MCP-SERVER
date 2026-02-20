"""配置加载与校验 (Settings)。

读取 config/settings.yaml，解析为 Settings 数据结构，并在启动时校验关键字段存在。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


# ---------------------------------------------------------------------------
# Settings 数据结构
# ---------------------------------------------------------------------------


@dataclass
class LLMSettings:
    """LLM 配置。"""

    provider: str  # azure | openai | ollama | deepseek
    model: str
    azure_endpoint: str = ""
    api_key: str = ""


@dataclass
class EmbeddingSettings:
    """Embedding 配置。"""

    provider: str  # openai | azure | ollama
    model: str


@dataclass
class VisionLLMSettings:
    """Vision LLM 配置。"""

    provider: str  # azure
    model: str


@dataclass
class VectorStoreSettings:
    """向量存储配置。"""

    backend: str  # chroma
    persist_path: str = "./data/db/chroma"


@dataclass
class RetrievalSettings:
    """检索配置。"""

    sparse_backend: str = "bm25"
    fusion_algorithm: str = "rrf"
    top_k_dense: int = 20
    top_k_sparse: int = 20
    top_k_final: int = 10


@dataclass
class RerankSettings:
    """重排配置。"""

    backend: str = "none"
    model: str = ""
    top_m: int = 30


@dataclass
class SplitterSettings:
    """文本切分配置。"""

    strategy: str = "recursive"
    chunk_size: int = 1000
    chunk_overlap: int = 200


@dataclass
class ChunkRefinerSettings:
    """Chunk 精炼配置。"""

    use_llm: bool = False


@dataclass
class IngestionSettings:
    """摄取管道配置。"""

    chunk_refiner: ChunkRefinerSettings = field(
        default_factory=ChunkRefinerSettings
    )


@dataclass
class EvaluationSettings:
    """评估配置。"""

    backends: list[str] = field(default_factory=lambda: ["custom"])
    golden_test_set: str = "./tests/fixtures/golden_test_set.json"


@dataclass
class ObservabilitySettings:
    """可观测性配置。"""

    enabled: bool = True
    log_file: str = "./logs/traces.jsonl"


@dataclass
class Settings:
    """全局配置，对应 config/settings.yaml 的完整结构。"""

    llm: LLMSettings
    embedding: EmbeddingSettings
    vision_llm: VisionLLMSettings
    vector_store: VectorStoreSettings
    retrieval: RetrievalSettings = field(default_factory=RetrievalSettings)
    rerank: RerankSettings = field(default_factory=RerankSettings)
    splitter: SplitterSettings = field(default_factory=SplitterSettings)
    ingestion: IngestionSettings = field(default_factory=IngestionSettings)
    evaluation: EvaluationSettings = field(default_factory=EvaluationSettings)
    observability: ObservabilitySettings = field(
        default_factory=ObservabilitySettings
    )


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
                f"配置缺失必填 section: '{section_name}'"
            )
    try:
        return cls(**{k: v for k, v in raw.items() if v is not None})
    except TypeError as exc:
        raise SettingsError(
            f"配置 section '{section_name}' 字段不完整: {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# 公共 API
# ---------------------------------------------------------------------------


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
        raise SettingsError(f"配置文件不存在: {config_path}")

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            raw: Any = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        raise SettingsError(f"YAML 解析失败: {exc}") from exc

    if not isinstance(raw, dict):
        raise SettingsError("配置文件内容不是合法的 YAML 映射")

    # 环境变量覆盖 api_key（优先级：环境变量 > yaml）
    llm_raw: dict[str, Any] = raw.get("llm") or {}
    if not llm_raw.get("api_key") and os.environ.get("LLM_API_KEY"):
        llm_raw["api_key"] = os.environ["LLM_API_KEY"]

    # 构建子 settings（处理 ingestion 内嵌结构）
    ingestion_raw = raw.get("ingestion") or {}
    chunk_refiner_raw = ingestion_raw.get("chunk_refiner") or {}
    ingestion_settings = IngestionSettings(
        chunk_refiner=_build_sub_settings(
            chunk_refiner_raw, ChunkRefinerSettings, "ingestion.chunk_refiner"
        ),
    )

    settings = Settings(
        llm=_build_sub_settings(llm_raw, LLMSettings, "llm"),
        embedding=_build_sub_settings(
            raw.get("embedding"), EmbeddingSettings, "embedding"
        ),
        vision_llm=_build_sub_settings(
            raw.get("vision_llm"), VisionLLMSettings, "vision_llm"
        ),
        vector_store=_build_sub_settings(
            raw.get("vector_store"), VectorStoreSettings, "vector_store"
        ),
        retrieval=_build_sub_settings(
            raw.get("retrieval"), RetrievalSettings, "retrieval"
        ),
        rerank=_build_sub_settings(
            raw.get("rerank"), RerankSettings, "rerank"
        ),
        splitter=_build_sub_settings(
            raw.get("splitter"), SplitterSettings, "splitter"
        ),
        ingestion=ingestion_settings,
        evaluation=_build_sub_settings(
            raw.get("evaluation"), EvaluationSettings, "evaluation"
        ),
        observability=_build_sub_settings(
            raw.get("observability"), ObservabilitySettings, "observability"
        ),
    )

    validate_settings(settings)
    return settings


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
                f"必填配置字段缺失或为空: '{dotted}'"
            )
