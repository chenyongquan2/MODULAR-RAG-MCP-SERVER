"""评估运行脚本入口。"""

from __future__ import annotations

import argparse
import json
import sys

from src.core.query_engine.hybrid_search import HybridSearch
from src.core.response.response_builder import ResponseBuilder
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
    parser.add_argument(
        "--generate-answers",
        dest="generate_answers",
        action="store_true",
        default=None,
        help=(
            "Generate LLM answers via ResponseBuilder for each case (needed by "
            "RAGAS faithfulness/answer_relevancy). Default: auto-on when 'ragas' "
            "is configured as an evaluation backend."
        ),
    )
    parser.add_argument(
        "--no-generate-answers",
        dest="generate_answers",
        action="store_false",
        help="Disable answer generation even if RAGAS is configured.",
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

        # 是否生成 LLM answer：RAGAS 指标需要；仅检索评估时无需。
        # 默认行为：配置启用了 ragas 则自动打开；命令行可通过 --no-generate-answers 关闭。
        backends = [b.lower() for b in settings.evaluation.backends]
        auto_enable = "ragas" in backends
        should_generate = args.generate_answers if args.generate_answers is not None else auto_enable

        response_builder = None
        if should_generate:
            logger.info("Answer generation enabled; instantiating ResponseBuilder.")
            response_builder = ResponseBuilder(settings=settings)

        runner = EvalRunner(
            settings=settings,
            hybrid_search=hybrid_search,
            evaluator=evaluator,
            response_builder=response_builder,
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
