"""系统总览页面。

提供系统配置和数据统计的概览视图，包括：
- 组件配置展示（LLM、Embedding、Splitter、Reranker 等）
- 向量存储统计（集合数量、向量总数）
- 系统状态概览

Design Principles Applied:
- Config-Driven: 所有展示信息从配置读取
- Observable: 清晰展示系统当前状态
"""

from __future__ import annotations

from typing import Any, Dict

import streamlit as st

from src.core.settings import load_settings
from src.observability.dashboard.services import ConfigService, VectorStoreService


def render_component_card(config: Dict[str, Any]) -> None:
    """渲染组件配置卡片。

    Args:
        config: 组件配置字典，包含 name, provider, model, details。
    """
    with st.container(border=True):
        # 组件名称（标题）
        st.markdown(f"### {config['name']}")

        # Provider 和 Model
        col1, col2 = st.columns(2)
        with col1:
            st.metric("Provider", config["provider"])
        with col2:
            st.metric("Model", config["model"])

        # 详细信息（可选）
        if config["details"]:
            with st.expander("查看详情"):
                for key, value in config["details"].items():
                    # 对于敏感信息（如 API key），只显示是否存在
                    if key.endswith("_key"):
                        st.write(f"**{key}**: {'✅ 已配置' if value else '❌ 未配置'}")
                    elif key.endswith("_path"):
                        st.write(f"**{key}**: `{value}`")
                    else:
                        st.write(f"**{key}**: `{value}`")


def render_vector_store_section(vector_service: VectorStoreService) -> None:
    """渲染向量存储统计部分。

    Args:
        vector_service: 向量存储服务实例。
    """
    st.divider()
    st.markdown("## 向量存储统计")

    # 获取统计信息
    summary = vector_service.get_summary()

    # 统计概览
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("后端", summary.backend_name)
    with col2:
        st.metric("集合数量", summary.total_collections)
    with col3:
        st.metric("向量总数", summary.total_vectors)

    # 集合列表
    if summary.collections:
        st.markdown("### 集合详情")
        for collection in summary.collections:
            st.write(f"- **{collection.name}**: `{collection.count}` 个向量")
    else:
        st.info("暂无集合数据")


def render_system_status_section(config_service: ConfigService) -> None:
    """渲染系统状态部分。

    Args:
        config_service: 配置服务实例。
    """
    st.divider()
    st.markdown("## 系统状态")

    col1, col2 = st.columns(2)

    with col1:
        # 可观测性状态
        observability_status = (
            "🟢 已启用" if config_service.is_observability_enabled() else "🔴 已禁用"
        )
        st.metric("可观测性", observability_status)

    with col2:
        # 日志文件路径
        log_path = config_service.get_log_file_path()
        st.metric("日志路径", f"`{log_path}`")


def render() -> None:
    """渲染系统总览页面。"""
    st.set_page_config(
        page_title="系统总览",
        page_icon="📊",
        layout="wide",
    )

    st.title("📊 系统总览")
    st.markdown("---")

    # 加载配置（使用缓存避免重复读取）
    @st.cache_resource
    def load_services():
        """加载服务实例（缓存）。"""
        settings = load_settings()
        config_service = ConfigService(settings)
        vector_service = VectorStoreService(settings)
        return config_service, vector_service

    config_service, vector_service = load_services()

    # 组件配置展示
    st.markdown("## 组件配置")
    components = config_service.get_all_components()

    # 使用网格布局展示组件卡片
    cols = st.columns(2)
    for i, component in enumerate(components):
        with cols[i % 2]:
            render_component_card(
                {
                    "name": component.name,
                    "provider": component.provider,
                    "model": component.model,
                    "details": component.details,
                }
            )

    # 向量存储统计
    render_vector_store_section(vector_service)

    # 系统状态
    render_system_status_section(config_service)


if __name__ == "__page__":
    render()
elif __name__ == "__main__":
    render()