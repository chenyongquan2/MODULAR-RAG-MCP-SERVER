"""评估运行脚本入口 (Feature-001 后扩展)。

新增 CLI 参数 (T012):
    --lang {zh,en}       从 settings.evaluation.golden_test_sets_by_lang[lang] 取金标
                         (与 --test-set 互斥)
    --archive / --no-archive  控制是否归档到 logs/evaluation_reports/
                             (默认 True,符合 contracts/cli_contracts.md § 1)
    --exit-on-fail       acceptance_status=fail 时退出码 3(用于 CI 集成)

退出码 (contracts/cli_contracts.md § 1):
    0 = 评估成功(且若 --exit-on-fail,acceptance_status=pass)
    1 = 校验错误(ValueError;含 FR-007 chunk_id 不存在)
    2 = 运行时错误(RuntimeError;含 Judge LLM 不可达)
    3 = --exit-on-fail 启用 + acceptance_status=fail
"""

from __future__ import annotations

import argparse
import json
import sys

from src.core.query_engine.hybrid_search import HybridSearch
from src.core.response.response_builder import ResponseBuilder
from src.core.settings import Settings, load_settings
from src.core.types import AcceptanceStatus
from src.libs.evaluator.evaluator_factory import EvaluatorFactory
from src.observability.evaluation.eval_runner import EvalRunner
from src.observability.logger import get_logger

logger = get_logger(__name__)


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(
        description="Run RAG evaluation with golden test set (Feature-001)"
    )
    parser.add_argument(
        "--test-set",
        type=str,
        default=None,
        help=(
            "Path to golden test set JSON. Default: settings.evaluation.golden_test_set "
            "(or settings.evaluation.golden_test_sets_by_lang[<lang>] when --lang given)"
        ),
    )
    parser.add_argument(
        "--lang",
        choices=["zh", "en"],
        default=None,
        help=(
            "Use settings.evaluation.golden_test_sets_by_lang[<lang>] as test set path. "
            "Mutually exclusive with --test-set."
        ),
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
        help="Optional collection filter (default: settings.vector_store.collection_name)",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print report JSON",
    )
    parser.add_argument(
        "--archive",
        dest="archive",
        action="store_true",
        default=True,
        help=(
            "Archive report to settings.evaluation.report_archive_dir "
            "(default: True; writes <run_id>.json + appends index.jsonl)"
        ),
    )
    parser.add_argument(
        "--no-archive",
        dest="archive",
        action="store_false",
        help="Disable report archiving (e.g., for ad-hoc smoke runs).",
    )
    parser.add_argument(
        "--exit-on-fail",
        action="store_true",
        help=(
            "Exit with code 3 when acceptance_status=fail (FR-013); "
            "used for CI gate integration."
        ),
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
    args = parser.parse_args()

    # 互斥校验 (--test-set / --lang 二选一)
    if args.test_set and args.lang:
        parser.error("--test-set and --lang are mutually exclusive")

    return args


def _resolve_test_set_path(args: argparse.Namespace, settings: Settings) -> str:
    """根据 --test-set / --lang 解析最终金标路径。

    优先级:
    1. --test-set 显式路径
    2. --lang 时从 settings.evaluation.golden_test_sets_by_lang[<lang>] 取
    3. 默认 settings.evaluation.golden_test_set(占位金标)
    """
    if args.test_set:
        return str(args.test_set)
    if args.lang:
        by_lang = settings.evaluation.golden_test_sets_by_lang or {}
        path = by_lang.get(args.lang)
        if not path:
            raise ValueError(
                f"--lang={args.lang} requires settings.evaluation.golden_test_sets_by_lang"
                f"['{args.lang}'] to be set; current value: {by_lang!r}"
            )
        return str(path)
    return str(settings.evaluation.golden_test_set)


def main() -> int:
    """执行评估流程。

    Returns:
        int: 退出码 (见模块 docstring)。
    """
    args = parse_args()
    try:
        settings = load_settings()
        test_set_path = _resolve_test_set_path(args, settings)

        hybrid_search = HybridSearch(settings=settings)
        evaluator = EvaluatorFactory.create(settings=settings)

        # 是否生成 LLM answer:RAGAS 指标需要;仅检索评估时无需。
        # 默认:配置启用了 ragas 则自动打开;命令行可通过 --no-generate-answers 关闭。
        backends = [b.lower() for b in settings.evaluation.backends]
        auto_enable = "ragas" in backends
        should_generate = (
            args.generate_answers if args.generate_answers is not None else auto_enable
        )

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
            test_set_path=test_set_path,
            top_k=args.top_k,
            filters=filters,
            archive=args.archive,
        )
    except ValueError as exc:
        logger.error("Evaluation validation failed: %s", exc)
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except RuntimeError as exc:
        logger.error("Evaluation runtime failed: %s", exc)
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # pragma: no cover - 防御性分支
        logger.error("Unexpected evaluation error: %s", exc)
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    report_dict = report.to_dict()
    indent = 2 if args.pretty else None
    print(json.dumps(report_dict, ensure_ascii=False, indent=indent))

    # FR-013 + --exit-on-fail:acceptance_status=fail 时返回退出码 3 (CI gate)
    if args.exit_on_fail and report.acceptance_status == AcceptanceStatus.FAIL:
        logger.warning(
            "acceptance_status=fail; exiting with code 3 due to --exit-on-fail"
        )
        return 3

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
