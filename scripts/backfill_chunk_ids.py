"""US2 chunk_id 回填 CLI (T022, refs FR-007 / contracts/cli_contracts.md § 4)。

精修后的金标 case 的 expected_chunk_ids 通常仍为空(由合成阶段留空)。本工具:
1. 用项目 EmbeddingFactory 把每条 case 的 ground_truth 编码为向量
2. 在指定 collection 中查 top-K 最相似 chunk
3. 过 --threshold 后回填 expected_chunk_ids(in-place 或 dry-run)

退出码:
    0 = 回填成功
    1 = 输入错误(文件 / collection 不存在)
    2 = 匹配率过低警告(< 90% 的 case 都没匹配到符合阈值的 chunk;退出但不写)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from src.core.settings import load_settings
from src.libs.embedding.embedding_factory import EmbeddingFactory
from src.libs.vector_store.vector_store_factory import VectorStoreFactory
from src.observability.logger import get_logger

logger = get_logger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill expected_chunk_ids via semantic match (US2 step 3)"
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Path to golden test set JSON (in-place updated unless --dry-run)",
    )
    parser.add_argument(
        "--collection",
        required=True,
        help="Vector store collection used for matching",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="How many top similar chunks to fetch per case (default 5)",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.6,
        help="Cosine similarity floor; chunks below this score are dropped (default 0.6)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the planned backfill without writing the file",
    )
    return parser.parse_args()


def _backfill_one(
    ground_truth: str,
    embedding_factory_instance: Any,
    vector_store: Any,
    collection: str,
    top_k: int,
    threshold: float,
) -> tuple[list[str], list[float]]:
    """Embed ground_truth + query vector store; return (chunk_ids_above_threshold, scores).

    Note: ``collection`` 参数当前被记录但实际查询走 ``settings.vector_store.collection_name``
    (BaseVectorStore.query 不接受 collection 重载)。CLI 调用方需保证 settings 已指向
    正确 collection,或在调用前临时改 settings。
    """
    if not ground_truth or not ground_truth.strip():
        return [], []
    vectors = embedding_factory_instance.embed([ground_truth])
    if not vectors:
        return [], []
    query_vec = vectors[0]
    # base_vector_store.query signature: query(vector, top_k, filters=None, trace=None)
    results = vector_store.query(
        vector=query_vec,
        top_k=top_k,
    )
    # results is List[Dict] with keys id/score/text/metadata (or similar);
    # normalize to id+score
    chunk_ids: list[str] = []
    scores: list[float] = []
    for r in results:
        if not isinstance(r, dict):
            continue
        score = float(r.get("score", 0.0))
        if score < threshold:
            continue
        cid = r.get("id") or r.get("chunk_id")
        if cid:
            chunk_ids.append(str(cid))
            scores.append(score)
    return chunk_ids, scores


def main() -> int:
    args = parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: input file not found: {input_path}", file=sys.stderr)
        return 1
    try:
        data = json.loads(input_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"Error: input not valid JSON: {exc}", file=sys.stderr)
        return 1
    cases = data.get("test_cases")
    if not isinstance(cases, list) or not cases:
        print("Error: input missing or empty 'test_cases'", file=sys.stderr)
        return 1

    try:
        settings = load_settings()
        embedding = EmbeddingFactory.create(settings=settings)
        vector_store = VectorStoreFactory.create(settings=settings)
    except Exception as exc:
        print(f"Error: failed to init factories: {exc}", file=sys.stderr)
        return 1

    matched_count = 0
    total = len(cases)
    for idx, case in enumerate(cases):
        ground_truth = case.get("ground_truth", "")
        try:
            chunk_ids, scores = _backfill_one(
                ground_truth=ground_truth,
                embedding_factory_instance=embedding,
                vector_store=vector_store,
                collection=args.collection,
                top_k=args.top_k,
                threshold=args.threshold,
            )
        except Exception as exc:
            logger.warning("backfill failed for case[%d]: %s", idx, exc)
            chunk_ids, scores = [], []

        if chunk_ids:
            matched_count += 1
        if args.dry_run:
            short_q = (case.get("query") or "")[:60]
            print(
                f"  [{idx + 1}/{total}] {short_q!r:<60s}  "
                f"matched {len(chunk_ids)} chunks "
                f"(scores: {[f'{s:.2f}' for s in scores]})"
            )
        # 实写:总是覆盖(精修后通常 expected_chunk_ids 为空)
        case["expected_chunk_ids"] = chunk_ids

    match_rate = matched_count / total if total else 0.0
    summary = (
        f"Backfilled {matched_count}/{total} cases ({match_rate:.1%}); "
        f"{total - matched_count} cases below threshold {args.threshold}"
    )

    if match_rate < 0.90:
        print(f"WARNING: {summary} (match rate < 90%; need manual review)", file=sys.stderr)
        if not args.dry_run:
            print(
                "Refusing to write file due to low match rate. "
                "Re-run with --dry-run to inspect, then manually adjust ground_truth or threshold.",
                file=sys.stderr,
            )
            return 2

    if not args.dry_run:
        input_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(summary + f" -> {input_path}")
    else:
        print(summary + " (dry-run; no file written)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
