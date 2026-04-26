"""US2 候选合成 CLI (T020, refs FR-004 / contracts/cli_contracts.md § 2)。

用 RAGAS TestsetGenerator + 项目 LLMFactory/EmbeddingFactory 从已摄入语料合成
候选 (question, ground_truth) 对,产出到 ``tests/fixtures/candidates/<lang>.json``。

退出码:
    0 = 合成成功
    1 = 配置/输入错误(collection 不存在 / target_count <= 0 / distribution 非法)
    2 = RAGAS 内部错误(LLM 调用失败、超时、模型不兼容)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.core.settings import load_settings
from src.observability.evaluation.testset_synthesizer import (
    DEFAULT_DISTRIBUTION,
    TestsetSynthesizer,
)
from src.observability.logger import get_logger

logger = get_logger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Synthesize candidate test set via RAGAS (Feature-001 US2 step 1)"
    )
    parser.add_argument(
        "--collection",
        required=True,
        help="Vector store collection name (e.g., mt5_docs_chinese / mt5_docs_english)",
    )
    parser.add_argument(
        "--lang",
        choices=["zh", "en"],
        required=True,
        help="Target language for the candidate set",
    )
    parser.add_argument(
        "--target-count",
        type=int,
        default=100,
        help="Number of candidate cases to synthesize (default 100; refine to >=40)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help=(
            "Output JSON path (default: tests/fixtures/candidates/<lang>.json). "
            "Parent dir will be created if missing."
        ),
    )
    parser.add_argument(
        "--distribution",
        type=str,
        default="0.5:0.3:0.2",
        help=(
            "Difficulty distribution as 'simple:reasoning:multi_context' "
            "(default 0.5:0.3:0.2; sum should be ~1.0)"
        ),
    )
    parser.add_argument(
        "--chunk-sample-size",
        type=int,
        default=None,
        help=(
            "Pull this many chunks from the collection as RAGAS source corpus. "
            "Default: target_count * 5"
        ),
    )
    return parser.parse_args()


def _parse_distribution(spec: str) -> dict[str, float]:
    """支持 '0.5:0.3:0.2' 或 '0.5,0.3,0.2' 两种分隔符。"""
    parts = spec.replace(",", ":").split(":")
    if len(parts) != 3:
        raise ValueError(
            f"--distribution must have 3 numbers separated by ':' or ',' "
            f"(got {spec!r})"
        )
    try:
        s, r, m = (float(p.strip()) for p in parts)
    except ValueError as exc:
        raise ValueError(f"--distribution values must be floats: {exc}") from exc
    return {"simple": s, "reasoning": r, "multi_context": m}


def _resolve_output_path(arg_output: str | None, lang: str) -> Path:
    if arg_output:
        return Path(arg_output)
    return Path("tests/fixtures/candidates") / f"{lang}.json"


def main() -> int:
    args = parse_args()

    try:
        settings = load_settings()
        distribution = _parse_distribution(args.distribution)
        synth = TestsetSynthesizer(settings=settings)
        logger.info(
            "Synthesizing %d candidates for collection=%s lang=%s distribution=%s",
            args.target_count, args.collection, args.lang, distribution,
        )
        candidate = synth.synthesize(
            collection=args.collection,
            lang=args.lang,
            target_count=args.target_count,
            distribution=distribution,
            chunk_sample_size=args.chunk_sample_size,
        )
    except ValueError as exc:
        logger.error("Synthesis validation failed: %s", exc)
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except RuntimeError as exc:
        logger.error("Synthesis runtime failed: %s", exc)
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Unexpected synthesis error: %s", exc)
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    output_path = _resolve_output_path(args.output, args.lang)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(candidate, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    n_cases = len(candidate.get("test_cases", []))
    diff_counter: dict[str, int] = {}
    for case in candidate["test_cases"]:
        d = case.get("tags", {}).get("difficulty", "simple")
        diff_counter[d] = diff_counter.get(d, 0) + 1

    print(
        f"Synthesized {n_cases} candidates -> {output_path} "
        f"({', '.join(f'{k}={v}' for k, v in sorted(diff_counter.items()))})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
