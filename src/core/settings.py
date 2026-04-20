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
from typing import Any, Literal

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
    """LLM 配置。"""

    provider: str  # azure | openai | ollama | deepseek | glm
    model: str
    azure_endpoint: str = ""
    api_key: str = ""
    base_url: str = ""


@dataclass
class EmbeddingSettings:
    """Embedding 配置。"""

    provider: str  # openai | azure | ollama | glm | bge
    model: str
    api_key: str = ""
    base_url: str = ""


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
    collection_name: str = "default"  # 集合名称，默认 "default"


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
class EvaluationSettings:
    """评估配置。"""

    backends: list[str] = field(default_factory=lambda: ["custom"])
    golden_test_set: str = "./tests/fixtures/golden_test_set.json"


@dataclass
class ObservabilitySettings:
    """可观测性配置。"""

    enabled: bool = True
    log_file: str = "./logs/traces.jsonl"


# 允许的 transport 类型，集中定义以避免各处字符串字面量散落
TransportType = Literal["stdio", "sse"]
VALID_TRANSPORTS: frozenset[str] = frozenset({"stdio", "sse"})


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
        mcp_server=_build_sub_settings(
            raw.get("mcp_server"), MCPServerSettings, "mcp_server"
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
