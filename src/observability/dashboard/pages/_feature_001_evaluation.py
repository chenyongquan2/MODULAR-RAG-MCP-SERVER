"""Streamlit 视图:Feature-001 基线 + 回归 (T033).

读 ``logs/evaluation_reports/index.jsonl`` 列出近期评估,提供:
- pass/fail 视觉徽标(spec § Clarifications Q3)
- 当前基线列表(per collection),fail 基线灰色背景
- Mark-as-baseline 操作(per row,调用 BaselineManager)
- 选中评估 → delta 表(vs 当前基线)+ 详情
- 8 项主聚合指标的历史时序折线(SC-004 / FR-010)

设计:本视图独立于 legacy ``EvaluationService`` 系统,只读 Feature-001 引入的
新归档(``logs/evaluation_reports/``)+ ``logs/baselines.json``。两套系统并存,
旧 dashboard 用户可继续用经典视图。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

import streamlit as st

from src.core.settings import Settings
from src.core.types import AcceptanceStatus
from src.observability.evaluation.baseline_manager import BaselineManager


def _read_index(archive_dir: Path) -> list[dict[str, Any]]:
    """读 index.jsonl,返回 list[dict],按时间倒序(最新在前)。"""
    index_file = archive_dir / "index.jsonl"
    if not index_file.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in index_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    rows.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    return rows


def _badge_html(status: Optional[str]) -> str:
    """生成 pass/fail/n-a 颜色徽标(Streamlit markdown 支持的 emoji + color)。"""
    if status == "pass":
        return ":green[✓ pass]"
    if status == "fail":
        return ":red[✗ fail]"
    return ":gray[— n/a]"


def _load_report(archive_dir: Path, run_id: str) -> Optional[dict[str, Any]]:
    """读单份归档报告 JSON;不存在返回 None。"""
    p = archive_dir / f"{run_id}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _render_runs_list(
    runs: list[dict[str, Any]],
    settings: Settings,
    manager: BaselineManager,
    archive_dir: Path,
) -> Optional[str]:
    """渲染评估列表,返回选中 run 的 run_id(若无选中返 None)。"""
    if not runs:
        st.info(
            "暂无 Feature-001 归档评估。运行 `python scripts/evaluate.py` 后会"
            "自动写入 `logs/evaluation_reports/index.jsonl`。"
        )
        return None

    # 显示当前基线状态(每 collection 一行)
    collections = sorted({r.get("collection", "") for r in runs if r.get("collection")})
    if collections:
        st.markdown("##### 当前基线 (per collection)")
        for col in collections:
            current = manager.get_current_baseline(col)
            if current is None:
                st.markdown(f"- `{col}`:**无基线**")
            else:
                st_color = (
                    ":green"
                    if current.acceptance_status == AcceptanceStatus.PASS
                    else ":red"
                )
                st.markdown(
                    f"- `{col}`:run_id `{current.report_id[:8]}...` "
                    f"{st_color}[**{current.acceptance_status.value}**]  "
                    f"标记于 {current.marked_at}"
                )

    st.markdown("##### 评估列表(按时间倒序)")
    # 表格视图(只读),并附 selectbox 让用户挑一条 run 看详情
    table_rows = []
    for r in runs[:30]:  # 最近 30 条
        table_rows.append({
            "run_id_short": (r.get("run_id") or "")[:8] + "...",
            "collection": r.get("collection", ""),
            "created_at": r.get("created_at", ""),
            "acceptance_status": r.get("acceptance_status", "n/a"),
            "judge": r.get("judge_llm_identifier") or "—",
            "embedding": r.get("embedding_identifier") or "—",
            "n_cases": r.get("total_cases", 0),
        })
    st.dataframe(table_rows, use_container_width=True, hide_index=True)

    # selectbox 让用户挑选 run_id 详查
    options = [(r.get("run_id"), f"{(r.get('run_id') or '')[:8]}... | {r.get('collection', '')} | {r.get('created_at', '')[:19]}") for r in runs[:30]]
    selected_label = st.selectbox(
        "选择一条评估查看详情 / 标记为基线",
        options=[label for _, label in options],
        index=0 if options else None,
    )
    if selected_label is None:
        return None
    selected_run_id = next((rid for rid, label in options if label == selected_label), None)
    return selected_run_id


def _render_run_detail(
    run_id: str,
    settings: Settings,
    manager: BaselineManager,
    archive_dir: Path,
) -> None:
    """选中 run 的详情视图 + Mark-as-baseline 按钮 + delta 表。"""
    report = _load_report(archive_dir, run_id)
    if report is None:
        st.error(f"找不到归档报告 {run_id}.json")
        return

    collection = report.get("collection", "")
    status = report.get("acceptance_status", "n/a")
    st.markdown(
        f"#### Run `{run_id[:8]}...` | collection `{collection}` "
        f"| {_badge_html(status)}"
    )

    # 元信息
    meta_cols = st.columns(4)
    meta_cols[0].metric("Total cases", report.get("total_cases", 0))
    meta_cols[1].metric("Degraded", report.get("degraded_case_count", 0))
    meta_cols[2].metric("Hit rate", f"{float(report.get('hit_rate', 0.0)):.2%}")
    meta_cols[3].metric("MRR", f"{float(report.get('mrr', 0.0)):.4f}")

    # judge / embedding identifier
    st.caption(
        f"Judge: `{report.get('judge_llm_identifier') or '—'}` | "
        f"Embedding: `{report.get('embedding_identifier') or '—'}` | "
        f"Test set: `{report.get('test_set_path', '')}` (v{report.get('test_set_version', '?')})"
    )

    # 8 项主聚合指标 + acceptance_thresholds_snapshot
    st.markdown("##### 主聚合指标 vs 阈值")
    aggr = report.get("aggregate_metrics", {}) or {}
    snap = report.get("acceptance_thresholds_snapshot", {}) or {}
    metric_table = []
    for metric_key in sorted(set(list(aggr.keys()) + list(snap.keys()))):
        v = aggr.get(metric_key)
        threshold = snap.get(metric_key)
        passed = (
            "—" if v is None or threshold is None
            else "✓" if isinstance(v, (int, float)) and not _is_nan(v) and v >= threshold
            else "✗"
        )
        metric_table.append({
            "metric": metric_key,
            "value": "NaN" if isinstance(v, float) and _is_nan(v) else v,
            "threshold": threshold,
            "pass": passed,
        })
    st.dataframe(metric_table, use_container_width=True, hide_index=True)

    # Mark as baseline 按钮
    current_baseline = manager.get_current_baseline(collection)
    is_current = current_baseline is not None and current_baseline.report_id == run_id
    if is_current:
        st.success(f"✓ 此 run 已是 `{collection}` 的当前基线 (标记于 {current_baseline.marked_at})")
    else:
        if st.button(
            f"🎯 标记为 `{collection}` 当前基线",
            help="把此评估设为该 collection 的当前基线;旧基线移到 history",
            type="primary" if status == "pass" else "secondary",
        ):
            try:
                acc_status = AcceptanceStatus(status) if status in ("pass", "fail") else AcceptanceStatus.FAIL
                manager.mark_as_baseline(
                    report_id=run_id, collection=collection,
                    acceptance_status=acc_status, marked_by="dashboard",
                )
                st.success("已标记为基线;请刷新页面查看 delta 视图。")
                st.rerun()
            except Exception as exc:
                st.error(f"标记失败:{exc}")

    # Delta 视图(若 report 已含 baseline_id)
    if report.get("baseline_id"):
        st.markdown("##### Delta vs Baseline")
        delta_aggr = report.get("delta_aggregate_metrics", {}) or {}
        delta_rows = [
            {"metric": k, "delta": v, "direction": "↑" if (isinstance(v, (int, float)) and v > 0) else "↓" if (isinstance(v, (int, float)) and v < 0) else "—"}
            for k, v in sorted(delta_aggr.items())
        ]
        st.dataframe(delta_rows, use_container_width=True, hide_index=True)
        if report.get("delta_hit_rate") is not None:
            st.caption(
                f"顶层 delta:hit_rate {report.get('delta_hit_rate'):+.4f}, "
                f"mrr {report.get('delta_mrr'):+.4f}"
            )

    # by-tag 切片诊断
    by_tag = report.get("aggregate_metrics_by_tag") or {}
    if by_tag:
        with st.expander("by-tag 切片诊断 (FR-015)", expanded=False):
            for dim, dim_values in by_tag.items():
                st.markdown(f"**Dimension: `{dim}`**")
                rows = []
                for value, slice_data in dim_values.items():
                    if isinstance(slice_data, dict) and slice_data.get("_skipped_reason"):
                        rows.append({
                            "value": value,
                            "status": f"skipped ({slice_data['_skipped_reason']})",
                            **{k: "—" for k in slice_data if not k.startswith("_")},
                        })
                    elif isinstance(slice_data, dict):
                        rows.append({"value": value, "status": "ok", **slice_data})
                if rows:
                    st.dataframe(rows, use_container_width=True, hide_index=True)


def _render_trend(runs: list[dict[str, Any]], archive_dir: Path) -> None:
    """读取每个 run 的完整 report,按 created_at 升序绘 8 项指标的折线 (FR-010)."""
    if len(runs) < 2:
        st.caption("至少需要 2 次评估才能呈现趋势 (当前 %d 次)" % len(runs))
        return

    # 取近 30 次,按时间升序
    selected = sorted(runs[:30], key=lambda r: r.get("created_at", ""))
    metric_names = [
        "ragas__context_recall", "ragas__context_precision",
        "ragas__faithfulness", "ragas__answer_relevancy",
        "custom__hit_rate", "custom__mrr", "custom__recall", "custom__ndcg",
    ]
    trend_data: dict[str, list[float]] = {m: [] for m in metric_names}
    timestamps: list[str] = []
    for r in selected:
        rid = r.get("run_id")
        if not rid:
            continue
        report = _load_report(archive_dir, rid)
        if report is None:
            continue
        aggr = report.get("aggregate_metrics", {}) or {}
        timestamps.append((r.get("created_at") or "")[:19])
        for m in metric_names:
            v = aggr.get(m)
            try:
                trend_data[m].append(float(v) if v is not None else float("nan"))
            except (TypeError, ValueError):
                trend_data[m].append(float("nan"))

    if not timestamps:
        st.caption("没有可读取的归档报告。")
        return
    # streamlit line_chart 接受 dict
    st.markdown("##### 8 项主聚合指标趋势 (近 30 次)")
    st.line_chart(trend_data, use_container_width=True)
    st.caption(f"X 轴:run 序号(0 = 最早,{len(timestamps) - 1} = 最近) | timestamps: {timestamps[0]} → {timestamps[-1]}")


def _is_nan(v: Any) -> bool:
    """跨平台 NaN 检测。"""
    try:
        import math
        return isinstance(v, float) and math.isnan(v)
    except Exception:
        return False


def render_feature_001_view(settings: Settings) -> None:
    """主入口:Feature-001 评估面板视图。"""
    archive_dir = Path(settings.evaluation.report_archive_dir)
    if not archive_dir.exists():
        st.info(
            "Feature-001 评估归档目录尚未生成。"
            "运行 `python scripts/evaluate.py --pretty` 后会自动创建。"
        )
        return

    manager = BaselineManager(settings)
    runs = _read_index(archive_dir)

    selected_run_id = _render_runs_list(runs, settings, manager, archive_dir)
    if selected_run_id:
        st.divider()
        _render_run_detail(selected_run_id, settings, manager, archive_dir)

    st.divider()
    _render_trend(runs, archive_dir)
