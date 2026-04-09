"""数据浏览器页面。

展示文档列表、Chunk 详情、图片预览。

Note: 此页面为占位实现，完整实现需要 G2 (DocumentManager) 和 G3 任务。
"""

from __future__ import annotations

import streamlit as st


def render() -> None:
    """渲染数据浏览器占位页面。"""
    st.set_page_config(
        page_title="数据浏览器",
        page_icon="📁",
        layout="wide",
    )

    st.title("📁 数据浏览器")
    st.markdown("---")

    st.info("🚧 此页面正在开发中")

    st.markdown("""
    **功能预览：**

    - 📄 文档列表视图：展示 source_path、集合、chunk 数、摄入时间
    - 📝 Chunk 详情视图：点击文档展开所有 chunk，显示内容、metadata、关联图片
    - 🖼️ 图片预览：查看文档中的提取图片

    *完成此页面需要：G2 (DocumentManager) + G3 任务*
    """)


if __name__ == "__page__":
    render()
elif __name__ == "__main__":
    render()