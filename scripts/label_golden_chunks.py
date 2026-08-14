"""金标标注 CLI —— 检索器无关的 expected_chunk_ids 构造。

change: retriever-agnostic-golden-labels (T-4.1 / T-4.2 / T-4.3)

## 与 backfill_chunk_ids.py 的区别

``scripts/backfill_chunk_ids.py``(第一代)把 ``ground_truth`` 编码成向量,查
dense top-5,过相似度阈值后写入 —— **标准答案就是「embedding 认为最像答案的
那几条」**,于是所有召回类指标都锚定 dense 一路。

本脚本改为:
1. 用 **query**(而非答案)从 dense / sparse / rerank 三路各取 top-N,取并集
2. 让 LLM 对每个候选判 0-3 分级相关度,``>= relevance_threshold`` 的纳入

没有任何一路能垄断标准答案。旧脚本**保留**,它是第一代金标的可复现来源。

## 用法

    python -u scripts/label_golden_chunks.py \
        --input tests/fixtures/golden_test_set_en.json \
        --output tests/fixtures/golden_test_set_en_v2.json \
        --collection default_text-embedding-v4

    # 人工抽检（判定可信度的必要闸门）
    python -u scripts/label_golden_chunks.py --input <v2> --export-sample 20 \
        --sample-out sample.json
    # 人工在 sample.json 里填 human_label，然后：
    python -u scripts/label_golden_chunks.py --input <v2> --import-sample sample.json

**务必加 `-u`** —— stdout 在管道下是全缓冲的,不加会看到空输出并误判成卡死。

## 退出码(沿用 Feature-003 语义)

    0   = 成功
    1   = 输入错误(文件/JSON/collection)
    2   = 前置条件不满足(labeling_llm 未配置 / 与合成端同源 / 无法确认异源)
    3   = 判定模型整体不可用(凭据、网络、模型下架)
    130 = 中断。**文件仍会写出**并标 partial,已完成的判定不丢
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.core.settings import load_settings
from src.observability.evaluation.chunk_labeler import (
    ChunkLabeler,
    ChunkVerdict,
    LabelingUnavailableError,
    check_labeling_divergence,
    get_labeling_identifier,
)
from src.observability.evaluation.chunk_pooler import (
    ChunkPooler,
    check_dense_overlap,
    dense_jaccard,
)
from src.observability.evaluation.testset_screener import SourceRelation
from src.observability.logger import get_logger

logger = get_logger(__name__)


LABELING_METHOD = "pooled-llm-judged"
"""写进金标的标注方式标识。第一代是 "dense-top-k"。"""

GOLDEN_VERSION_V2 = "v2.0"
GOLDEN_VERSION_PARTIAL = "v2.0-partial"

EXIT_OK = 0
EXIT_INPUT_ERROR = 1
EXIT_PRECONDITION = 2
EXIT_MODEL_UNAVAILABLE = 3
EXIT_INTERRUPTED = 130


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Label golden expected_chunk_ids via multi-route pooling + LLM judging "
            "(retriever-agnostic; replaces the dense-only backfill)"
        )
    )
    parser.add_argument("--input", required=True, help="Path to golden test set JSON")
    parser.add_argument(
        "--output",
        default=None,
        help=(
            "Where to write the labelled set. Defaults to <input>_v2.json. "
            "The input file is NEVER overwritten — old and new labels are not the "
            "same yardstick, so both must remain available"
        ),
    )
    parser.add_argument(
        "--collection",
        default=None,
        help=(
            "Retrieval collection (overrides settings.vector_store.collection_name "
            "for BOTH dense and sparse routes)"
        ),
    )
    parser.add_argument(
        "--allow-same-source",
        action="store_true",
        help=(
            "Proceed when source divergence cannot be VERIFIED (missing synthesis "
            "identifier). Does NOT waive a confirmed same-source pair"
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Pool candidates and report sizes without making any judging call",
    )
    parser.add_argument(
        "--export-sample",
        type=int,
        default=0,
        metavar="N",
        help=(
            "Export N random (query, chunk, verdict) triples for human review. "
            "Sampling is stratified across relevant and non-relevant verdicts — "
            "sampling only the accepted ones cannot detect over-acceptance"
        ),
    )
    parser.add_argument(
        "--sample-out",
        default="labeling_sample.json",
        help="Where --export-sample writes (default: labeling_sample.json)",
    )
    parser.add_argument(
        "--import-sample",
        default=None,
        help=(
            "Read a human-reviewed sample file, compute agreement rate and write it "
            "into the golden set's labeling metadata"
        ),
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Random seed for sampling (makes --export-sample reproducible)",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# 前置检查
# ---------------------------------------------------------------------------


def check_preconditions(
    settings: Any,
    golden: Dict[str, Any],
    allow_same_source: bool,
) -> Optional[str]:
    """检查标注的前置条件。返回问题描述,None 表示通过。

    两条:``labeling_llm`` 必须已配置;判定端必须与合成端异源。
    """
    cfg = settings.evaluation.labeling_llm
    if not cfg.is_enabled():
        return (
            "evaluation.labeling_llm.provider and .model must both be set. "
            "The labelling model MUST differ from evaluation.judge_llm (which "
            "synthesised ground_truth) — otherwise it would be judging which "
            "chunks support an answer it wrote itself."
        )

    relation = check_labeling_divergence(settings, golden)

    if relation is SourceRelation.SAME_SOURCE:
        return (
            f"labeling LLM ({get_labeling_identifier(settings)}) is the same model "
            "that synthesised ground_truth. Change evaluation.labeling_llm.model to "
            "a different model. This is NOT waivable by --allow-same-source: a model "
            "grading its own answers cannot give an independent relevance judgement."
        )

    if relation is SourceRelation.UNVERIFIABLE and not allow_same_source:
        return (
            "cannot verify source divergence — the golden set carries no synthesis "
            "identifier (_synthesis_metadata.judge_llm_identifier or "
            "_review_metadata.synthesis_identifier), so there is no way to tell "
            "whether the labelling model wrote these answers. Re-run with "
            "--allow-same-source to accept that risk explicitly."
        )

    return None


# ---------------------------------------------------------------------------
# 续跑:从已有产出里读回已判定的候选
# ---------------------------------------------------------------------------


def load_prior_verdicts(path: Path) -> Dict[int, Dict[str, ChunkVerdict]]:
    """从已有产出里读回每个 case 已判定过的候选。

    续跑靠产出文件自身,不引入独立断点文件 —— 多一个文件就多一处可能与产出
    不一致的状态。

    Returns:
        ``{case_index: {chunk_id: ChunkVerdict}}``。文件不存在或格式不符时返回空。
    """
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("cannot read prior output %s for resume: %s", path, exc)
        return {}

    out: Dict[int, Dict[str, ChunkVerdict]] = {}
    for idx, case in enumerate(data.get("test_cases") or []):
        labels = case.get("_chunk_labels") or []
        per_case: Dict[str, ChunkVerdict] = {}
        for entry in labels:
            cid = entry.get("chunk_id")
            if not cid:
                continue
            grade = entry.get("grade")
            per_case[str(cid)] = ChunkVerdict(
                chunk_id=str(cid),
                grade=int(grade) if isinstance(grade, int) else None,
                reason=str(entry.get("reason") or ""),
                judge_failed=bool(entry.get("judge_failed")),
            )
        if per_case:
            out[idx] = per_case
    if out:
        total = sum(len(v) for v in out.values())
        logger.info("resume: found %d already-judged candidates in %s", total, path)
    return out


# ---------------------------------------------------------------------------
# 人工抽检 (T-4.3)
# ---------------------------------------------------------------------------


def export_sample(
    golden: Dict[str, Any],
    n: int,
    seed: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """导出 n 个 (query, chunk, 判定) 三元组供人工复核。

    **分层抽样**:相关与不相关各抽一半。只抽通过的无法发现「判定过于宽松」——
    而过于宽松正是最可能的失效方向(LLM 倾向于说「有关」)。

    Args:
        golden: 已标注的金标。
        n: 抽多少条。
        seed: 随机种子,使抽样可复现。

    Returns:
        待人工填写 ``human_label`` 的样本列表。
    """
    threshold = 2  # 仅用于分层，实际门槛已体现在 label 字段里
    relevant: List[Dict[str, Any]] = []
    other: List[Dict[str, Any]] = []

    for case in golden.get("test_cases") or []:
        query = case.get("query", "")
        accepted = set(case.get("expected_chunk_ids") or [])
        for entry in case.get("_chunk_labels") or []:
            cid = entry.get("chunk_id")
            if not cid:
                continue
            record = {
                "query": query,
                "chunk_id": cid,
                "chunk_text": entry.get("chunk_text", ""),
                "llm_grade": entry.get("grade"),
                "llm_reason": entry.get("reason", ""),
                "llm_accepted": cid in accepted,
                "human_label": None,  # 人工填：true = 相关 / false = 不相关
            }
            (relevant if cid in accepted else other).append(record)

    rng = random.Random(seed)
    rng.shuffle(relevant)
    rng.shuffle(other)

    half = n // 2
    picked = relevant[:half] + other[: n - half]
    # 某一层不够时从另一层补足
    if len(picked) < n:
        pool = relevant[half:] + other[n - half :]
        rng.shuffle(pool)
        picked += pool[: n - len(picked)]

    rng.shuffle(picked)
    return picked[:n]


def compute_agreement(sample: List[Dict[str, Any]]) -> Tuple[float, int, int]:
    """算人工复核与 LLM 判定的一致率。

    只统计人工填了 ``human_label`` 的条目 —— 没填的不算作「不一致」。

    Returns:
        ``(一致率, 已复核条数, 一致条数)``。已复核为 0 时一致率为 0.0。
    """
    reviewed = [
        r for r in sample if isinstance(r.get("human_label"), bool)
    ]
    if not reviewed:
        return 0.0, 0, 0
    agree = sum(
        1 for r in reviewed if bool(r.get("llm_accepted")) == bool(r["human_label"])
    )
    return agree / len(reviewed), len(reviewed), agree


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


def _default_output(input_path: Path) -> Path:
    return input_path.with_name(f"{input_path.stem}_v2{input_path.suffix}")


def main() -> int:  # noqa: C901 —— CLI 编排，分支多但线性
    args = parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: input file not found: {input_path}", file=sys.stderr)
        return EXIT_INPUT_ERROR
    try:
        golden = json.loads(input_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"Error: input not valid JSON: {exc}", file=sys.stderr)
        return EXIT_INPUT_ERROR

    cases = golden.get("test_cases")
    if not isinstance(cases, list) or not cases:
        print("Error: input missing or empty 'test_cases'", file=sys.stderr)
        return EXIT_INPUT_ERROR

    # ── 抽检导出/回填：两条不需要任何 LLM 调用的旁路 ──────────────────
    if args.export_sample > 0:
        sample = export_sample(golden, args.export_sample, seed=args.seed)
        out = Path(args.sample_out)
        out.write_text(
            json.dumps(sample, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(
            f"Exported {len(sample)} triples to {out}. "
            "Fill in 'human_label' (true/false) for each, then re-run with "
            f"--import-sample {out}"
        )
        return EXIT_OK

    if args.import_sample:
        sample_path = Path(args.import_sample)
        if not sample_path.exists():
            print(f"Error: sample file not found: {sample_path}", file=sys.stderr)
            return EXIT_INPUT_ERROR
        sample = json.loads(sample_path.read_text(encoding="utf-8"))
        rate, reviewed, agree = compute_agreement(sample)
        meta = golden.setdefault("_labeling_metadata", {})
        meta["human_agreement_rate"] = round(rate, 4)
        meta["human_reviewed_count"] = reviewed
        meta["human_agreed_count"] = agree

        settings = load_settings()
        warn_at = settings.evaluation.labeling.human_agreement_warn
        warnings = meta.setdefault("warnings", [])
        if reviewed == 0:
            warnings.append(
                "human sample imported but no human_label filled in — agreement "
                "rate is meaningless; the judging model remains uncalibrated"
            )
        elif rate < warn_at:
            warnings.append(
                f"human agreement {rate:.1%} below {warn_at:.1%}; the labelling "
                "prompt or model needs recalibration before these labels are "
                "trusted as ground truth"
            )
        input_path.write_text(
            json.dumps(golden, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(
            f"Agreement {rate:.1%} ({agree}/{reviewed} reviewed) -> {input_path}"
        )
        return EXIT_OK

    # ── 正常标注流程 ──────────────────────────────────────────────────
    try:
        settings = load_settings()
    except Exception as exc:  # noqa: BLE001
        print(f"Error: failed to load settings: {exc}", file=sys.stderr)
        return EXIT_INPUT_ERROR

    if args.collection:
        logger.info(
            "overriding retrieval collection: %s -> %s",
            settings.vector_store.collection_name,
            args.collection,
        )
        settings.vector_store.collection_name = args.collection

    problem = check_preconditions(settings, golden, args.allow_same_source)
    if problem:
        print(f"Error: {problem}", file=sys.stderr)
        return EXIT_PRECONDITION

    output_path = Path(args.output) if args.output else _default_output(input_path)
    if output_path.resolve() == input_path.resolve():
        print(
            "Error: --output must differ from --input. Old and new labels are not "
            "the same yardstick — overwriting would make historical baselines "
            "silently incomparable.",
            file=sys.stderr,
        )
        return EXIT_INPUT_ERROR

    prior = load_prior_verdicts(output_path)

    try:
        pooler = ChunkPooler(settings)
        labeler = ChunkLabeler(settings) if not args.dry_run else None
    except Exception as exc:  # noqa: BLE001
        print(f"Error: failed to init labelling components: {exc}", file=sys.stderr)
        return EXIT_INPUT_ERROR

    labeling_cfg = settings.evaluation.labeling
    budget_left = labeling_cfg.max_judgements
    interrupted = False
    model_unavailable = False

    route_totals: Dict[str, int] = {}
    pool_sizes: List[int] = []
    accepted_total = 0
    rejected_total = 0
    failed_total = 0
    skipped_total = 0
    warnings: List[str] = []
    jaccards: List[float] = []

    try:
        for idx, case in enumerate(cases):
            query = case.get("query", "")
            ground_truth = case.get("ground_truth", "")
            if not query.strip():
                logger.warning("case[%d] has empty query, skipping", idx)
                continue

            pool = pooler.pool(query)
            pool_sizes.append(len(pool.candidates))
            for route, count in pool.route_counts.items():
                route_totals[route] = route_totals.get(route, 0) + count
            for route, err in pool.errors.items():
                warnings.append(f"case[{idx}] route {route} failed: {err}")

            print(
                f"  [{idx + 1}/{len(cases)}] pooled {len(pool.candidates):>3d} "
                f"candidates  {dict(pool.route_counts)}",
                flush=True,
            )

            if args.dry_run or labeler is None:
                continue

            run = labeler.label_all(
                query,
                ground_truth,
                pool.candidates,
                budget=budget_left,
                already_judged=prior.get(idx),
            )
            budget_left -= run.judged_count
            skipped_total += run.skipped_count
            failed_total += sum(1 for v in run.verdicts if v.judge_failed)
            warnings.extend(run.warnings)

            relevant = labeler.relevant_ids(run)
            accepted_total += len(relevant)
            rejected_total += len(run.verdicts) - len(relevant)

            texts = {c.chunk_id: c.text for c in pool.candidates}
            contributions = {c.chunk_id: c.contributed_by for c in pool.candidates}

            case["expected_chunk_ids"] = relevant
            case["_chunk_labels"] = [
                {
                    "chunk_id": v.chunk_id,
                    "grade": v.grade,
                    "reason": v.reason,
                    "judge_failed": v.judge_failed,
                    "contributed_by": contributions.get(v.chunk_id, []),
                    "chunk_text": texts.get(v.chunk_id, "")[:500],
                }
                for v in run.verdicts
            ]

            jaccards.append(dense_jaccard(relevant, pool.dense_top_k_ids))
            overlap_warning = check_dense_overlap(
                relevant, pool.dense_top_k_ids, labeling_cfg.dense_overlap_warn
            )
            if overlap_warning:
                warnings.append(f"case[{idx}] {overlap_warning}")

    except LabelingUnavailableError as exc:
        # **必须先写出已完成的部分再退出。**
        #
        # 这里曾经直接 return,结果 2026-08-13 英文那轮跑到第 20 个 case 时网关
        # 挂掉(Connection error),前 19 个 case 约 630 次判定、2.5 小时的工作
        # **全部丢失** —— 而续跑恰恰依赖产出文件存在。于是「模型不可用」这条
        # 快速失败路径把 spec 要求的「可续跑」直接架空了。
        #
        # 快速失败要防的是「产出一份全是不相关的空金标」,不是「丢掉已经算好的
        # 结果」。两者不冲突:写出部分结果 + 标 partial + 退出码 3,既留痕又不
        # 让调用方误以为跑完了。
        model_unavailable = True
        print(f"Error: {exc}", file=sys.stderr)
        print(
            "Writing partial results so the completed cases are not lost — "
            "re-run the same command to resume from here once the gateway "
            "recovers.",
            file=sys.stderr,
        )
    except KeyboardInterrupt:
        interrupted = True
        print("\nInterrupted — writing partial results.", file=sys.stderr)

    if model_unavailable:
        warnings.append(
            "labelling stopped early: the judging model became unavailable "
            "(all calls for one case failed at the transport layer). This output "
            "is PARTIAL — re-run the same command to resume."
        )

    mean_jaccard = sum(jaccards) / len(jaccards) if jaccards else 0.0
    if skipped_total:
        warnings.append(
            f"{skipped_total} candidates were never judged because "
            f"max_judgements={labeling_cfg.max_judgements} was reached. This output "
            "is NOT a complete labelling — re-run to continue from here."
        )

    golden["version"] = (
        GOLDEN_VERSION_PARTIAL
        if (interrupted or skipped_total or model_unavailable)
        else GOLDEN_VERSION_V2
    )
    golden["_labeling_method"] = LABELING_METHOD
    golden["_labeling_metadata"] = {
        "route_contributions": route_totals,
        "pool_size_mean": round(sum(pool_sizes) / len(pool_sizes), 2) if pool_sizes else 0,
        "pool_size_max": max(pool_sizes) if pool_sizes else 0,
        "accepted_count": accepted_total,
        "rejected_count": rejected_total,
        "judge_failed_count": failed_total,
        "skipped_count": skipped_total,
        "labeling_llm_identifier": get_labeling_identifier(settings),
        "synthesis_llm_identifier": (
            (golden.get("_synthesis_metadata") or {}).get("judge_llm_identifier")
            or (golden.get("_review_metadata") or {}).get("synthesis_identifier")
            or ""
        ),
        "mean_dense_jaccard": round(mean_jaccard, 4),
        "config_snapshot": {
            "pool_top_n_dense": labeling_cfg.pool_top_n_dense,
            "pool_top_n_sparse": labeling_cfg.pool_top_n_sparse,
            "pool_top_n_rerank": labeling_cfg.pool_top_n_rerank,
            "relevance_threshold": labeling_cfg.relevance_threshold,
            "max_judgements": labeling_cfg.max_judgements,
        },
        "warnings": warnings,
        "interrupted": interrupted,
        "model_unavailable": model_unavailable,
    }

    if args.dry_run:
        print(
            f"Dry run: {len(pool_sizes)} cases pooled, mean pool size "
            f"{golden['_labeling_metadata']['pool_size_mean']}, "
            f"routes {route_totals}. No judging calls made, no file written."
        )
        return EXIT_OK

    output_path.write_text(
        json.dumps(golden, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        f"Labelled {accepted_total} accepted / {rejected_total} rejected / "
        f"{failed_total} judge-failed / {skipped_total} skipped; "
        f"mean dense Jaccard {mean_jaccard:.3f} -> {output_path}"
    )
    for w in warnings:
        print(f"  WARNING: {w}", file=sys.stderr)

    # 退出码优先级：模型不可用(3) > 中断(130) > 正常(0)。
    # 前者是需要人去修网关的信号，比「被中断」更需要引起注意。
    if model_unavailable:
        return EXIT_MODEL_UNAVAILABLE
    return EXIT_INTERRUPTED if interrupted else EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
