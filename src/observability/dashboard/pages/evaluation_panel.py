"""评估面板页面。

运行评估、查看指标、历史对比。

Note: 此页面为占位实现，完整实现需要 H4 任务。
"""

from __future__ import annotations

import streamlit as st


def render() -> None:
    """渲染评估面板占位页面。

    注意：页面配置在 app.py 中统一设置，此处不再调用 st.set_page_config()
    """
    st.title("📈 评估面板")
    st.markdown("---")

    st.info("🚧 此页面正在开发中")

    st.markdown("""
    **功能预览：**

    - ⚙️ 配置选择：选择评估后端（Ragas/Custom）和 golden test set
    - ▶️ 运行评估：点击按钮运行评估，展示结果（hit_rate、mrr、各 query 明细）
    - 📊 历史对比：可选的历史评估结果对比图

    *完成此页面需要：H4 任务*
    """)


if __name__ == "__page__":
    render()
elif __name__ == "__main__":
    render()