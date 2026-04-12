"""Dashboard 端到端冒烟测试。

验证 Dashboard 六个页面脚本都能加载并执行到首轮渲染，无未捕获异常。
"""

from __future__ import annotations

from pathlib import Path

import pytest

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest


def _assert_streamlit_page_runs(page_path: Path) -> None:
    """运行单个 Streamlit 页面并断言没有未捕获异常。"""
    app = AppTest.from_file(str(page_path))
    app.run(timeout=15)
    assert not app.exception, f"Page failed: {page_path.name}"


@pytest.mark.e2e
def test_dashboard_pages_can_render_without_unhandled_exception() -> None:
    """验证 Dashboard 六个页面可正常渲染。"""
    project_root = Path(__file__).resolve().parents[2]
    pages_dir = project_root / "src" / "observability" / "dashboard" / "pages"

    page_files = [
        pages_dir / "overview.py",
        pages_dir / "data_browser.py",
        pages_dir / "ingestion_manager.py",
        pages_dir / "ingestion_traces.py",
        pages_dir / "query_traces.py",
        pages_dir / "evaluation_panel.py",
    ]

    for page_file in page_files:
        assert page_file.exists(), f"Missing dashboard page file: {page_file}"
        _assert_streamlit_page_runs(page_file)
