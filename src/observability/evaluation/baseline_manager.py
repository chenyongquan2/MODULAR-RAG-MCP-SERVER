"""BaselineManager — 评估基线标记、查询与 delta 计算 (Feature-001 T031).

实现 spec § FR-008 / FR-009 + data-model § 2.6/2.7/2.8 + research § Decision 3。

存储模型(单 JSON 文件,原子写):
    logs/baselines.json:
    {
      "_schema_version": 1,
      "current": {
        "<collection_name>": {
          "report_id": "<uuid4>",
          "marked_at": "<iso8601>",
          "marked_by": "manual",
          "acceptance_status": "pass"
        }
      },
      "history": {
        "<collection_name>": [
          {"report_id": "<uuid_old>", "marked_at": ..., "demoted_at": ...}
        ]
      }
    }

为什么独立实现 BaselineManager 而不复用 EvaluationService.mark_as_baseline:
- 旧 EvaluationService 用 evals.jsonl 单文件 + ``is_baseline`` flag,无 collection
  维度、无 UUID4 主键、无 history 列表
- 新 spec 要求 per-collection 一份当前基线 + 完整 history(FR-008/spec § Edge Cases)
- 两套机制并存:旧 dashboard 继续读 evals.jsonl,新 EvalRunner 通过本类读
  baselines.json + evaluation_reports/<run_id>.json

宪法 § I provider-agnostic 不适用本模块(纯文件 IO 工具,不绑任何 LLM/向量库
provider);宪法 § II 配置驱动通过 ``settings.evaluation.baseline_store_path``
+ ``report_archive_dir`` 满足。
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from src.core.types import AcceptanceStatus, Baseline, DeltaReport
from src.observability.logger import get_logger

if TYPE_CHECKING:
    from src.core.settings import Settings


logger = get_logger(__name__)


CURRENT_SCHEMA_VERSION = 1


class BaselineManager:
    """Per-collection 基线标记与 delta 计算。

    Args:
        settings: 全局 Settings,读 ``settings.evaluation.baseline_store_path``
            与 ``settings.evaluation.report_archive_dir``。
    """

    def __init__(self, settings: "Settings") -> None:
        self._settings = settings
        self._store_path = Path(settings.evaluation.baseline_store_path)
        self._archive_dir = Path(settings.evaluation.report_archive_dir)

    # ------------------------------------------------------------------
    # 核心操作:标记 / 查询当前 / 查询历史
    # ------------------------------------------------------------------

    def mark_as_baseline(
        self,
        report_id: str,
        collection: str,
        acceptance_status: AcceptanceStatus = AcceptanceStatus.FAIL,
        marked_by: str = "manual",
        retrieval_mode: str = "",
        corpus_validity: str = "",
    ) -> Baseline:
        """把指定报告标记为该 collection 的当前基线。

        旧的当前基线(若存在)被移到 ``history[<collection>]`` 列表(spec § FR-008
        "可保留历史基线记录")。

        Args:
            report_id: 已归档的 EvaluationReport 的 UUID4(必须已存在于
                ``report_archive_dir/<report_id>.json``,否则拒绝)。
            collection: 该基线绑定的 collection 名。
            acceptance_status: 此报告的 pass/fail(从报告 JSON 读出后传入,或调用
                方提供;BaselineStore 冗余存储,便于面板查询不必再读 report)。
            marked_by: 标记者标识(MVP 阶段默认 "manual")。
            retrieval_mode: 该次评估实际生效的检索模式(feature-004 T032)。
                ``"dense_only"`` | ``"hybrid"``;留空表示未标注。
            corpus_validity: 语料是否与金标匹配(feature-004 T032)。
                ``"valid"`` | ``"mismatched"``;留空表示未标注。

        Returns:
            新创建的 Baseline 对象。

        Raises:
            ValueError: report_id 在 archive_dir 中不存在;或 collection 为空。
        """
        if not collection or not collection.strip():
            raise ValueError("collection cannot be empty")
        report_path = self._archive_dir / f"{report_id}.json"
        if not report_path.exists():
            raise ValueError(
                f"report_id '{report_id}' not found in archive ({report_path}); "
                "ensure the evaluation was run with --archive (default)"
            )

        store = self._read_store()
        current = store.setdefault("current", {})
        history = store.setdefault("history", {})

        now_iso = datetime.now(timezone.utc).isoformat()

        # 旧的当前基线降级到 history
        old_current = current.get(collection)
        if old_current is not None:
            collection_history: list[dict[str, Any]] = history.setdefault(collection, [])
            demoted = dict(old_current)
            demoted["demoted_at"] = now_iso
            collection_history.append(demoted)

        # 新基线写入 current
        new_baseline_dict = {
            "report_id": report_id,
            "collection": collection,
            "marked_at": now_iso,
            "marked_by": marked_by,
            "acceptance_status": acceptance_status.value
            if isinstance(acceptance_status, AcceptanceStatus)
            else str(acceptance_status),
            "retrieval_mode": retrieval_mode,
            "corpus_validity": corpus_validity,
        }
        current[collection] = new_baseline_dict

        self._write_store_atomic(store)
        logger.info(
            "Marked baseline: collection=%s report_id=%s status=%s (old baseline %s)",
            collection, report_id, new_baseline_dict["acceptance_status"],
            "moved to history" if old_current is not None else "(none)",
        )

        return Baseline(
            report_id=report_id,
            collection=collection,
            marked_at=now_iso,
            marked_by=marked_by,
            acceptance_status=AcceptanceStatus(new_baseline_dict["acceptance_status"]),
            retrieval_mode=retrieval_mode,
            corpus_validity=corpus_validity,
        )

    def annotate_baseline(
        self,
        collection: str,
        retrieval_mode: str | None = None,
        corpus_validity: str | None = None,
    ) -> Baseline:
        """给某 collection 的**当前基线**补标注,不改动任何指标数字。

        用途(feature-004 T034):给 feature-004 之前的历史基线补上"它到底跑的
        是什么检索模式、语料对不对"。这些记录的数字**不是错的** —— 它们真实
        反映了当时的系统行为;错的只是当时以为自己在跑混合检索。

        Args:
            collection: 目标 collection。
            retrieval_mode: 新的检索模式标注;``None`` 表示不改该字段。
            corpus_validity: 新的语料有效性标注;``None`` 表示不改该字段。

        Returns:
            更新后的 Baseline。

        Raises:
            ValueError: 该 collection 没有当前基线。
        """
        store = self._read_store()
        current = store.setdefault("current", {})

        record = current.get(collection)
        if record is None:
            raise ValueError(f"no current baseline for collection '{collection}'")

        if retrieval_mode is not None:
            record["retrieval_mode"] = retrieval_mode
        if corpus_validity is not None:
            record["corpus_validity"] = corpus_validity

        self._write_store_atomic(store)
        logger.info(
            "Annotated baseline: collection=%s retrieval_mode=%s corpus_validity=%s",
            collection, record.get("retrieval_mode"), record.get("corpus_validity"),
        )

        return Baseline.from_dict(record)

    def get_current_baseline(self, collection: str) -> Optional[Baseline]:
        """获取该 collection 的当前基线;无则返回 None。"""
        store = self._read_store()
        current = store.get("current", {})
        entry = current.get(collection)
        if entry is None:
            return None
        # 走 Baseline.from_dict 而非手工构造:此前这里逐字段列举,新增字段时
        # 极易漏掉一处(feature-004 加 retrieval_mode/corpus_validity 时就漏了),
        # 而漏掉的表现是字段静默变空 —— 又是一次静默失效
        return Baseline.from_dict({**entry, "collection": collection})

    def get_history(self, collection: str) -> list[dict[str, Any]]:
        """获取该 collection 的历史基线列表(按 demotion 时间顺序)。

        每条 entry 含 ``report_id``/``marked_at``/``marked_by``/``acceptance_status``
        + ``demoted_at``(被新基线替换的时间)。
        """
        store = self._read_store()
        return list(store.get("history", {}).get(collection, []))

    # ------------------------------------------------------------------
    # Delta 计算
    # ------------------------------------------------------------------

    def compute_delta(
        self,
        current_report: dict[str, Any],
        baseline_report: dict[str, Any],
    ) -> DeltaReport:
        """计算当前评估与基线的 delta(简单相减,正数 = 提升)。

        覆盖 8 项主聚合 + by-tag 切片(对齐 EvaluationReport 字段)。
        切片只在两份报告**都**含该切片且**都**未 skipped 时才计 delta;否则该
        per_tag entry 为 None(避免误把 skipped 当成 0 分参与减法)。

        Args:
            current_report: 当前评估报告 dict(已含 aggregate_metrics 等字段)。
            baseline_report: 基线评估报告 dict。

        Returns:
            DeltaReport 实例。
        """
        cur_run_id = str(current_report.get("run_id", ""))
        base_run_id = str(baseline_report.get("run_id", ""))

        # 主聚合 delta
        cur_aggr = current_report.get("aggregate_metrics", {}) or {}
        base_aggr = baseline_report.get("aggregate_metrics", {}) or {}
        per_metric_delta: dict[str, float] = {}
        for metric_key, cur_value in cur_aggr.items():
            base_value = base_aggr.get(metric_key)
            if base_value is None:
                continue
            try:
                cur_f = float(cur_value)
                base_f = float(base_value)
            except (TypeError, ValueError):
                continue
            # NaN 不参与减法(任一 NaN → delta 为 NaN);保持 dict 中 key 存在
            per_metric_delta[metric_key] = cur_f - base_f

        # by-tag delta
        cur_by_tag = current_report.get("aggregate_metrics_by_tag", {}) or {}
        base_by_tag = baseline_report.get("aggregate_metrics_by_tag", {}) or {}
        per_tag_delta: dict[str, dict[str, Optional[dict[str, float]]]] = {}
        for dim, cur_dim_values in cur_by_tag.items():
            base_dim_values = base_by_tag.get(dim, {}) or {}
            dim_result: dict[str, Optional[dict[str, float]]] = {}
            for value, cur_slice in cur_dim_values.items():
                base_slice = base_dim_values.get(value)
                # 任一边 skipped 或缺失 → 该切片 delta 为 None
                if (
                    not isinstance(cur_slice, dict)
                    or not isinstance(base_slice, dict)
                    or cur_slice.get("_skipped_reason")
                    or base_slice.get("_skipped_reason")
                ):
                    dim_result[value] = None
                    continue
                slice_delta: dict[str, float] = {}
                for metric_key, cur_val in cur_slice.items():
                    if metric_key.startswith("_"):
                        continue
                    base_val = base_slice.get(metric_key)
                    if cur_val is None or base_val is None:
                        continue
                    try:
                        slice_delta[metric_key] = float(cur_val) - float(base_val)
                    except (TypeError, ValueError):
                        continue
                dim_result[value] = slice_delta if slice_delta else None
            if dim_result:
                per_tag_delta[dim] = dim_result

        return DeltaReport(
            current_report_id=cur_run_id,
            baseline_report_id=base_run_id,
            per_metric_delta=per_metric_delta,
            per_tag_delta=per_tag_delta,
        )

    # ------------------------------------------------------------------
    # 报告读取(给 EvalRunner 集成 / 面板用)
    # ------------------------------------------------------------------

    def load_report(self, report_id: str) -> dict[str, Any]:
        """从 archive 读取已归档的 EvaluationReport JSON。

        Raises:
            ValueError: report 文件不存在或非法 JSON。
        """
        report_path = self._archive_dir / f"{report_id}.json"
        if not report_path.exists():
            raise ValueError(
                f"report_id '{report_id}' not found in archive ({report_path})"
            )
        try:
            return json.loads(report_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"archived report '{report_id}' is not valid JSON: {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # 文件 IO(原子写)
    # ------------------------------------------------------------------

    def _read_store(self) -> dict[str, Any]:
        """读 baselines.json;不存在或损坏时返回初始 schema。"""
        if not self._store_path.exists():
            return self._initial_store()
        try:
            data = json.loads(self._store_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"baseline_store_path '{self._store_path}' is not valid JSON: {exc}"
            ) from exc
        # schema 版本兼容
        version = data.get("_schema_version", CURRENT_SCHEMA_VERSION)
        if version != CURRENT_SCHEMA_VERSION:
            raise ValueError(
                f"baselines.json _schema_version={version} not supported "
                f"(expected {CURRENT_SCHEMA_VERSION})"
            )
        # 确保关键 key 存在
        data.setdefault("current", {})
        data.setdefault("history", {})
        return data

    @staticmethod
    def _initial_store() -> dict[str, Any]:
        return {"_schema_version": CURRENT_SCHEMA_VERSION, "current": {}, "history": {}}

    def _write_store_atomic(self, store: dict[str, Any]) -> None:
        """原子写:写到临时文件 → ``os.replace`` 重命名,避免半写状态。"""
        self._store_path.parent.mkdir(parents=True, exist_ok=True)
        # mkstemp 在同目录下创建临时文件,os.replace 才能跨 fs 安全
        fd, tmp_path_str = tempfile.mkstemp(
            prefix=".baselines.", suffix=".tmp", dir=str(self._store_path.parent)
        )
        tmp_path = Path(tmp_path_str)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(store, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self._store_path)
        except Exception:
            # 失败时清理临时文件
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except OSError:
                pass
            raise
