"""Dashboard 主应用入口。

提供基于 Streamlit st.navigation 的多页面 Dashboard 架构。

Design Principles Applied:
- Modularity: 每个页面独立模块，职责清晰
- Maintainability: 使用 Streamlit 官方推荐的多页面架构
- Extensibility: 新增页面只需添加新的 page 对象

页面列表：
- 系统总览 (overview): 展示系统配置和数据统计
- 数据浏览 (data_browser): 占位页面 (G3)
- 摄取管理 (ingestion_manager): 占位页面 (G4)
- 查询追踪 (query_traces): 占位页面 (G6)
- 摄取追踪 (ingestion_traces): 占位页面 (G5)
- 评估面板 (evaluation_panel): 占位页面 (H4)
"""

from __future__ import annotations

import streamlit as st

from src.observability.dashboard.pages import overview, data_browser, ingestion_manager, query_traces, ingestion_traces, evaluation_panel


def render_sidebar() -> None:
    """渲染侧边栏。

    显示应用标题和说明信息。
    """
    with st.sidebar:
        st.title("🎛️ RAG Dashboard")
        st.write("---")
        st.markdown("""
        **模块化 RAG 系统管理平台**

        通过此仪表盘可以：
        - 查看系统组件配置
        - 监控数据统计
        - 管理文档摄取
        - 分析查询性能
        - 运行质量评估
        """)


def render_main_app() -> None:
    """渲染主应用。

    使用 Streamlit 的 st.navigation API 实现多页面导航。
    """
    # 设置页面配置
    st.set_page_config(
        page_title="RAG Dashboard",
        page_icon="🎛️",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    # 渲染侧边栏
    render_sidebar()

    # 定义所有页面（使用 st.pages）
    # 注意：这是 Streamlit 1.28+ 的推荐做法
    # 页面顺序将决定导航栏中的显示顺序

    # Overview 页面已完整实现，其他页面为占位实现
    pages = [
        st.Page(overview.render, title="系统总览", icon="📊"),
        st.Page(data_browser.render, title="数据浏览", icon="📁"),
        st.Page(ingestion_manager.render, title="摄取管理", icon="📥"),
        st.Page(query_traces.render, title="查询追踪", icon="🔍"),
        st.Page(ingestion_traces.render, title="摄取追踪", icon="📊"),
        st.Page(evaluation_panel.render, title="评估面板", icon="📈"),
    ]

    # 创建导航对象
    pg = st.navigation(pages)

    # 渲染当前页面
    pg.run()


if __name__ == "__main__":
    render_main_app()