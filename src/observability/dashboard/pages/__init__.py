"""Dashboard 页面包。

避免模块导入时立刻触发 streamlit 依赖，改为按需懒加载。
"""

from __future__ import annotations

from importlib import import_module

__all__ = [
    "overview",
    "data_browser",
    "ingestion_manager",
    "query_traces",
    "ingestion_traces",
    "evaluation_panel",
]


def __getattr__(name: str):
    if name in __all__:
        return import_module(f"src.observability.dashboard.pages.{name}")
    raise AttributeError(f"module {__name__} has no attribute {name}")
