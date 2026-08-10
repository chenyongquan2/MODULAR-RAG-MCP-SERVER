"""融合权重校准 (Feature-005 T017-T019/T024)。

**为什么需要校准**：Feature-004 实测发现等权融合在英文金标上 recall 42.4%
**低于**纯语义检索的 45.7%、hit_rate 61.9% 低于 69.0%，而 MRR 0.502 高于
0.437。根因是 RRF 对两路一视同仁 —— 关键词路径的噪音命中挤掉了语义路径的
正确结果。本脚本扫出一组消除该倒退的权重。

**核心设计：一次检索、多次离线重放。**

权重**只影响融合，不影响检索** —— 两路各自的召回结果与权重完全无关。因此：

1. ``--build-cache``：每条查询只执行**一次**两路检索，把两路的有序标识列表
   缓存到 JSON
2. ``--sweep`` / ``--compare``：纯粹在缓存上重放融合，**零 API 调用**

对比：

================================  ==========  ==============
方式                              检索次数    embedding 调用
================================  ==========  ==============
朴素扫描（8 组权重 × 48 条金标）  384         384
缓存重放                          **48**      **48**
================================  ==========  ==============

Feature-004 期间反复遭遇网关 503 与超时，长批量任务极易夭折 —— 把 API 调用
集中在第一步且只做一遍，是校准能跑完的前提。附带好处是缓存本身即校准记录，
第三方拿到它无需 API 即可复算（FR-010）。

Usage::

    python scripts/calibrate_fusion_weights.py --build-cache --lang en
    python scripts/calibrate_fusion_weights.py --sweep --lang en
    python scripts/calibrate_fusion_weights.py --compare --lang en --recommended 0.25
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

sys.path.insert(0, ".")

from src.core.query_engine.fusion import Fusion  # noqa: E402
from src.core.settings import Settings, SettingsError, load_settings  # noqa: E402
from src.core.types import RetrievalResult  # noqa: E402
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

#: 缓存格式版本。结构变更须 bump，加载时不匹配即报错而非静默重放。
CACHE_FORMAT_VERSION = 1

#: 候选 sparse 权重。dense 固定 1.0 —— 权重只有相对比例有意义，
#: 因此一维扫描已覆盖全部有意义的配置（见 data-model.md § 2）。
DEFAULT_SPARSE_CANDIDATES = (0.0, 0.1, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0)

#: 缓存默认目录
CACHE_DIR = Path("logs/fusion_calibration")


# ---------------------------------------------------------------------------
# 指标
# ---------------------------------------------------------------------------


def _dcg(gains: Sequence[float]) -> float:
    return sum(g / math.log2(i + 2) for i, g in enumerate(gains))


@dataclass
class Metrics:
    """一组检索结果在金标上的四项指标。"""

    n: int = 0
    hit_rate: float = 0.0
    recall: float = 0.0
    mrr: float = 0.0
    ndcg: float = 0.0

    def as_row(self) -> str:
        return (
            f"hit={self.hit_rate:6.1%}  recall={self.recall:6.1%}  "
            f"MRR={self.mrr:.4f}  nDCG={self.ndcg:.4f}"
        )


def score_ranking(ranked_ids: Sequence[str], expected: Sequence[str]) -> Dict[str, float]:
    """算单条 case 的四项指标。

    Args:
        ranked_ids: 融合后的有序标识列表。
        expected: 金标期望标识。

    Returns:
        含 ``hit`` / ``recall`` / ``rr`` / ``ndcg`` 的字典。
    """
    expected_set = set(expected)
    if not expected_set:
        return {"hit": 0.0, "recall": 0.0, "rr": 0.0, "ndcg": 0.0}

    overlap = expected_set.intersection(ranked_ids)
    rr = next(
        (1.0 / (i + 1) for i, cid in enumerate(ranked_ids) if cid in expected_set),
        0.0,
    )
    gains = [1.0 if cid in expected_set else 0.0 for cid in ranked_ids]
    ideal = [1.0] * min(len(expected_set), len(ranked_ids))

    return {
        "hit": 1.0 if overlap else 0.0,
        "recall": len(overlap) / len(expected_set),
        "rr": rr,
        "ndcg": (_dcg(gains) / _dcg(ideal)) if ideal else 0.0,
    }


# ---------------------------------------------------------------------------
# 缓存
# ---------------------------------------------------------------------------


@dataclass
class CachedCase:
    query: str
    expected_chunk_ids: List[str]
    difficulty: str
    routes: Dict[str, List[str]] = field(default_factory=dict)


@dataclass
class Cache:
    collection: str
    lang: str
    cases: List[CachedCase]

    def to_json(self) -> Dict[str, Any]:
        return {
            "_format_version": CACHE_FORMAT_VERSION,
            "collection": self.collection,
            "lang": self.lang,
            "cases": [
                {
                    "query": c.query,
                    "expected_chunk_ids": c.expected_chunk_ids,
                    "difficulty": c.difficulty,
                    "routes": c.routes,
                }
                for c in self.cases
            ],
        }

    @classmethod
    def from_json(cls, data: Dict[str, Any], expected_collection: str) -> "Cache":
        version = data.get("_format_version")
        if version != CACHE_FORMAT_VERSION:
            raise ValueError(
                f"Unsupported cache format: found _format_version={version!r}, "
                f"expected {CACHE_FORMAT_VERSION}. Re-run --build-cache."
            )

        collection = data.get("collection", "")
        if collection != expected_collection:
            raise ValueError(
                f"Cache was built on collection {collection!r} but current config "
                f"points at {expected_collection!r}. Retrieval results are not "
                "comparable across collections — re-run --build-cache."
            )

        return cls(
            collection=collection,
            lang=data.get("lang", ""),
            cases=[
                CachedCase(
                    query=c["query"],
                    expected_chunk_ids=list(c.get("expected_chunk_ids") or []),
                    difficulty=str(c.get("difficulty", "")),
                    routes={k: list(v) for k, v in (c.get("routes") or {}).items()},
                )
                for c in data.get("cases", [])
            ],
        )


def cache_path(lang: str) -> Path:
    return CACHE_DIR / f"routes_{lang}.json"


def build_cache(settings: Settings, lang: str, top_k: int) -> Cache:
    """对金标每条查询执行**一次**两路检索并缓存有序标识列表。

    这是全流程中唯一有 API 成本的步骤。
    """
    from src.core.query_engine.dense_retriever import DenseRetriever
    from src.core.query_engine.query_processor import QueryProcessor
    from src.core.query_engine.sparse_retriever import SparseRetriever

    golden_path = (settings.evaluation.golden_test_sets_by_lang or {}).get(lang)
    if not golden_path:
        raise ValueError(f"No golden test set configured for lang={lang!r}")

    cases_raw = json.loads(Path(golden_path).read_text(encoding="utf-8"))["test_cases"]

    processor = QueryProcessor()
    dense = DenseRetriever(settings)
    sparse = SparseRetriever(settings=settings)

    cached: List[CachedCase] = []
    for index, case in enumerate(cases_raw, start=1):
        query = case["query"]
        processed = processor.process(query)

        dense_ids = [r.chunk_id for r in dense.retrieve(query, top_k=top_k)]
        sparse_ids = [r.chunk_id for r in sparse.retrieve(processed.keywords, top_k=top_k)]

        cached.append(
            CachedCase(
                query=query,
                expected_chunk_ids=list(case.get("expected_chunk_ids") or []),
                difficulty=str((case.get("tags") or {}).get("difficulty", "")),
                routes={"dense": dense_ids, "sparse": sparse_ids},
            )
        )
        logger.info("Cached %d/%d: dense=%d sparse=%d", index, len(cases_raw),
                    len(dense_ids), len(sparse_ids))

    return Cache(
        collection=settings.vector_store.collection_name,
        lang=lang,
        cases=cached,
    )


# ---------------------------------------------------------------------------
# 离线重放
# ---------------------------------------------------------------------------


def replay(cache: Cache, weights: Dict[str, float], k: int, top_k: int) -> Metrics:
    """在缓存上重放融合并算聚合指标。**零 API 调用。**

    构造真实的 ``Fusion`` 而非另写一份打分逻辑 —— 否则校准结论与生产行为
    可能漂移，而这种漂移是静默的。
    """
    fusion = Fusion(k=k, weights=weights)

    totals = {"hit": 0.0, "recall": 0.0, "rr": 0.0, "ndcg": 0.0}
    for case in cache.cases:
        routes = {
            name: [
                RetrievalResult(chunk_id=cid, score=0.0, text="", metadata={})
                for cid in ids
            ]
            for name, ids in case.routes.items()
        }
        ranked = [r.chunk_id for r in fusion.fuse(routes, top_k=top_k)]
        for key, value in score_ranking(ranked, case.expected_chunk_ids).items():
            totals[key] += value

    n = len(cache.cases) or 1
    return Metrics(
        n=len(cache.cases),
        hit_rate=totals["hit"] / n,
        recall=totals["recall"] / n,
        mrr=totals["rr"] / n,
        ndcg=totals["ndcg"] / n,
    )


@dataclass
class SweepOutcome:
    """扫描结果与选择过程（判据须显式可见，不做隐式选择）。"""

    rows: List[tuple]  # (sparse_weight, Metrics)
    dense_only: Metrics
    recommended: Optional[float]
    satisfied_hard_constraint: bool
    reason: str


def select_recommended(
    rows: Sequence[tuple],
    dense_only: Metrics,
) -> SweepOutcome:
    """按 research.md Decision 6 的判据选推荐权重。

    1. **硬约束**：recall ≥ 纯语义的 recall（消除倒退是本 feature 的理由）
    2. 满足者中取 MRR 最大
    3. 无人满足则取 recall 最大，并标注未达成
    """
    # sparse=0 等价于纯语义，本身不构成「混合」，排除出候选
    candidates = [(w, m) for w, m in rows if w > 0]

    qualified = [(w, m) for w, m in candidates if m.recall >= dense_only.recall]

    if qualified:
        best_w, best_m = max(qualified, key=lambda item: item[1].mrr)
        return SweepOutcome(
            rows=list(rows),
            dense_only=dense_only,
            recommended=best_w,
            satisfied_hard_constraint=True,
            reason=(
                f"{len(qualified)}/{len(candidates)} 个候选满足硬约束 "
                f"recall >= {dense_only.recall:.1%}；其中 MRR 最高者为 "
                f"sparse={best_w}（MRR={best_m.mrr:.4f}）"
            ),
        )

    if not candidates:
        return SweepOutcome(list(rows), dense_only, None, False, "无有效候选")

    best_w, best_m = max(candidates, key=lambda item: item[1].recall)
    return SweepOutcome(
        rows=list(rows),
        dense_only=dense_only,
        recommended=best_w,
        satisfied_hard_constraint=False,
        reason=(
            f"**无候选满足硬约束** recall >= {dense_only.recall:.1%}。"
            f"退化为取 recall 最大者 sparse={best_w}（recall={best_m.recall:.1%}）。"
            "这意味着在当前语料上关键词路径对召回的贡献为负 —— "
            "spec Assumptions 已预先承认这种可能"
        ),
    )


def sweep(cache: Cache, k: int, top_k: int,
          candidates: Sequence[float] = DEFAULT_SPARSE_CANDIDATES) -> SweepOutcome:
    """扫描候选权重。dense 固定 1.0，只扫 sparse（只有相对比例有意义）。"""
    rows = [
        (w, replay(cache, {"dense": 1.0, "sparse": w}, k=k, top_k=top_k))
        for w in candidates
    ]
    dense_only = replay(cache, {"dense": 1.0, "sparse": 0.0}, k=k, top_k=top_k)
    return select_recommended(rows, dense_only)


# ---------------------------------------------------------------------------
# 输出
# ---------------------------------------------------------------------------


def _print_sweep(outcome: SweepOutcome, lang: str, k: int) -> None:
    print(f"\n=== 权重扫描 lang={lang} rrf_k={k} n={outcome.dense_only.n} ===\n")
    print(f"{'dense:sparse':>14s}  {'hit_rate':>9s} {'recall':>8s} {'MRR':>8s} {'nDCG':>8s}")
    print("-" * 56)
    for w, m in outcome.rows:
        tag = "  (=纯语义)" if w == 0 else ""
        print(f"{'1 : ' + format(w, 'g'):>14s}  {m.hit_rate:>8.1%} {m.recall:>7.1%} "
              f"{m.mrr:>8.4f} {m.ndcg:>8.4f}{tag}")
    print("-" * 56)
    print(f"\n判据（research.md Decision 6）：")
    print(f"  硬约束 recall >= {outcome.dense_only.recall:.1%}（纯语义水平）")
    print(f"  → {outcome.reason}")
    if outcome.recommended is not None:
        status = "✔ 硬约束满足" if outcome.satisfied_hard_constraint else "✘ 硬约束未满足"
        print(f"\n推荐权重：dense=1.0, sparse={outcome.recommended:g}   [{status}]")
    print()


def _print_compare(cache: Cache, k: int, top_k: int, recommended: float) -> None:
    configs = [
        ("纯语义", {"dense": 1.0, "sparse": 0.0}),
        ("等权混合", {"dense": 1.0, "sparse": 1.0}),
        (f"带权混合(1:{recommended:g})", {"dense": 1.0, "sparse": recommended}),
    ]
    print(f"\n=== 三方对比 lang={cache.lang} n={len(cache.cases)} rrf_k={k} ===\n")
    print(f"{'配置':>22s}  {'hit_rate':>9s} {'recall':>8s} {'MRR':>8s} {'nDCG':>8s}")
    print("-" * 62)
    results = {}
    for label, weights in configs:
        m = replay(cache, weights, k=k, top_k=top_k)
        results[label] = m
        print(f"{label:>22s}  {m.hit_rate:>8.1%} {m.recall:>7.1%} {m.mrr:>8.4f} {m.ndcg:>8.4f}")
    print("-" * 62)

    dense = results["纯语义"]
    equal = results["等权混合"]
    tuned = results[f"带权混合(1:{recommended:g})"]
    print("\n核心判据：")
    for name, ok in (
        (f"SC-001 带权 recall({tuned.recall:.1%}) >= 纯语义({dense.recall:.1%})",
         tuned.recall >= dense.recall),
        (f"SC-002 带权 hit_rate({tuned.hit_rate:.1%}) >= 纯语义({dense.hit_rate:.1%})",
         tuned.hit_rate >= dense.hit_rate),
        (f"SC-003 带权 MRR({tuned.mrr:.4f}) >= 等权({equal.mrr:.4f})",
         tuned.mrr >= equal.mrr),
        (f"SC-011 带权在 recall 与 MRR 上同时严格优于两个单路",
         tuned.recall > dense.recall and tuned.mrr > dense.mrr),
    ):
        print(f"  {'✔' if ok else '✘'} {name}")
    print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="融合权重校准：一次检索缓存 + 离线权重扫描 + 三方对比",
    )
    parser.add_argument("--build-cache", action="store_true",
                        help="执行两路检索并写缓存（唯一有 API 成本的步骤）")
    parser.add_argument("--sweep", action="store_true", help="离线扫描候选权重")
    parser.add_argument("--compare", action="store_true", help="三方对比")
    parser.add_argument("--lang", choices=["zh", "en"], required=True)
    parser.add_argument("--top-k", type=int, default=10, help="融合后取前 N 条算指标")
    parser.add_argument("--retrieve-top-k", type=int, default=20, help="每路召回数量")
    parser.add_argument("--recommended", type=float, default=None,
                        help="--compare 用的带权配置；缺省时先跑 sweep 取推荐值")
    parser.add_argument("--config", default="config/settings.yaml")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)

    if not (args.build_cache or args.sweep or args.compare):
        print("Error: 至少指定 --build-cache / --sweep / --compare 之一", file=sys.stderr)
        return 1

    try:
        settings = load_settings(args.config)
    except SettingsError as exc:
        logger.error("Failed to load settings: %s", exc)
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    path = cache_path(args.lang)
    k = settings.retrieval.rrf_k

    if args.build_cache:
        logger.info("Building route cache for lang=%s", args.lang)
        try:
            cache = build_cache(settings, args.lang, top_k=args.retrieve_top_k)
        except Exception as exc:  # noqa: BLE001 — 顶层 CLI 边界
            logger.error("Cache build failed: %s", exc)
            print(f"Error: 缓存构建失败: {exc}", file=sys.stderr)
            return 1
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cache.to_json(), ensure_ascii=False), encoding="utf-8")
        print(f"\n缓存已写入 {path}（{len(cache.cases)} 条 case，"
              f"collection={cache.collection}）\n")

    if not (args.sweep or args.compare):
        return 0

    if not path.exists():
        print(f"Error: 缓存不存在 {path}，先跑 --build-cache", file=sys.stderr)
        return 1

    try:
        cache = Cache.from_json(
            json.loads(path.read_text(encoding="utf-8")),
            expected_collection=settings.vector_store.collection_name,
        )
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    outcome: Optional[SweepOutcome] = None
    if args.sweep:
        outcome = sweep(cache, k=k, top_k=args.top_k)
        _print_sweep(outcome, args.lang, k)

    if args.compare:
        recommended = args.recommended
        if recommended is None:
            recommended = (outcome or sweep(cache, k=k, top_k=args.top_k)).recommended
        if recommended is None:
            print("Error: 无法确定推荐权重", file=sys.stderr)
            return 1
        _print_compare(cache, k=k, top_k=args.top_k, recommended=recommended)

    return 0


if __name__ == "__main__":
    sys.exit(main())
