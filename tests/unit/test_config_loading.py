"""A3: 配置加载与校验 — 单元测试。

验收标准：
- load_settings 能成功加载 config/settings.yaml 并返回 Settings 对象。
- 缺失关键字段时抛出 SettingsError，错误信息包含字段路径。
- 非法 YAML / 文件不存在 时报错。
- 环境变量可覆盖 api_key。
"""

from __future__ import annotations

import os
import textwrap
from pathlib import Path

import pytest

from core.settings import (
    Settings,
    SettingsError,
    load_settings,
    validate_settings,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

MINIMAL_YAML = textwrap.dedent("""\
    llm:
      provider: openai
      model: gpt-4o
    embedding:
      provider: openai
      model: text-embedding-3-small
    vision_llm:
      provider: azure
      model: gpt-4o
    vector_store:
      backend: chroma
""")


@pytest.fixture()
def yaml_file(tmp_path: Path) -> Path:
    """在临时目录写入最小合法 YAML 并返回路径。"""
    p = tmp_path / "settings.yaml"
    p.write_text(MINIMAL_YAML, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# 正常加载
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestLoadSettings:
    """正常加载场景。"""

    def test_load_default_settings(self) -> None:
        """加载项目根目录的 config/settings.yaml 应成功。"""
        settings = load_settings("config/settings.yaml")
        assert isinstance(settings, Settings)

    def test_load_minimal_yaml(self, yaml_file: Path) -> None:
        """加载最小合法 YAML 应返回 Settings。"""
        settings = load_settings(str(yaml_file))
        assert isinstance(settings, Settings)

    def test_settings_fields_accessible(self, yaml_file: Path) -> None:
        """Settings 各字段应可正常访问。"""
        settings = load_settings(str(yaml_file))
        assert settings.llm.provider == "openai"
        assert settings.llm.model == "gpt-4o"
        assert settings.embedding.provider == "openai"
        assert settings.embedding.model == "text-embedding-3-small"
        assert settings.vector_store.backend == "chroma"

    def test_default_retrieval_values(self, yaml_file: Path) -> None:
        """未在 YAML 中指定的 retrieval section 应使用默认值。"""
        settings = load_settings(str(yaml_file))
        assert settings.retrieval.top_k_dense == 20
        assert settings.retrieval.top_k_final == 10
        assert settings.retrieval.fusion_algorithm == "rrf"

    def test_default_splitter_values(self, yaml_file: Path) -> None:
        """未在 YAML 中指定的 splitter section 应使用默认值。"""
        settings = load_settings(str(yaml_file))
        assert settings.splitter.strategy == "recursive"
        assert settings.splitter.chunk_size == 1000
        assert settings.splitter.chunk_overlap == 200

    def test_default_ingestion_values(self, yaml_file: Path) -> None:
        """未在 YAML 中指定的 ingestion section 应使用默认值。"""
        settings = load_settings(str(yaml_file))
        assert settings.ingestion.chunk_refiner.use_llm is False

    def test_default_mcp_server_values(self, yaml_file: Path) -> None:
        """未在 YAML 中指定的 mcp_server section 应使用默认值。"""
        settings = load_settings(str(yaml_file))
        assert settings.mcp_server.transport == "stdio"
        assert settings.mcp_server.host == "127.0.0.1"
        assert settings.mcp_server.port == 8000
        assert settings.mcp_server.sse_path == "/sse"
        assert settings.mcp_server.message_path == "/messages/"

    def test_custom_mcp_server_values(self, tmp_path: Path) -> None:
        """mcp_server section 指定值应被正确加载。"""
        yaml_text = MINIMAL_YAML + textwrap.dedent("""\

            mcp_server:
              transport: sse
              host: 0.0.0.0
              port: 18080
              sse_path: /stream
              message_path: /ingress/
        """)
        p = tmp_path / "settings.yaml"
        p.write_text(yaml_text, encoding="utf-8")

        settings = load_settings(str(p))
        assert settings.mcp_server.transport == "sse"
        assert settings.mcp_server.host == "0.0.0.0"
        assert settings.mcp_server.port == 18080
        assert settings.mcp_server.sse_path == "/stream"
        assert settings.mcp_server.message_path == "/ingress/"


# ---------------------------------------------------------------------------
# 校验失败
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestValidation:
    """校验异常场景。"""

    def test_missing_llm_provider_raises(self, tmp_path: Path) -> None:
        """缺少 llm.provider 时应报错，错误信息包含字段路径。"""
        bad_yaml = MINIMAL_YAML.replace("provider: openai", "provider: ", 1)
        p = tmp_path / "bad.yaml"
        p.write_text(bad_yaml, encoding="utf-8")

        with pytest.raises(SettingsError, match="llm"):
            load_settings(str(p))

    def test_missing_embedding_provider_raises(self, tmp_path: Path) -> None:
        """缺少 embedding.provider 时应报错。"""
        yaml_text = textwrap.dedent("""\
            llm:
              provider: openai
              model: gpt-4o
            embedding:
              provider: ""
              model: text-embedding-3-small
            vision_llm:
              provider: azure
              model: gpt-4o
            vector_store:
              backend: chroma
        """)
        p = tmp_path / "bad.yaml"
        p.write_text(yaml_text, encoding="utf-8")

        with pytest.raises(SettingsError, match="embedding.provider"):
            load_settings(str(p))

    def test_missing_vector_store_backend_raises(
        self, tmp_path: Path
    ) -> None:
        """缺少 vector_store.backend 时应报错。"""
        yaml_text = textwrap.dedent("""\
            llm:
              provider: openai
              model: gpt-4o
            embedding:
              provider: openai
              model: text-embedding-3-small
            vision_llm:
              provider: azure
              model: gpt-4o
            vector_store:
              backend: ""
        """)
        p = tmp_path / "bad.yaml"
        p.write_text(yaml_text, encoding="utf-8")

        with pytest.raises(SettingsError, match="vector_store.backend"):
            load_settings(str(p))

    def test_missing_embedding_section_raises(self, tmp_path: Path) -> None:
        """整个 embedding section 缺失时应报错。"""
        yaml_text = textwrap.dedent("""\
            llm:
              provider: openai
              model: gpt-4o
            vision_llm:
              provider: azure
              model: gpt-4o
            vector_store:
              backend: chroma
        """)
        p = tmp_path / "bad.yaml"
        p.write_text(yaml_text, encoding="utf-8")

        with pytest.raises(SettingsError, match="embedding"):
            load_settings(str(p))

    def test_invalid_mcp_transport_raises(self, tmp_path: Path) -> None:
        """mcp_server.transport 非法值应报错。"""
        yaml_text = MINIMAL_YAML + textwrap.dedent("""\

            mcp_server:
              transport: websocket
        """)
        p = tmp_path / "bad.yaml"
        p.write_text(yaml_text, encoding="utf-8")

        with pytest.raises(SettingsError, match="mcp_server.transport"):
            load_settings(str(p))

    def test_invalid_mcp_port_raises(self, tmp_path: Path) -> None:
        """mcp_server.port 超出范围应报错。"""
        yaml_text = MINIMAL_YAML + textwrap.dedent("""\

            mcp_server:
              transport: sse
              port: 70000
        """)
        p = tmp_path / "bad_port.yaml"
        p.write_text(yaml_text, encoding="utf-8")

        with pytest.raises(SettingsError, match="mcp_server.port"):
            load_settings(str(p))


# ---------------------------------------------------------------------------
# 文件/格式错误
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFileErrors:
    """文件不存在或格式错误。"""

    def test_missing_yaml_file_raises(self) -> None:
        """不存在的配置文件应报错。"""
        with pytest.raises(SettingsError, match="not found"):
            load_settings("/nonexistent/path/settings.yaml")

    def test_invalid_yaml_raises(self, tmp_path: Path) -> None:
        """非法 YAML 内容应报错。"""
        p = tmp_path / "bad.yaml"
        p.write_text("{{{{invalid yaml: [[[", encoding="utf-8")

        with pytest.raises(SettingsError, match="YAML"):
            load_settings(str(p))

    def test_non_dict_yaml_raises(self, tmp_path: Path) -> None:
        """YAML 内容不是 dict 时应报错。"""
        p = tmp_path / "list.yaml"
        p.write_text("- item1\n- item2\n", encoding="utf-8")

        with pytest.raises(SettingsError, match="not a valid YAML mapping"):
            load_settings(str(p))


# ---------------------------------------------------------------------------
# 环境变量覆盖
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEnvOverride:
    """环境变量覆盖。"""

    def test_env_override_api_key(
        self, yaml_file: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """LLM_API_KEY 环境变量应覆盖 yaml 中空的 api_key。"""
        monkeypatch.setenv("LLM_API_KEY", "sk-test-from-env")
        settings = load_settings(str(yaml_file))
        assert settings.llm.api_key == "sk-test-from-env"

    def test_yaml_api_key_takes_precedence(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """yaml 中已有 api_key 时，环境变量不应覆盖。"""
        yaml_text = textwrap.dedent("""\
            llm:
              provider: openai
              model: gpt-4o
              api_key: sk-from-yaml
            embedding:
              provider: openai
              model: text-embedding-3-small
            vision_llm:
              provider: azure
              model: gpt-4o
            vector_store:
              backend: chroma
        """)
        p = tmp_path / "settings.yaml"
        p.write_text(yaml_text, encoding="utf-8")
        monkeypatch.setenv("LLM_API_KEY", "sk-from-env")

        settings = load_settings(str(p))
        assert settings.llm.api_key == "sk-from-yaml"
