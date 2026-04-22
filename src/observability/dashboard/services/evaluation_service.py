"""评估面板服务层。

封装评估执行与历史记录持久化逻辑，供 Dashboard 页面调用。
"""

from __future__ import annotations

import copy
import dataclasses
import json
import logging
import os
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

from src.core.query_engine.hybrid_search import HybridSearch
from src.core.settings import Settings
from src.libs.evaluator.base_evaluator import BaseEvaluator
from src.libs.evaluator.evaluator_factory import EvaluatorFactory
from src.observability.evaluation.eval_runner import EvalReport, EvalRunner

_logger = logging.getLogger(__name__)


class EvaluationService:
    """评估服务。

    负责：
    1. 根据用户选择运行单次评估；
    2. 读写评估历史（JSON Lines）。
    """

    DEFAULT_HISTORY_FILE = Path("logs/evaluations.jsonl")

    def __init__(self, history_file: Optional[Path] = None) -> None:
        """初始化评估服务。

        Args:
            history_file: 历史文件路径，默认 ``logs/evaluations.jsonl``。
        """
        self._history_file = history_file or self.DEFAULT_HISTORY_FILE

    def discover_test_sets(
        self,
        default_path: str,
        fixtures_dir: Optional[Path] = None,
    ) -> list[str]:
        """发现可选的 golden test set 文件。

        Args:
            default_path: 配置中的默认测试集路径。
            fixtures_dir: 搜索目录，默认 ``tests/fixtures``。

        Returns:
            去重后的文件路径列表（字符串），按字典序排序。
        """
        candidates: set[str] = set()
        default_file = Path(default_path)
        if default_file.exists():
            candidates.add(default_path)

        search_root = fixtures_dir or Path("tests/fixtures")
        if search_root.exists():
            for file_path in search_root.rglob("*.json"):
                if "golden" in file_path.name.lower():
                    candidates.add(str(file_path))

        return sorted(candidates)

    def resolve_backends(self, mode: str, current_backends: list[str]) -> list[str]:
        """根据页面选择解析评估后端列表。

        Args:
            mode: 页面模式（``all``/``custom``/``ragas``）。
            current_backends: 当前 settings 中配置的后端列表。

        Returns:
            可用于 ``settings.evaluation.backends`` 的标准化后端列表。
        """
        normalized_mode = mode.lower().strip()
        if normalized_mode == "custom":
            return ["custom"]
        if normalized_mode == "ragas":
            return ["ragas"]

        normalized_existing = [backend.lower() for backend in current_backends if backend]
        return normalized_existing or ["custom"]

    def run_evaluation(
        self,
        settings: Settings,
        mode: str,
        test_set_path: str,
        top_k: int,
        collection: str,
        hybrid_search_builder: Callable[[Settings], Any] = HybridSearch,
        evaluator_builder: Optional[Callable[[Settings], BaseEvaluator]] = None,
        runner_builder: Callable[[Settings, Any, BaseEvaluator], EvalRunner] = EvalRunner,
        response_builder_builder: Optional[Callable[[Settings], Any]] = None,
        compare_baseline: bool = True,
    ) -> EvalReport:
        """运行评估并返回报告。

        Args:
            settings: 全局配置对象。
            mode: 后端模式（all/custom/ragas）。
            test_set_path: 测试集路径。
            top_k: 每条 query 的召回条数。
            collection: 集合过滤器，空字符串表示不启用。
            hybrid_search_builder: HybridSearch 构造器（便于测试注入）。
            evaluator_builder: Evaluator 构造器（便于测试注入）。
            runner_builder: EvalRunner 构造器（便于测试注入）。
                约定签名：``(settings, hybrid_search, evaluator) -> EvalRunner``。
                若需要注入 response_builder，通过 ``response_builder_builder``
                单独提供，由本方法在构造后附加到 runner 上。
            response_builder_builder: 可选 ResponseBuilder 构造器。提供后将在
                RAGAS 模式下为 EvalRunner 挂接 LLM answer 生成能力。

        Returns:
            EvalReport: 评估报告对象。
        """
        if top_k <= 0:
            raise ValueError("top_k must be a positive integer")

        # 使用深拷贝避免污染全局 settings，保证页面多次运行可重复。
        effective_settings = copy.deepcopy(settings)
        effective_settings.evaluation.backends = self.resolve_backends(
            mode=mode,
            current_backends=effective_settings.evaluation.backends,
        )

        effective_evaluator_builder = evaluator_builder or (
            lambda cfg: EvaluatorFactory.create(settings=cfg)
        )
        hybrid_search = hybrid_search_builder(effective_settings)
        evaluator = effective_evaluator_builder(effective_settings)
        runner = runner_builder(
            effective_settings,
            hybrid_search,
            evaluator,
        )

        # 如启用了 ragas 且外部提供了 ResponseBuilder 构造器，则挂接。
        # 保持 runner_builder 签名向后兼容（只接 3 参），此处以属性方式追加。
        if (
            response_builder_builder is not None
            and "ragas" in [b.lower() for b in effective_settings.evaluation.backends]
        ):
            setattr(runner, "_response_builder", response_builder_builder(effective_settings))

        filters = {"collection": collection.strip()} if collection.strip() else None
        report = runner.run(
            test_set_path=test_set_path,
            top_k=top_k,
            filters=filters,
        )
        # 自动与当前基线对比，填充 delta 字段；CI/脚本可通过 compare_baseline=False 关闭
        if compare_baseline:
            report = self.compare_with_baseline(report)
        return report

    def append_history(self, entry: dict[str, Any]) -> None:
        """追加一条评估历史记录（与基线覆写串行，防止并发丢写）。"""
        self._history_file.parent.mkdir(parents=True, exist_ok=True)
        with self._file_lock():
            with self._history_file.open("a", encoding="utf-8") as file_obj:
                file_obj.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def load_history(self, limit: int = 50) -> list[dict[str, Any]]:
        """加载评估历史，按时间倒序返回。"""
        if not self._history_file.exists():
            return []

        records: list[dict[str, Any]] = []
        with self._history_file.open("r", encoding="utf-8") as file_obj:
            for line in file_obj:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    _logger.warning(
                        "skipping corrupted JSONL line in %s: %s", self._history_file, exc
                    )
                    continue

        records.sort(key=lambda item: item.get("timestamp", ""), reverse=True)
        return records[:limit]

    def build_history_entry(
        self,
        mode: str,
        test_set_path: str,
        top_k: int,
        collection: str,
        report: EvalReport,
    ) -> dict[str, Any]:
        """构建标准化历史记录。"""
        return {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "mode": mode.lower(),
            "test_set_path": test_set_path,
            "top_k": top_k,
            "collection": collection.strip(),
            "total_cases": report.total_cases,
            "hit_rate": report.hit_rate,
            "mrr": report.mrr,
            "source_hit_rate": report.source_hit_rate,
            "aggregate_metrics": report.aggregate_metrics,
        }

    # ------------------------------------------------------------------
    # 基线管理：标记/查询/对比
    # ------------------------------------------------------------------

    def mark_as_baseline(self, timestamp: str) -> bool:
        """将指定 timestamp 的历史记录标记为当前基线。

        同时清除其他所有记录的 ``is_baseline`` 标志，保证同一时刻只有一条基线。
        读取→修改→覆写的整个序列在文件锁保护下执行，避免与 ``append_history``
        并发产生丢写或读到半成品。

        Args:
            timestamp: 历史记录的 ISO 时间戳字符串。

        Returns:
            True 表示找到并标记成功，False 表示未找到对应记录。
        """
        with self._file_lock():
            records = self._read_all_history()
            found = False
            for record in records:
                if record.get("timestamp") == timestamp:
                    record["is_baseline"] = True
                    found = True
                else:
                    record.pop("is_baseline", None)

            if found:
                self._overwrite_history(records)
            else:
                _logger.warning(
                    "mark_as_baseline: no history entry found for timestamp=%s", timestamp
                )
        return found

    def get_baseline_entry(self) -> Optional[dict[str, Any]]:
        """返回当前标记为基线的历史记录，若不存在则返回 None。"""
        for record in self._read_all_history():
            if record.get("is_baseline"):
                return record
        return None

    def compare_with_baseline(
        self,
        current_report: EvalReport,
        baseline_entry: Optional[dict[str, Any]] = None,
    ) -> EvalReport:
        """将当前报告与基线记录对比，填充 delta 字段后返回。

        Args:
            current_report: 本次评估产出的 EvalReport。
            baseline_entry: 指定基线历史记录；若为 None 则自动调用
                            ``get_baseline_entry()`` 查找。

        Returns:
            填充了 ``delta_hit_rate``、``delta_mrr``、``delta_aggregate_metrics``
            和 ``baseline_id`` 字段的 EvalReport（无基线时原样返回）。
        """
        entry = baseline_entry if baseline_entry is not None else self.get_baseline_entry()
        if entry is None:
            return current_report

        baseline_agg: dict[str, float] = entry.get("aggregate_metrics") or {}
        delta_aggregate = {
            key: current_report.aggregate_metrics.get(key, 0.0) - float(baseline_agg.get(key, 0.0))
            for key in set(current_report.aggregate_metrics) | set(baseline_agg)
        }
        # 使用 dataclasses.replace 返回新副本，避免原地修改传入的 report，
        # 便于同一份 report 对比多个 baseline 时互不干扰。
        return dataclasses.replace(
            current_report,
            baseline_id=entry.get("timestamp", "unknown"),
            delta_hit_rate=current_report.hit_rate - float(entry.get("hit_rate", 0.0)),
            delta_mrr=current_report.mrr - float(entry.get("mrr", 0.0)),
            delta_aggregate_metrics=delta_aggregate,
        )

    # ------------------------------------------------------------------
    # 内部辅助方法
    # ------------------------------------------------------------------

    def _read_all_history(self) -> list[dict[str, Any]]:
        """读取全部 JSONL 历史记录，不做排序和截断。"""
        if not self._history_file.exists():
            return []
        records: list[dict[str, Any]] = []
        with self._history_file.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    _logger.warning(
                        "skipping corrupted JSONL line in %s: %s", self._history_file, exc
                    )
                    continue
        return records

    def _overwrite_history(self, records: list[dict[str, Any]]) -> None:
        """原子性地覆写 JSONL 文件（先写临时文件再重命名）。"""
        self._history_file.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._history_file.with_suffix(".jsonl.tmp")
        with tmp_path.open("w", encoding="utf-8") as fh:
            for record in records:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        tmp_path.replace(self._history_file)

    @contextmanager
    def _file_lock(self, timeout_seconds: float = 5.0) -> Iterator[None]:
        """跨进程文件锁（基于 O_EXCL 原子创建 .lock 文件）。

        保证 ``append_history`` 与 ``mark_as_baseline`` 不会在"读-改-写"窗口
        中被另一个写入者打断，避免丢失追加或基线标记被吞掉。

        Args:
            timeout_seconds: 获取锁的最长等待时间，超时抛 TimeoutError。
        """
        lock_path = self._history_file.with_suffix(".jsonl.lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + timeout_seconds
        while True:
            try:
                fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                break
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise TimeoutError(
                        f"could not acquire history lock {lock_path} within "
                        f"{timeout_seconds}s; stale lock file may need manual removal"
                    )
                time.sleep(0.05)
        try:
            yield
        finally:
            try:
                os.close(fd)
            except OSError:
                pass
            try:
                lock_path.unlink()
            except OSError:
                pass
