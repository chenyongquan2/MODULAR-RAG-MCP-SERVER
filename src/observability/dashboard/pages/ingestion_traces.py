"""Ingestion 追踪页面。

展示摄取历史列表、阶段耗时瀑布图。

Note: 此页面为占位实现，完整实现需要 G5 任务。
"""

from __future__ import annotations

import streamlit as st


def render() -> None:
    """渲染摄取追踪占位页面。"""
    st.set_page_config(
        page_title="摄取追踪",
        page_icon="📊",
        layout="wide",
    )

    st.title("📊 摄取追踪")
    st.markdown("---")

    st.info("🚧 此页面正在开发中")

    st.markdown("""
    **功能预览：**

    - 📜 摄取历史：按时间倒序展示 `trace_type == "ingestion"` 记录
    - 📉 耗时分析：横向条形图展示 load/split/transform/embed/upsert 耗时分布
    - 🔍 详情查看：点击记录查看详细的阶段信息和性能指标

    *完成此页面需要：G5 任务*
    """)


if __name__ == "__page__":
    render()
elif __name__ == "__main__":
    render()