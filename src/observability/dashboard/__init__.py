"""Dashboard 包。

为避免在仅导入 service 层时强依赖 streamlit，
这里对 app 入口采用延迟导入。
"""


def render_main_app() -> None:
    """渲染 Dashboard 主应用（延迟导入 streamlit 相关模块）。"""
    from src.observability.dashboard.app import render_main_app as _render_main_app

    _render_main_app()


__all__ = ["render_main_app"]
