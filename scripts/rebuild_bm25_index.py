"""从向量库反向重建关键词索引 (Feature-004 T018/T019)。

修复缺陷 D1：关键词索引与向量库的 chunk 标识体系不相交。

**问题有多严重**：抽 200 个关键词索引里的标识去向量库查，命中 **0/200**。
两套标识分别是 ``doc_<hash>_<idx>_<hash>`` 与 ``ingest_source`` 绝对路径式，
来自不同批次的 ingest、不同版本的代码。后果是：

1. ``fusion.py`` 按 chunk_id 合并两路结果 —— 标识不相交，**融合从未真正发生**
2. ``sparse_retriever.py`` 拿关键词命中的标识去向量库取正文 —— 取不到，返回空
3. 于是「混合检索」实际一直是**纯向量检索**

**为什么只能反向重建**：``ingest_source/`` 原始文档目录已不存在，且向量生成
走 API 有真实成本。所幸向量库自身同时持有正文与正确标识（实测正文合计
仅 20 MB / 52,919 条），反向重建在数据上完全可行且零 embedding 调用。

复用既有组件，不另造轮子::

    向量库 iter_records → Chunk → SparseEncoder.encode()
        → ChunkRecord(sparse_vector) → 按 metadata.collection 分组
        → BM25Indexer.build() + save()

Usage::

    python scripts/rebuild_bm25_index.py --inspect-only
    python scripts/rebuild_bm25_index.py --collection mt5_docs_english
    python scripts/rebuild_bm25_index.py --all

宪法原则一：本脚本**不 import chromadb**，全程经 ``VectorStoreFactory`` +
``BaseVectorStore`` 抽象访问。
"""

from __future__ import annotations

import argparse
import copy
import json
import random
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

sys.path.insert(0, ".")

from src.core.settings import Settings, SettingsError, load_settings  # noqa: E402
from src.core.types import Chunk  # noqa: E402
from src.ingestion.embedding.sparse_encoder import SparseEncoder  # noqa: E402
from src.ingestion.storage.bm25_indexer import BM25Indexer  # noqa: E402
from src.libs.vector_store.base_vector_store import BaseVectorStore  # noqa: E402
from src.libs.vector_store.vector_store_factory import VectorStoreFactory  # noqa: E402
from src.observability.logger import get_logger  # noqa: E402

logger = get_logger(__name__)

# Windows 默认 stdout 用 GBK，中文与符号会炸。与其他 scripts 做法一致。
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

#: CJK 统一表意文字区间，用于统计「含中文词条占比」（SC-003）
_CJK_PATTERN = re.compile(r"[一-鿿]")

#: 标识回查向量库时的抽样条数（FR-001 的可执行判据）
_ID_VERIFY_SAMPLE = 200


@dataclass
class CollectionStats:
    """单个集合的重建统计（FR-013）。"""

    collection: str
    chunk_count: int = 0
    skipped_empty_text: List[str] = field(default_factory=list)
    term_count: int = 0
    cjk_term_count: int = 0
    index_path: Optional[Path] = None
    index_bytes: int = 0
    id_verify_sampled: int = 0
    id_verify_hit: int = 0

    @property
    def cjk_ratio(self) -> float:
        return self.cjk_term_count / self.term_count if self.term_count else 0.0

    @property
    def id_hit_rate(self) -> float:
        return self.id_verify_hit / self.id_verify_sampled if self.id_verify_sampled else 0.0


def _store_for(settings: Settings, collection: str) -> BaseVectorStore:
    """构造指向指定集合的向量库实例。

    ``ChromaStore`` 在 ``__init__`` 时绑定 ``collection_name``，因此切换集合
    的办法是用改过该字段的 settings 副本重新构造实例。
    """
    scoped = copy.deepcopy(settings)
    scoped.vector_store.collection_name = collection
    return VectorStoreFactory.create(scoped)


def _load_chunks(store: BaseVectorStore, stats: CollectionStats) -> List[Chunk]:
    """从向量库读出全部记录并转成 ``Chunk``。

    **关键点**：``Chunk.id`` 直接用向量库的记录标识 —— 这正是 D1 的修复所在。
    重建出的索引因此天生与向量库同源，两路结果得以正确合并。
    """
    chunks: List[Chunk] = []

    for record in store.iter_records(include_vectors=False, batch_size=1000):
        text = record.get("text") or ""
        if not text.strip():
            # 正文为空的记录建不了倒排，跳过并计入报告而非中断重建
            stats.skipped_empty_text.append(record["id"])
            continue

        chunks.append(
            Chunk(
                id=record["id"],
                text=text,
                metadata=dict(record.get("metadata") or {}),
                source_ref=(record.get("metadata") or {}).get("doc_id"),
            )
        )

    stats.chunk_count = len(chunks)
    return chunks


def _verify_ids_against_store(
    store: BaseVectorStore,
    chunk_ids: Sequence[str],
    stats: CollectionStats,
    sample_size: int = _ID_VERIFY_SAMPLE,
) -> None:
    """抽样回查：索引里的标识必须能在向量库中取回（FR-001 的可执行判据）。

    这是本 feature 最核心的验收项。修复前该命中率为 **0/200**。
    """
    if not chunk_ids:
        return

    rng = random.Random(42)  # 固定种子，报告可复现
    sample = rng.sample(list(chunk_ids), min(sample_size, len(chunk_ids)))

    found = store.get_by_ids(sample)
    found_ids = {record["id"] for record in found}

    stats.id_verify_sampled = len(sample)
    stats.id_verify_hit = sum(1 for cid in sample if cid in found_ids)


def rebuild_collection(
    settings: Settings,
    collection: str,
) -> CollectionStats:
    """重建单个集合的关键词索引。"""
    stats = CollectionStats(collection=collection)
    store = _store_for(settings, collection)

    logger.info("Reading records from collection %r", collection)
    chunks = _load_chunks(store, stats)

    if not chunks:
        logger.warning("Collection %r has no usable records; index not written", collection)
        return stats

    logger.info("Encoding %d chunks with the shared tokenizer", len(chunks))
    encoder = SparseEncoder()
    records = encoder.encode(chunks)

    indexer = BM25Indexer(
        index_dir=settings.vector_store.bm25_index_path,
        format_version=settings.vector_store.bm25_index_format_version,
    )
    indexer.build(records, collection=collection)
    index_path = indexer.save(collection=collection)

    stats.index_path = index_path
    stats.index_bytes = index_path.stat().st_size
    stats.term_count = len(indexer._index)
    stats.cjk_term_count = sum(1 for term in indexer._index if _CJK_PATTERN.search(term))

    _verify_ids_against_store(store, list(indexer._doc_lengths.keys()), stats)

    return stats


def inspect_collection(settings: Settings, collection: str) -> Dict[str, Any]:
    """只读检查当前索引状态，不做任何写入。"""
    index_path = Path(settings.vector_store.bm25_index_path) / f"{collection}.json"
    info: Dict[str, Any] = {"collection": collection, "exists": index_path.exists()}

    if not index_path.exists():
        return info

    info["bytes"] = index_path.stat().st_size
    try:
        raw = json.loads(index_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        info["error"] = f"无法解析: {exc}"
        return info

    terms = list(raw.get("index", {}))
    info["format_version"] = raw.get("_format_version", "(缺失 → v1)")
    info["term_count"] = len(terms)
    info["cjk_term_count"] = sum(1 for term in terms if _CJK_PATTERN.search(term))
    info["total_documents"] = raw.get("total_documents", 0)
    return info


def _print_inspection(infos: List[Dict[str, Any]]) -> None:
    print(f"\n{'集合':24s} {'格式':>10s} {'词条数':>9s} {'含中文':>8s} {'占比':>7s} {'体积':>9s}")
    print("-" * 74)
    for info in infos:
        if not info["exists"]:
            print(f"{info['collection']:24s} {'(无索引)':>10s}")
            continue
        if "error" in info:
            print(f"{info['collection']:24s} {info['error']}")
            continue
        total = info["term_count"]
        cjk = info["cjk_term_count"]
        ratio = cjk / total if total else 0.0
        mb = info["bytes"] / 1024 / 1024
        print(
            f"{info['collection']:24s} {str(info['format_version']):>10s} "
            f"{total:>9,} {cjk:>8,} {ratio:>6.1%} {mb:>8.1f}M"
        )
    print("-" * 74)
    print()


def _print_stats(all_stats: List[CollectionStats]) -> None:
    """重建统计报告（FR-013 / SC-010）。"""
    print(f"\n{'集合':24s} {'chunk':>8s} {'词条数':>9s} {'含中文':>8s} {'占比':>7s} "
          f"{'标识命中':>9s} {'体积':>9s}")
    print("-" * 84)

    for stats in all_stats:
        if not stats.index_path:
            print(f"{stats.collection:24s} {'(无可用记录，未写出索引)':>20s}")
            continue
        print(
            f"{stats.collection:24s} {stats.chunk_count:>8,} {stats.term_count:>9,} "
            f"{stats.cjk_term_count:>8,} {stats.cjk_ratio:>6.1%} "
            f"{stats.id_verify_hit:>4}/{stats.id_verify_sampled:<4} "
            f"{stats.index_bytes / 1024 / 1024:>8.1f}M"
        )

    print("-" * 84)

    for stats in all_stats:
        if stats.skipped_empty_text:
            print(f"\n⚠ {stats.collection}: 跳过 {len(stats.skipped_empty_text)} 条正文为空的记录")
            for cid in stats.skipped_empty_text[:5]:
                print(f"    - {cid}")
            if len(stats.skipped_empty_text) > 5:
                print(f"    ... 另有 {len(stats.skipped_empty_text) - 5} 条")

    print("\n验收要点：")
    for stats in all_stats:
        if not stats.index_path:
            continue
        ok_id = stats.id_hit_rate == 1.0
        mark = "✔" if ok_id else "✘"
        print(
            f"  {mark} {stats.collection}: 标识回查命中率 {stats.id_hit_rate:.1%}"
            f"（FR-001 要求 100%；修复前实测 0/200）"
        )
    print()


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="从向量库反向重建关键词索引（零 embedding 调用）",
    )
    parser.add_argument(
        "--collection",
        action="append",
        default=None,
        help="要重建的集合（可重复指定；默认取 settings.vector_store.collection_name）",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="重建所有已知集合（依据现有索引文件与向量库集合名）",
    )
    parser.add_argument(
        "--inspect-only",
        action="store_true",
        help="只报告当前索引状态，不做任何写入",
    )
    parser.add_argument(
        "--config",
        default="config/settings.yaml",
        help="配置文件路径",
    )
    return parser.parse_args(argv)


def _resolve_collections(args: argparse.Namespace, settings: Settings) -> List[str]:
    if args.collection:
        return list(dict.fromkeys(args.collection))
    if args.all:
        index_dir = Path(settings.vector_store.bm25_index_path)
        names = sorted(p.stem for p in index_dir.glob("*.json")) if index_dir.exists() else []
        return names or [settings.vector_store.collection_name]
    return [settings.vector_store.collection_name]


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)

    try:
        settings = load_settings(args.config)
    except SettingsError as exc:
        logger.error("Failed to load settings: %s", exc)
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    collections = _resolve_collections(args, settings)

    if args.inspect_only:
        _print_inspection([inspect_collection(settings, c) for c in collections])
        return 0

    all_stats: List[CollectionStats] = []
    for collection in collections:
        try:
            logger.info("Rebuilding index for collection %r", collection)
            all_stats.append(rebuild_collection(settings, collection))
        except Exception as exc:  # noqa: BLE001 — 顶层 CLI 边界
            logger.error("Rebuild failed for %r: %s", collection, exc)
            print(f"Error: 重建 {collection!r} 失败: {exc}", file=sys.stderr)
            print("既有索引未被破坏（原子替换），可安全重跑。", file=sys.stderr)
            return 1

    _print_stats(all_stats)
    return 0


if __name__ == "__main__":
    sys.exit(main())
