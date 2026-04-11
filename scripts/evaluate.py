"""评估运行脚本入口。"""

from __future__ import annotations

import argparse
import json
import sys

from src.core.query_engine.hybrid_search import HybridSearch
from src.core.settings import load_settings
from src.libs.evaluator.evaluator_factory import EvaluatorFactory
from src.observability.evaluation.eval_runner import EvalRunner
from src.observability.logger import get_logger

logger = get_logger(__name__)


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(description="Run retrieval evaluation with golden test set")
    parser.add_argument(
        "--test-set",
        type=str,
        default="tests/fixtures/golden_test_set.json",
        help="Path to golden test set JSON",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=None,
        help="Top-K retrieval results per query (default: settings.retrieval.top_k_final)",
    )
    parser.add_argument(
        "--collection",
        type=str,
        default=None,
        help="Optional collection filter",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print report JSON",
    )
    return parser.parse_args()


def main() -> int:
    """执行评估流程。

    Returns:
        int: 0 表示成功，1 表示失败。
    """
    args = parse_args()
    try:
        settings = load_settings()
        hybrid_search = HybridSearch(settings=settings)
        evaluator = EvaluatorFactory.create(settings=settings)
        runner = EvalRunner(
            settings=settings,
            hybrid_search=hybrid_search,
            evaluator=evaluator,
        )

        filters = {"collection": args.collection} if args.collection else None
        report = runner.run(
            test_set_path=args.test_set,
            top_k=args.top_k,
            filters=filters,
        )
    except ValueError as exc:
        logger.error("Evaluation validation failed: %s", exc)
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except RuntimeError as exc:
        logger.error("Evaluation runtime failed: %s", exc)
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # pragma: no cover - 防御性分支
        logger.error("Unexpected evaluation error: %s", exc)
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    report_dict = report.to_dict()
    indent = 2 if args.pretty else None
    print(json.dumps(report_dict, ensure_ascii=False, indent=indent))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
