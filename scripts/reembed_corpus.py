"""用当前配置的 embedding 模型重嵌语料 (Feature-004 追加)。

**为什么需要它**：2026-08-09 网关把 ``text-embedding-3-small`` 整体下架
（503 model_not_found），实测 Qwen 网关 embedding 类只剩
``qwen/text-embedding-v4``、GLM 官方端点零个 embedding 模型。新模型是
**1024 维**而库内现存 52,919 条向量是 **1536 维** —— 不同向量空间，dense
检索会以 ``Collection expecting embedding with dimension of 1536, got 1024``
报错（刻意不静默降级）。

要恢复 dense 检索，只能用新模型重嵌。**正文都在 Chroma 里，不需要原始文档**
（``ingest_source/`` 早已不存在）。

**写到新集合而非就地覆盖**：Chroma 集合的维度由首次写入固定，1024 维向量
写不进 1536 维集合。更重要的是原集合保持完整可回滚 —— 万一网关又把旧模型
放回来，旧向量立刻可用。

⚠️ **有真实 API 成本**。默认 ``--dry-run``，先看估算再决定。

Usage::

    python scripts/reembed_corpus.py --source default            # 估算，不调用 API
    python scripts/reembed_corpus.py --source default --limit 50 --execute   # 小规模试跑
    python scripts/reembed_corpus.py --source default --execute  # 全量

宪法原则一：本脚本**不 import chromadb**，全程经 ``VectorStoreFactory`` +
``BaseVectorStore`` 抽象访问。
"""

from __future__ import annotations

import argparse
import copy
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional

sys.path.insert(0, ".")

from src.core.settings import Settings, SettingsError, load_settings  # noqa: E402
from src.libs.embedding.embedding_factory import EmbeddingFactory  # noqa: E402
from src.libs.vector_store.base_vector_store import BaseVectorStore  # noqa: E402
from src.libs.vector_store.vector_store_factory import VectorStoreFactory  # noqa: E402
from src.observability.logger import get_logger  # noqa: E402

logger = get_logger(__name__)

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


@dataclass
class ReembedStats:
    """重嵌统计。"""

    source: str
    target: str
    model: str
    dimension: int
    batch_size: int
    scanned: int = 0
    skipped_empty: List[str] = field(default_factory=list)
    embedded: int = 0
    written: int = 0
    elapsed_s: float = 0.0

    @property
    def api_calls(self) -> int:
        """预计/实际的 API 调用次数（按批计）。"""
        if self.batch_size <= 0:
            return 0
        pending = self.scanned - len(self.skipped_empty)
        return (pending + self.batch_size - 1) // self.batch_size


def _store_for(settings: Settings, collection: str) -> BaseVectorStore:
    """构造指向指定集合的向量库实例。"""
    scoped = copy.deepcopy(settings)
    scoped.vector_store.collection_name = collection
    return VectorStoreFactory.create(scoped)


def _iter_batches(
    store: BaseVectorStore,
    batch_size: int,
    stats: ReembedStats,
    limit: Optional[int] = None,
) -> Iterator[List[Dict[str, Any]]]:
    """按 batch_size 从源集合读出待重嵌的记录。

    只取正文与元数据 —— 旧向量要被丢弃，读它纯属浪费带宽与内存。
    """
    batch: List[Dict[str, Any]] = []

    for record in store.iter_records(include_vectors=False, batch_size=1000):
        if limit is not None and stats.scanned >= limit:
            break
        stats.scanned += 1

        text = record.get("text") or ""
        if not text.strip():
            stats.skipped_empty.append(record["id"])
            continue

        batch.append(record)
        if len(batch) >= batch_size:
            yield batch
            batch = []

    if batch:
        yield batch


def reembed(
    settings: Settings,
    source: str,
    target: str,
    execute: bool,
    limit: Optional[int] = None,
) -> ReembedStats:
    """把源集合的正文用当前模型重嵌后写入目标集合。"""
    embedder = EmbeddingFactory.create(settings)
    batch_size = embedder.get_max_batch_size()

    stats = ReembedStats(
        source=source,
        target=target,
        model=embedder.get_model_name(),
        dimension=embedder.get_dimension(),
        batch_size=batch_size,
    )

    source_store = _store_for(settings, source)
    target_store = _store_for(settings, target) if execute else None

    started = time.perf_counter()
    for batch in _iter_batches(source_store, batch_size, stats, limit=limit):
        if not execute:
            continue

        vectors = embedder.embed([r["text"] for r in batch])
        stats.embedded += len(vectors)

        assert target_store is not None
        target_store.upsert(
            [
                {
                    "id": record["id"],
                    "vector": vector,
                    "text": record["text"],
                    "metadata": copy.deepcopy(record.get("metadata") or {}),
                }
                for record, vector in zip(batch, vectors)
            ]
        )
        stats.written += len(batch)
        logger.info("Re-embedded %d records into %r", stats.written, target)

    stats.elapsed_s = time.perf_counter() - started
    return stats


def _print_stats(stats: ReembedStats, execute: bool) -> None:
    print()
    print(f"源集合      : {stats.source}")
    print(f"目标集合    : {stats.target}")
    print(f"模型        : {stats.model}  ({stats.dimension} 维)")
    print(f"批大小      : {stats.batch_size}")
    print(f"扫描记录    : {stats.scanned:,}")
    if stats.skipped_empty:
        print(f"跳过（空文）: {len(stats.skipped_empty):,}")
    print(f"API 调用    : {stats.api_calls:,} 次（按批计）")

    if not execute:
        # 实测单次调用约 2 s，用它给个数量级估算
        est_s = stats.api_calls * 2.0
        print(f"预计耗时    : 约 {est_s / 60:.0f} 分钟（按单批 ~2s 估算，串行）")
        print()
        print("这是 --dry-run，未调用任何 API、未写入任何数据。")
        print("确认后加 --execute 实跑；建议先用 --limit 50 --execute 小规模验证。")
    else:
        print(f"已重嵌      : {stats.embedded:,}")
        print(f"已写入      : {stats.written:,}")
        print(f"实际耗时    : {stats.elapsed_s / 60:.1f} 分钟")
        print()
        print(f"下一步：把 settings.yaml 的 vector_store.collection_name 改为 "
              f"{stats.target!r}，然后跑")
        print(f"  python scripts/rebuild_bm25_index.py --collection {stats.target}")
        print("关键词索引必须一并重建 —— 它的 chunk 标识要与新集合对齐。")
    print()


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="用当前配置的 embedding 模型重嵌语料（写入新集合，不覆盖源数据）",
    )
    parser.add_argument("--source", default=None, help="源集合（默认取配置值）")
    parser.add_argument(
        "--target",
        default=None,
        help="目标集合（默认 <source>_<模型裸名>，例如 default_text-embedding-v4）",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="实际调用 API 并写入。**不加则只做估算**",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="只处理前 N 条（小规模试跑用）",
    )
    parser.add_argument("--config", default="config/settings.yaml")
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
    model_slug = settings.embedding.model.split("/")[-1]
    target = args.target or f"{source}_{model_slug}"

    if target == source:
        print(
            "Error: 目标集合不能与源集合同名 —— Chroma 集合维度由首次写入固定，"
            "1024 维向量写不进 1536 维集合。",
            file=sys.stderr,
        )
        return 1

    try:
        stats = reembed(settings, source, target, execute=args.execute, limit=args.limit)
    except Exception as exc:  # noqa: BLE001 — 顶层 CLI 边界
        logger.error("Re-embedding failed: %s", exc)
        print(f"Error: 重嵌失败: {exc}", file=sys.stderr)
        print("源集合未被修改，可安全重跑。", file=sys.stderr)
        return 1

    _print_stats(stats, args.execute)
    return 0


if __name__ == "__main__":
    sys.exit(main())
