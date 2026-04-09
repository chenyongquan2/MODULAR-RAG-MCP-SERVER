"""Ingestion 管理页面。

提供文件上传、摄取触发、文档删除功能。

Note: 此页面为占位实现，完整实现需要 G2 (DocumentManager) 和 G4 任务。
"""

from __future__ import annotations

import streamlit as st


def render() -> None:
    """渲染摄取管理占位页面。"""
    st.set_page_config(
        page_title="摄取管理",
        page_icon="📥",
        layout="wide",
    )

    st.title("📥 摄取管理")
    st.markdown("---")

    st.info("🚧 此页面正在开发中")

    st.markdown("""
    **功能预览：**

    - 📤 文件上传：选择文件 + 集合选择
    - 🚀 摄取触发：调用 IngestionPipeline 并显示实时进度条
    - 🗑️ 文档删除：在文档列表中提供删除按钮

    *完成此页面需要：G2 (DocumentManager) + G4 任务*
    """)


if __name__ == "__page__":
    render()
elif __name__ == "__main__":
    render()