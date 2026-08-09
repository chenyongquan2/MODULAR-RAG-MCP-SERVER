"""集合物理隔离迁移 (Feature-004 T008/T009)。

把混在一个物理 collection 里、靠 ``metadata.collection`` 区分的记录，
按标记复制到各自的物理 collection，使**向量侧与关键词侧的隔离口径一致**。

背景（缺陷 D2）：``vector_upserter.py`` 的 ``upsert()`` 从不传 collection，
向量全部写入 ``settings.vector_store.collection_name`` 指向的那一个物理
集合；而 ``pipeline.py`` 的关键词索引是**按 collection 分文件存**的。于是
``--collection`` 参数在两侧语义完全不同 —— 关键词侧是物理隔离，向量侧只是
给 chunk 打了个元数据标签。后果是指定集合时向量侧搜全量、关键词侧只搜其中
一小部分，两路语料范围可以相差几个数量级。

**复制语义，不删源数据**：源集合在人工确认前保持完整可回滚（FR-006）。
磁盘可用空间远大于数据量，复制成本可忽略。

**不重新生成向量**：向量随记录一起复制（SC-005）。

Usage::

    python scripts/migrate_collections.py --dry-run
    python scripts/migrate_collections.py
    python scripts/migrate_collections.py --source default --only mt5_docs_english

宪法原则一：本脚本**不 import chromadb**，全程经 ``VectorStoreFactory`` +
``BaseVectorStore`` 抽象访问（由 tests/unit/test_vector_store_contract.py
的守卫测试强制）。
"""

from __future__ import annotations

import argparse
import copy
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Iterator, List, Optional

sys.path.insert(0, ".")

from src.core.settings import Settings, SettingsError, load_settings  # noqa: E402
from src.libs.vector_store.base_vector_store import BaseVectorStore  # noqa: E402
from src.libs.vector_store.vector_store_factory import VectorStoreFactory  # noqa: E402
from src.observability.logger import get_logger  # noqa: E402

logger = get_logger(__name__)

# Windows 默认 stdout 用 GBK 编码,遇到非 ASCII 字符(中文 / 警示符号)会炸。
# 强制 UTF-8,与 scripts/refine_testset.py 的既有做法一致。
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

#: 判定「源路径指向临时目录」的模式。
#:
#: 实测 10 条残留形如 ``C:\\Users\\...\\AppData\\Local\\Temp\\tmpg0csbti9.md_0_xxx``，
#: 它们的 ``metadata.collection`` **并非缺失**（都标着 ``default``），因此不能靠
#: 元数据缺失来识别 —— 必须看源路径。
_TEMP_PATH_PATTERN = re.compile(r"(?:[\\/]Temp[\\/]|[\\/]tmp[\\/]|[\\/]tmp[a-z0-9_]{6,}\.)", re.IGNORECASE)

#: 迁移时单批 upsert 的记录数
_UPSERT_BATCH = 500


@dataclass
class MigrationPlan:
    """一次迁移的计划与统计。"""

    source: str
    #: 目标集合名 → 待迁移记录数
    groups: Dict[str, int] = field(default_factory=dict)
    #: 源路径指向临时目录的记录（可疑数据，不自动删除）
    temp_residue: List[str] = field(default_factory=list)
    #: ``metadata.collection`` 缺失或为空的记录（防御性检查）
    unlabeled: List[str] = field(default_factory=list)
    total_scanned: int = 0

    def targets(self, exclude_source: bool = True) -> List[str]:
        """需要实际写入的目标集合（默认排除与源同名的那个）。"""
        return sorted(
            name
            for name in self.groups
            if not (exclude_source and name == self.source)
        )


def scan_source(store: BaseVectorStore, source: str) -> MigrationPlan:
    """扫描源集合，产出迁移计划。

    Args:
        store: 指向源集合的向量库实例。
        source: 源集合名（用于判断哪些分组无需迁移）。

    Returns:
        MigrationPlan：分组计数 + 可疑数据清单。
    """
    plan = MigrationPlan(source=source)
    counter: Counter[str] = Counter()

    for record in store.iter_records(include_vectors=False, batch_size=1000):
        plan.total_scanned += 1
        record_id = record["id"]
        label = (record.get("metadata") or {}).get("collection")

        if not label:
            plan.unlabeled.append(record_id)
            continue

        counter[str(label)] += 1

        if _TEMP_PATH_PATTERN.search(record_id):
            plan.temp_residue.append(record_id)

    plan.groups = dict(counter)
    return plan


def _store_for(settings: Settings, collection: str) -> BaseVectorStore:
    """构造指向指定集合的向量库实例。

    ``ChromaStore`` 在 ``__init__`` 时绑定 ``settings.vector_store.collection_name``，
    因此切换集合的办法是用改过该字段的 settings 副本重新构造实例 ——
    这样既不需要给 ``upsert`` 增加 collection 参数，也不触碰 provider 实现。
    """
    scoped = copy.deepcopy(settings)
    scoped.vector_store.collection_name = collection
    return VectorStoreFactory.create(scoped)


def migrate(
    settings: Settings,
    source_store: BaseVectorStore,
    targets: Iterable[str],
    batch_size: int = _UPSERT_BATCH,
) -> Dict[str, int]:
    """单遍扫描源集合，把各分组的记录分发到各自的物理集合。

    **刻意做成单遍**：``include_vectors=True`` 时每条记录带 1536 维向量，
    按目标集合逐个扫描会把 5 万条向量重复读 N 遍。单遍扫描 + 按标记分发
    只读一次。

    向量随记录一起复制，不重新生成 —— 重新 embedding 有真实 API 成本
    （SC-005）。

    Args:
        settings: 全局配置（用于构造目标集合的 store 实例）。
        source_store: 指向源集合的向量库实例。
        targets: 需要写出的目标集合名集合。
        batch_size: 单次 upsert 的记录数。

    Returns:
        目标集合名 → 实际写入条数。
    """
    wanted = set(targets)
    if not wanted:
        return {}

    stores = {label: _store_for(settings, label) for label in wanted}
    buffers: Dict[str, List[Dict[str, Any]]] = {label: [] for label in wanted}
    written: Dict[str, int] = {label: 0 for label in wanted}

    def flush(label: str) -> None:
        batch = buffers[label]
        if not batch:
            return
        stores[label].upsert(batch)
        written[label] += len(batch)
        buffers[label] = []
        logger.info("Migrated %d records into collection %r", written[label], label)

    for record in source_store.iter_records(include_vectors=True, batch_size=batch_size):
        metadata = record.get("metadata") or {}
        label = str(metadata.get("collection") or "")
        if label not in wanted:
            continue

        buffers[label].append(
            {
                "id": record["id"],
                "vector": record.get("vector") or [],
                "text": record.get("text", ""),
                # 深拷贝，避免下游 upsert 就地改写影响源数据
                "metadata": copy.deepcopy(metadata),
            }
        )

        if len(buffers[label]) >= batch_size:
            flush(label)

    for label in wanted:
        flush(label)

    return written


def _print_plan(plan: MigrationPlan, only: Optional[str]) -> None:
    """打印迁移计划（人类可读输出，按宪法只在 scripts/ 中出现）。"""
    print(f"\n源集合: {plan.source}    扫描记录数: {plan.total_scanned:,}\n")
    print(f"{'metadata.collection':28s} {'记录数':>10s}  动作")
    print("-" * 60)

    for label in sorted(plan.groups, key=lambda k: -plan.groups[k]):
        count = plan.groups[label]
        if label == plan.source:
            action = "留在原地（与源同名）"
        elif only and label != only:
            action = "跳过（--only 未选中）"
        else:
            action = f"→ 复制到物理集合 {label!r}"
        print(f"{label:28s} {count:>10,}  {action}")

    print("-" * 60)

    if plan.temp_residue:
        print(f"\n⚠ 源路径指向临时目录的记录: {len(plan.temp_residue)} 条")
        print("  这些是历史 ingest 残留，源文件已不存在。**本脚本不会删除它们**，")
        print("  需人工确认后单独处理（对应 tasks.md 的 T041）：")
        for record_id in plan.temp_residue[:10]:
            print(f"    - {record_id}")
        if len(plan.temp_residue) > 10:
            print(f"    ... 另有 {len(plan.temp_residue) - 10} 条")

    if plan.unlabeled:
        print(f"\n⚠ metadata.collection 缺失或为空: {len(plan.unlabeled)} 条（不会被迁移）")
        for record_id in plan.unlabeled[:10]:
            print(f"    - {record_id}")

    print()


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="按 metadata.collection 把记录复制到各自的物理集合（复制式，不删源数据）",
    )
    parser.add_argument(
        "--source",
        default=None,
        help="源集合名（默认取 settings.vector_store.collection_name）",
    )
    parser.add_argument(
        "--only",
        default=None,
        help="只迁移这一个目标集合（默认迁移全部分组）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印迁移计划，不写入任何数据",
    )
    parser.add_argument(
        "--config",
        default="config/settings.yaml",
        help="配置文件路径",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)

    try:
        settings = load_settings(args.config)
    except SettingsError as exc:
        logger.error("Failed to load settings: %s", exc)
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    source = args.source or settings.vector_store.collection_name
    logger.info("Scanning source collection %r", source)

    try:
        source_store = _store_for(settings, source)
        plan = scan_source(source_store, source)
    except Exception as exc:  # noqa: BLE001 — 顶层 CLI 边界
        logger.error("Failed to scan source collection: %s", exc)
        print(f"Error: 扫描源集合失败: {exc}", file=sys.stderr)
        return 1

    _print_plan(plan, args.only)

    if args.dry_run:
        print("--dry-run 已指定，未写入任何数据。")
        return 0

    targets = plan.targets()
    if args.only:
        if args.only not in plan.groups:
            print(f"Error: --only {args.only!r} 不在源集合的分组中", file=sys.stderr)
            return 1
        targets = [args.only] if args.only != source else []

    if not targets:
        print("没有需要迁移的分组。")
        return 0

    logger.info("Migrating %d group(s) in a single pass: %s", len(targets), targets)
    try:
        written = migrate(settings, source_store, targets)
    except Exception as exc:  # noqa: BLE001 — 顶层 CLI 边界
        logger.error("Migration failed: %s", exc)
        print(f"Error: 迁移失败: {exc}", file=sys.stderr)
        print("源集合未被修改，可安全重跑。", file=sys.stderr)
        return 1

    for label in sorted(written):
        print(f"✔ {label}: 已复制 {written[label]:,} 条")

    print(
        f"\n完成。共复制 {sum(written.values()):,} 条；"
        f"源集合 {source!r} 保持完整，可随时回滚。"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
