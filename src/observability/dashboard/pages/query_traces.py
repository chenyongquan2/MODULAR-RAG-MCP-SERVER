"""Query 追踪页面。

展示查询历史、Dense/Sparse 对比、Rerank 变化。

Note: 此页面为占位实现，完整实现需要 G6 任务。
"""

from __future__ import annotations

import streamlit as st


def render() -> None:
    """渲染查询追踪占位页面。"""
    st.set_page_config(
        page_title="查询追踪",
        page_icon="🔍",
        layout="wide",
    )

    st.title("🔍 查询追踪")
    st.markdown("---")

    st.info("🚧 此页面正在开发中")

    st.markdown("""
    **功能预览：**

    - 📜 查询历史：按时间倒序展示 `trace_type == "query"` 记录
    - 🔎 关键词搜索：支持按 Query 关键词搜索历史记录
    - 📊 详情分析：耗时瀑布图 + Dense vs Sparse 并列对比 + Rerank 前后排名变化

    *完成此页面需要：G6 任务*
    """)


if __name__ == "__page__":
    render()
elif __name__ == "__main__":
    render()