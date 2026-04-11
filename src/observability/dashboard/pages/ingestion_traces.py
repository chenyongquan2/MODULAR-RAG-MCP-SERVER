"""Ingestion 追踪页面。

展示摄取历史列表、阶段耗时瀑布图。
"""

from __future__ import annotations

import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime

from src.observability.dashboard.services.trace_service import TraceService


def render() -> None:
    """渲染摄取追踪页面。

    注意：页面配置在 app.py 中统一设置，此处不再调用 st.set_page_config()
    """
    st.title("📊 摄取追踪")
    st.markdown("---")

    # 初始化 Trace 服务
    trace_service = TraceService()

    # 检查 trace 文件是否可用
    if not trace_service.is_available:
        st.warning("⚠️ 未找到追踪记录，请先执行文档摄取操作。")
        st.info("追踪记录存储在 `logs/traces.jsonl` 文件中。")
        return

    # 加载追踪记录
    with st.spinner("加载追踪记录..."):
        traces = trace_service.get_ingestion_traces(limit=100)

    if not traces:
        st.info("暂无摄取记录")
        return

    # 显示统计信息
    st.subheader("📈 统计概览")
    col1, col2, col3, col4 = st.columns(4)

    total = len(traces)
    success = sum(1 for t in traces if t.status == "success")
    failed = sum(1 for t in traces if t.status == "failed")
    skipped = sum(1 for t in traces if t.status == "skipped")

    col1.metric("总记录数", total)
    col2.metric("成功", success, delta_color="normal")
    col3.metric("失败", failed, delta_color="inverse")
    col4.metric("跳过", skipped, delta_color="off")

    st.markdown("---")

    # 历史列表
    st.subheader("📜 摄取历史")

    # 准备数据表格
    table_data = []
    for trace in traces:
        table_data.append({
            "时间": trace.timestamp_dt.strftime("%Y-%m-%d %H:%M:%S") if trace.timestamp_dt else "-",
            "状态": _get_status_badge(trace.status),
            "集合": trace.collection,
            "文件": _truncate_path(trace.file_path),
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
    st.subheader("🔍 详细分析")

    # 选择要查看的记录
    trace_options = [f"{t.trace_id[:8]}... - {t.file_path}" for t in traces]
    selected_idx = st.selectbox(
        "选择要查看的记录",
        range(len(trace_options)),
        format_func=lambda i: trace_options[i],
    )

    if selected_idx is not None:
        trace = traces[selected_idx]
        _render_trace_detail(trace)


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


def _truncate_path(path: str, max_len: int = 50) -> str:
    """截断过长的文件路径。

    Args:
        path: 文件路径
        max_len: 最大长度

    Returns:
        截断后的路径
    """
    if len(path) <= max_len:
        return path
    return f"...{path[-(max_len - 3):]}"


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

    st.write(f"**文件路径:** `{trace.file_path}`")

    st.markdown("---")

    # 耗时分布图
    st.subheader("📊 阶段耗时分布")

    stages = ["load", "split", "transform", "embed", "upsert"]
    stage_durations = []
    stage_labels = []

    for stage in stages:
        duration = trace.get_stage_duration(stage)
        if duration is not None:
            stage_durations.append(duration)
            stage_labels.append(stage.upper())

    if stage_durations:
        # 创建水平条形图
        fig = px.bar(
            x=stage_durations,
            y=stage_labels,
            orientation="h",
            labels={"x": "耗时 (ms)", "y": "阶段"},
            color=stage_durations,
            color_continuous_scale="Blues",
            title="各阶段处理耗时",
        )
        fig.update_layout(yaxis={"categoryorder": "total ascending"})
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("暂无阶段耗时数据")

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
