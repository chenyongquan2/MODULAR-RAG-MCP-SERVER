"""评估面板页面。

支持运行评估、展示指标与查看历史趋势。
"""

from __future__ import annotations

import streamlit as st

from src.core.settings import load_settings
from src.observability.dashboard.services import EvaluationService
from src.observability.evaluation.eval_runner import EvalReport


def _render_summary_metrics(report: EvalReport) -> None:
    """渲染评估摘要指标。"""
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("测试用例", report.total_cases)
    with col2:
        st.metric("Hit Rate", f"{report.hit_rate:.2%}")
    with col3:
        st.metric("MRR", f"{report.mrr:.4f}")
    with col4:
        st.metric("Source Hit", f"{report.source_hit_rate:.2%}")


def _render_aggregate_metrics(report: EvalReport) -> None:
    """渲染聚合指标表。"""
    st.subheader("聚合指标")
    if not report.aggregate_metrics:
        st.info("当前报告没有额外聚合指标。")
        return

    table_data = [
        {"metric": metric_name, "value": metric_value}
        for metric_name, metric_value in sorted(report.aggregate_metrics.items())
    ]
    st.dataframe(table_data, use_container_width=True, hide_index=True)


def _render_case_details(report: EvalReport) -> None:
    """渲染逐条用例结果。"""
    st.subheader("用例明细")
    rows: list[dict[str, object]] = []
    for case in report.case_results:
        rows.append(
            {
                "query": case.query,
                "hit": case.hit,
                "reciprocal_rank": round(case.reciprocal_rank, 4),
                "source_hit": case.source_hit,
                "retrieved_top3": ", ".join(case.retrieved_chunk_ids[:3]),
                "expected_top3": ", ".join(case.expected_chunk_ids[:3]),
            }
        )

    st.dataframe(rows, use_container_width=True, hide_index=True)


def _render_history(service: EvaluationService) -> None:
    """渲染评估历史与趋势。"""
    st.subheader("历史趋势")
    history = service.load_history(limit=30)
    if not history:
        st.info("暂无评估历史。运行一次评估后会自动记录。")
        return

    trend_source = list(reversed(history))
    trend_data = {
        "hit_rate": [item.get("hit_rate", 0.0) for item in trend_source],
        "mrr": [item.get("mrr", 0.0) for item in trend_source],
    }
    st.line_chart(trend_data, use_container_width=True)
    st.dataframe(history, use_container_width=True, hide_index=True)


def render() -> None:
    """渲染评估面板页面。

    注意：页面配置在 app.py 中统一设置，此处不再调用 st.set_page_config()
    """
    st.title("📈 评估面板")
    st.markdown("---")

    @st.cache_resource
    def load_runtime():
        """加载页面运行时依赖（缓存）。"""
        settings = load_settings()
        service = EvaluationService()
        return settings, service

    settings, service = load_runtime()

    st.subheader("运行配置")
    candidate_test_sets = service.discover_test_sets(
        default_path=settings.evaluation.golden_test_set
    )
    selectable_test_sets = candidate_test_sets or [settings.evaluation.golden_test_set]

    col1, col2 = st.columns(2)
    with col1:
        mode_label = st.selectbox(
            "评估后端",
            options=["all", "custom", "ragas"],
            format_func=lambda value: {
                "all": "All（按当前配置）",
                "custom": "Custom（轻量指标）",
                "ragas": "Ragas（语义评估）",
            }[value],
            index=0,
        )
    with col2:
        selected_test_set = st.selectbox(
            "Golden Test Set",
            options=selectable_test_sets,
            index=0,
        )

    col3, col4 = st.columns(2)
    with col3:
        top_k = st.number_input(
            "Top-K",
            min_value=1,
            step=1,
            value=int(settings.retrieval.top_k_final),
        )
    with col4:
        collection = st.text_input(
            "集合过滤（可选）",
            value="",
            placeholder="例如 default",
        )

    run_clicked = st.button("运行评估", type="primary", use_container_width=True)

    if run_clicked:
        try:
            report = service.run_evaluation(
                settings=settings,
                mode=mode_label,
                test_set_path=selected_test_set,
                top_k=int(top_k),
                collection=collection,
            )
            st.session_state["latest_eval_report"] = report
            history_entry = service.build_history_entry(
                mode=mode_label,
                test_set_path=selected_test_set,
                top_k=int(top_k),
                collection=collection,
                report=report,
            )
            service.append_history(history_entry)
            st.success("评估完成，结果已记录到历史。")
        except ImportError as exc:
            st.error(f"依赖缺失，无法运行评估：{exc}")
        except (ValueError, RuntimeError) as exc:
            st.error(f"评估失败：{exc}")
        except Exception as exc:  # pragma: no cover - 防御性分支
            st.error(f"发生未预期错误：{exc}")

    latest_report = st.session_state.get("latest_eval_report")
    if latest_report is not None:
        _render_summary_metrics(latest_report)
        _render_aggregate_metrics(latest_report)
        _render_case_details(latest_report)

    st.divider()
    _render_history(service)


if __name__ == "__page__":
    render()
elif __name__ == "__main__":
    render()
