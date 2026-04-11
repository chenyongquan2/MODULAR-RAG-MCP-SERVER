"""Query 追踪页面。

展示查询历史列表、阶段耗时瀑布图、Dense/Sparse 对比、Rerank 变化。
"""

from __future__ import annotations

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime

from src.observability.dashboard.services.trace_service import TraceService


def render() -> None:
    """渲染查询追踪页面。

    注意：页面配置在 app.py 中统一设置，此处不再调用 st.set_page_config()
    """
    st.title("🔍 查询追踪")
    st.markdown("---")

    # 初始化 Trace 服务
    trace_service = TraceService()

    # 检查 trace 文件是否可用
    if not trace_service.is_available:
        st.warning("⚠️ 未找到追踪记录，请先执行查询操作。")
        st.info("追踪记录存储在 `logs/traces.jsonl` 文件中。")
        return

    # 加载追踪记录
    with st.spinner("加载追踪记录..."):
        traces = trace_service.get_query_traces(limit=100)

    if not traces:
        st.info("暂无查询记录")
        return

    # 显示统计信息
    st.subheader("📈 统计概览")
    col1, col2, col3, col4 = st.columns(4)

    total = len(traces)
    success = sum(1 for t in traces if t.status == "success")
    failed = sum(1 for t in traces if t.status == "failed")
    avg_time = sum(t.total_elapsed_ms for t in traces if t.total_elapsed_ms) / total if total > 0 else 0

    col1.metric("总记录数", total)
    col2.metric("成功", success, delta_color="normal")
    col3.metric("失败", failed, delta_color="inverse")
    col4.metric("平均耗时", f"{avg_time:.2f} ms")

    st.markdown("---")

    # 搜索和筛选
    st.subheader("🔎 查询历史")

    # 关键词搜索
    search_query = st.text_input("按查询文本搜索", placeholder="输入关键词...")
    if search_query:
        traces = [t for t in traces if _contains_query(t, search_query)]

    if not traces:
        st.info("未找到匹配的查询记录")
        return

    # 准备数据表格
    table_data = []
    for trace in traces:
        query_text = trace.get_stage_data("query_processing", {}).get("query", "-")
        truncated_query = _truncate_text(query_text, max_len=40)

        table_data.append({
            "时间": trace.timestamp_dt.strftime("%Y-%m-%d %H:%M:%S") if trace.timestamp_dt else "-",
            "状态": _get_status_badge(trace.status),
            "查询": truncated_query,
            "耗时": f"{trace.total_elapsed_ms:.2f} ms" if trace.total_elapsed_ms else "-",
            "阶段数": trace.stage_count,
        })

    df = pd.DataFrame(table_data)

    # 显示表格
    st.dataframe(
        df,
        use_container_width=True,
        height=300,
        hide_index=True,
    )

    st.markdown("---")

    # 详情查看
    st.subheader("📊 详细分析")

    # 选择要查看的记录
    trace_options = [f"{t.trace_id[:8]}... - {t.get_stage_data('query_processing', {}).get('query', 'N/A')}" for t in traces]
    selected_idx = st.selectbox(
        "选择要查看的记录",
        range(len(trace_options)),
        format_func=lambda i: trace_options[i],
    )

    if selected_idx is not None:
        trace = traces[selected_idx]
        _render_trace_detail(trace)


def _contains_query(trace: TraceRecord, keyword: str) -> bool:
    """检查 trace 是否包含指定的查询关键词。

    Args:
        trace: 追踪记录对象
        keyword: 搜索关键词

    Returns:
        是否包含关键词
    """
    query_data = trace.get_stage_data("query_processing")
    if not query_data:
        return False
    query_text = query_data.get("query", "")
    return keyword.lower() in query_text.lower()


def _get_status_badge(status: str) -> str:
    """获取状态徽章。

    Args:
        status: 状态字符串

    Returns:
        带表情符号的状态文本
    """
    status_map = {
        "success": "✅ 成功",
        "failed": "❌ 失败",
        "skipped": "⏭️ 跳过",
        "processing": "⏳ 处理中",
    }
    return status_map.get(status.lower(), status)


def _truncate_text(text: str, max_len: int = 50) -> str:
    """截断过长的文本。

    Args:
        text: 原始文本
        max_len: 最大长度

    Returns:
        截断后的文本
    """
    if len(text) <= max_len:
        return text
    return f"...{text[-(max_len - 3):]}"


def _render_trace_detail(trace: TraceRecord) -> None:
    """渲染追踪记录详情。

    Args:
        trace: 追踪记录对象
    """
    # 基本信息
    col1, col2, col3 = st.columns(3)
    col1.write(f"**Trace ID:** `{trace.trace_id}`")
    col2.write(f"**时间:** {trace.timestamp_dt.strftime('%Y-%m-%d %H:%M:%S') if trace.timestamp_dt else '-'}")
    col3.write(f"**状态:** {_get_status_badge(trace.status)}")

    # 显示查询文本
    query_data = trace.get_stage_data("query_processing")
    if query_data:
        query_text = query_data.get("query", "-")
        st.write(f"**查询:** {query_text}")

    st.markdown("---")

    # 耗时瀑布图
    st.subheader("📊 阶段耗时瀑布图")

    # Query trace 阶段：query_processing -> dense_retrieval -> sparse_retrieval -> fusion -> rerank
    stages = ["query_processing", "dense_retrieval", "sparse_retrieval", "fusion", "rerank"]
    stage_labels = []
    stage_durations = []
    stage_colors = []

    for stage in stages:
        duration = trace.get_stage_duration(stage)
        if duration is not None:
            stage_labels.append(stage.upper())
            stage_durations.append(duration)

            # 根据阶段设置颜色
            if stage == "query_processing":
                stage_colors.append("#1f77b4")  # 蓝色
            elif stage == "dense_retrieval":
                stage_colors.append("#ff7f0e")  # 橙色
            elif stage == "sparse_retrieval":
                stage_colors.append("#2ca02c")  # 绿色
            elif stage == "fusion":
                stage_colors.append("#d62728")  # 红色
            elif stage == "rerank":
                stage_colors.append("#9467bd")  # 紫色

    if stage_durations:
        # 创建水平条形图（瀑布图样式）
        fig = go.Figure(data=[
            go.Bar(
                y=stage_labels,
                x=stage_durations,
                orientation='h',
                marker_color=stage_colors,
                text=[f"{d:.2f} ms" for d in stage_durations],
                textposition='outside',
            )
        ])
        fig.update_layout(
            xaxis_title="耗时 (ms)",
            yaxis_title="阶段",
            title="各阶段处理耗时",
            height=300,
            margin=dict(l=10, r=10, t=40, b=40),
        )
        fig.update_yaxes(categoryorder="array", categoryarray=stage_labels)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("暂无阶段耗时数据")

    st.markdown("---")

    # Dense vs Sparse 对比
    st.subheader("🔄 Dense vs Sparse 检索对比")

    dense_data = trace.get_stage_data("dense_retrieval")
    sparse_data = trace.get_stage_data("sparse_retrieval")

    col1, col2 = st.columns(2)

    with col1:
        st.info("### Dense 检索")
        if dense_data:
            st.write(f"**方法:** {dense_data.get('method', 'N/A')}")
            st.write(f"**结果数量:** {dense_data.get('count', 0)}")
            if dense_data.get("error"):
                st.error(f"**错误:** {dense_data.get('error')}")
        else:
            st.write("暂无数据")

    with col2:
        st.success("### Sparse 检索")
        if sparse_data:
            st.write(f"**方法:** {sparse_data.get('method', 'N/A')}")
            st.write(f"**结果数量:** {sparse_data.get('count', 0)}")
            if sparse_data.get("error"):
                st.error(f"**错误:** {sparse_data.get('error')}")
        else:
            st.write("暂无数据")

    st.markdown("---")

    # Fusion 和 Rerank 分析
    st.subheader("⚡ Fusion 与 Rerank 分析")

    fusion_data = trace.get_stage_data("fusion")
    rerank_data = trace.get_stage_data("rerank")

    col1, col2 = st.columns(2)

    with col1:
        st.warning("### Fusion 阶段")
        if fusion_data:
            st.write(f"**方法:** {fusion_data.get('method', 'N/A')}")
            st.write(f"**Dense 输入:** {fusion_data.get('input_dense', 0)}")
            st.write(f"**Sparse 输入:** {fusion_data.get('input_sparse', 0)}")
            st.write(f"**融合输出:** {fusion_data.get('output_count', 0)}")
        else:
            st.write("暂无数据")

    with col2:
        st.error("### Rerank 阶段")
        if rerank_data:
            st.write(f"**方法:** {rerank_data.get('method', 'N/A')}")
            st.write(f"**输入数量:** {rerank_data.get('input_count', 0)}")
            st.write(f"**输出数量:** {rerank_data.get('output_count', 0)}")
            fallback = rerank_data.get('fallback', False)
            if fallback:
                st.warning("⚠️ **使用了回退策略**")
            else:
                st.success("✅ **正常重排序**")
        else:
            st.write("暂无数据")

    st.markdown("---")

    # 阶段详细数据
    st.subheader("📋 阶段详细数据")

    if trace.stages:
        for stage_data in trace.stages:
            stage_name = stage_data.get("name", "").upper()
            duration = stage_data.get("duration_ms")
            stage_metadata = stage_data.get("data", {})

            with st.expander(f"🔹 {stage_name} - {duration:.2f} ms"):
                # 显示阶段元数据
                if stage_metadata:
                    for key, value in stage_metadata.items():
                        if key == "error" and value:
                            st.error(f"**错误:** {value}")
                        else:
                            st.write(f"**{key}:** `{value}`")
                else:
                    st.write("无额外数据")
    else:
        st.info("暂无阶段数据")


if __name__ == "__page__":
    render()
elif __name__ == "__main__":
    render()