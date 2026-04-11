"""Smoke tests: verify all top-level packages are importable.

This is the first test in the project (A2). It ensures the directory
skeleton created in A1 can be imported without errors.
"""

import pytest


@pytest.mark.unit
class TestSmokeImports:
    """Verify every top-level source package can be imported."""

    def test_import_mcp_server(self) -> None:
        """MCP Server 层可导入。"""
        import mcp_server  # noqa: F401
        import mcp_server.server  # noqa: F401
        import mcp_server.protocol_handler  # noqa: F401
        import mcp_server.tools  # noqa: F401

    def test_import_core(self) -> None:
        """Core 层可导入。"""
        import core  # noqa: F401
        import core.settings  # noqa: F401
        import core.types  # noqa: F401
        import core.query_engine  # noqa: F401
        import core.response  # noqa: F401
        import core.trace  # noqa: F401

    def test_import_ingestion(self) -> None:
        """Ingestion Pipeline 层可导入。"""
        import ingestion  # noqa: F401
        import ingestion.pipeline  # noqa: F401
        import ingestion.chunking  # noqa: F401
        import ingestion.transform  # noqa: F401
        import ingestion.embedding  # noqa: F401
        import ingestion.storage  # noqa: F401

    def test_import_libs(self) -> None:
        """Libs 可插拔层可导入。"""
        import libs  # noqa: F401
        import libs.llm  # noqa: F401
        import libs.embedding  # noqa: F401
        import libs.splitter  # noqa: F401
        import libs.vector_store  # noqa: F401
        import libs.reranker  # noqa: F401
        import libs.evaluator  # noqa: F401
        import libs.loader  # noqa: F401

    def test_import_observability(self) -> None:
        """Observability 层可导入。"""
        import src.observability.logger  # noqa: F401
        import src.observability.dashboard  # noqa: F401
        import src.observability.dashboard.services  # noqa: F401
        import src.observability.dashboard.pages  # noqa: F401
        import src.observability.evaluation  # noqa: F401
