"""Unit tests for 分路径评估口径 (T-1.2 / T-1.3)。

change: per-route-metrics-and-synonym-rewrite

**为什么需要分路径指标**：现有 8 项指标量的都是**融合后**的最终结果。而本项目
稀疏路的生效权重只有稠密路的十分之一（``fusion_weights.sparse = 0.1``），所以
任何只作用于稀疏路的改进（同义词扩展就是），其效果在融合后指标上几乎看不见 ——
会得出「改写没用」的错误结论，而改善其实真的发生了，只是被融合口径量丢了。

这与本项目在第一代金标上踩的坑是同一类失败：**尺子不对时，做对的事会被判为做错。**

**本文件最关键的一组是** ``TestSingleRouteEqualsFused`` —— 那是分路径口径唯一的
自检手段。没有它，分路径指标算错了也没人会知道（又一个「看起来生效、实际没生效、
而且不报错」）。

不触发任何 LLM / 向量库调用 —— 全部用替身。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

import pytest

from src.core.settings import load_settings
from src.core.types import ROUTE_DENSE, ROUTE_SPARSE, RetrievalResult, SearchOutcome
from src.libs.evaluator.custom_evaluator import CustomEvaluator
from src.observability.evaluation.eval_runner import EvalRunner

pytestmark = pytest.mark.unit


def _r(chunk_id: str) -> RetrievalResult:
    return RetrievalResult(chunk_id=chunk_id, score=0.5, text=f"t-{chunk_id}", metadata={})


class StubSearchWithRoutes:
    """按 query 返回预置 SearchOutcome 的检索引擎替身。"""

    def __init__(self, outcomes: Dict[str, SearchOutcome]) -> None:
        self._outcomes = outcomes

    def search_with_routes(self, query: str, **kwargs: Any) -> SearchOutcome:
        return self._outcomes[query]

    def search(self, query: str, **kwargs: Any) -> List[RetrievalResult]:
        return self._outcomes[query].results


class StubSearchLegacy:
    """只有 search() 的老式检索引擎替身 —— 用于验证「测不了就不出数」。"""

    def __init__(self, results: Sequence[RetrievalResult]) -> None:
        self._results = list(results)

    def search(self, query: str, **kwargs: Any) -> List[RetrievalResult]:
        return list(self._results)


def _runner(hybrid: Any, evaluator: Any = None) -> EvalRunner:
    settings = load_settings()
    return EvalRunner(
        settings=settings,
        hybrid_search=hybrid,
        evaluator=evaluator if evaluator is not None else CustomEvaluator(settings),
    )


def _golden(tmp_path, cases: Sequence[Dict[str, Any]]):
    import json

    data = {
        "_schema_version": 1,
        "version": "v2.0",
        "language": "en",
        "_labeling_method": "pooled-llm-judged",
        "test_cases": [
            {
                "query": c["query"],
                "expected_chunk_ids": list(c["expected"]),
                "expected_sources": [],
                "ground_truth": "gt",
            }
            for c in cases
        ],
    }
    path = tmp_path / "golden.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return str(path)


def _run(runner: EvalRunner, path: str, top_k: int = 10):
    # chunk_id 存在性校验会去连向量库，这里关掉 —— 本组测试只关心指标口径。
    runner._validate_chunk_ids_exist = lambda *a, **k: None  # type: ignore[method-assign]
    return runner.run(test_set_path=path, top_k=top_k, archive=False)


# ---------------------------------------------------------------------------
# 分路径指标产出
# ---------------------------------------------------------------------------


class TestRouteMetricsProduced:
    def test_both_routes_reported_alongside_fused(self, tmp_path) -> None:
        """分路径与融合后指标并存，且不会因同名而混淆。"""
        outcome = SearchOutcome(
            results=[_r("a"), _r("b")],
            routes={ROUTE_DENSE: [_r("a")], ROUTE_SPARSE: [_r("b")]},
        )
        path = _golden(tmp_path, [{"query": "q1", "expected": ["a"]}])

        report = _run(_runner(StubSearchWithRoutes({"q1": outcome})), path)

        assert set(report.aggregate_metrics_by_route) == {ROUTE_DENSE, ROUTE_SPARSE}
        # 融合后 a 在第 1 位 → mrr 1.0；dense 路 a 也在第 1 位 → 1.0；
        # sparse 路只有 b，一个都没命中 → 0.0。三者互不干扰。
        assert report.aggregate_metrics["mrr"] == pytest.approx(1.0)
        assert report.aggregate_metrics_by_route[ROUTE_DENSE]["mrr"] == pytest.approx(1.0)
        assert report.aggregate_metrics_by_route[ROUTE_SPARSE]["mrr"] == pytest.approx(0.0)

    def test_four_metrics_per_route(self, tmp_path) -> None:
        outcome = SearchOutcome(
            results=[_r("a")],
            routes={ROUTE_DENSE: [_r("a")], ROUTE_SPARSE: [_r("z")]},
        )
        path = _golden(tmp_path, [{"query": "q1", "expected": ["a"]}])

        report = _run(_runner(StubSearchWithRoutes({"q1": outcome})), path)

        for name in (ROUTE_DENSE, ROUTE_SPARSE):
            assert set(report.aggregate_metrics_by_route[name]) == {
                "hit_rate",
                "mrr",
                "recall",
                "ndcg",
            }

    def test_empty_route_counts_as_miss_not_skipped(self, tmp_path) -> None:
        """某一路无结果时按未命中计入，分母仍是全部用例数。

        跳过会让分母悄悄变小、均值被幸存者偏差抬高 —— 正是 RAGAS 降级那个坑。
        """
        outcomes = {
            "q1": SearchOutcome(
                results=[_r("a")],
                routes={ROUTE_DENSE: [_r("a")], ROUTE_SPARSE: []},
            ),
            "q2": SearchOutcome(
                results=[_r("b")],
                routes={ROUTE_DENSE: [_r("b")], ROUTE_SPARSE: [_r("b")]},
            ),
        }
        path = _golden(
            tmp_path,
            [{"query": "q1", "expected": ["a"]}, {"query": "q2", "expected": ["b"]}],
        )

        report = _run(_runner(StubSearchWithRoutes(outcomes)), path)

        # sparse：q1 空（0.0）+ q2 命中第 1 位（1.0），分母 2 → 0.5。
        # 若 q1 被跳过，分母会变成 1、结果虚高成 1.0。
        assert report.aggregate_metrics_by_route[ROUTE_SPARSE]["mrr"] == pytest.approx(0.5)
        assert report.aggregate_metrics_by_route[ROUTE_DENSE]["mrr"] == pytest.approx(1.0)

    def test_case_level_route_metrics_serialized(self, tmp_path) -> None:
        outcome = SearchOutcome(
            results=[_r("a")], routes={ROUTE_DENSE: [_r("a")], ROUTE_SPARSE: []}
        )
        path = _golden(tmp_path, [{"query": "q1", "expected": ["a"]}])

        report = _run(_runner(StubSearchWithRoutes({"q1": outcome})), path)

        case_dict = report.to_dict()["case_results"][0]
        assert case_dict["route_metrics"][ROUTE_DENSE]["hit_rate"] == pytest.approx(1.0)
        assert case_dict["route_metrics"][ROUTE_SPARSE]["hit_rate"] == pytest.approx(0.0)

    def test_report_dict_contains_route_aggregate(self, tmp_path) -> None:
        outcome = SearchOutcome(
            results=[_r("a")], routes={ROUTE_DENSE: [_r("a")], ROUTE_SPARSE: []}
        )
        path = _golden(tmp_path, [{"query": "q1", "expected": ["a"]}])

        report = _run(_runner(StubSearchWithRoutes({"q1": outcome})), path)

        assert "aggregate_metrics_by_route" in report.to_dict()


class TestUnmeasuredIsNotZero:
    """测不了分路径时**不产出**该字段，而不是填零值。

    「没测」和「测了但全零」必须长得不一样 —— 回落成看起来正常的默认值，
    正是本项目反复踩的那个坑（`_synthesis_metadata.language_consistency`
    为此刻意用 `measured: false` 而不给数）。
    """

    def test_legacy_search_engine_yields_no_route_field(self, tmp_path) -> None:
        path = _golden(tmp_path, [{"query": "q1", "expected": ["a"]}])

        report = _run(_runner(StubSearchLegacy([_r("a")])), path)

        assert report.aggregate_metrics_by_route == {}
        assert "aggregate_metrics_by_route" not in report.to_dict()
        # 融合后指标照常产出 —— 老路不受影响
        assert report.aggregate_metrics["hit_rate"] == pytest.approx(1.0)

    def test_evaluator_without_capability_yields_no_route_field(self, tmp_path) -> None:
        """评估后端不支持只凭 id 打分时同样不产出。"""

        class NoCapabilityEvaluator(CustomEvaluator):
            def supports_retrieval_only(self) -> bool:
                return False

        outcome = SearchOutcome(
            results=[_r("a")], routes={ROUTE_DENSE: [_r("a")], ROUTE_SPARSE: []}
        )
        path = _golden(tmp_path, [{"query": "q1", "expected": ["a"]}])
        settings = load_settings()

        report = _run(
            _runner(
                StubSearchWithRoutes({"q1": outcome}),
                evaluator=NoCapabilityEvaluator(settings),
            ),
            path,
        )

        assert report.aggregate_metrics_by_route == {}

    def test_mock_evaluator_is_not_mistaken_for_capable(self, tmp_path) -> None:
        """``Mock()`` 的任何方法都返回真值 —— 必须用 ``is True`` 才不会误判。

        本项目为这个陷阱让 6 个既有用例全红过一次。
        """
        from unittest.mock import Mock

        outcome = SearchOutcome(
            results=[_r("a")], routes={ROUTE_DENSE: [_r("a")], ROUTE_SPARSE: []}
        )
        mock_evaluator = Mock()
        mock_evaluator.evaluate.return_value = {"hit_rate": 1.0, "mrr": 1.0}
        mock_evaluator.zero_metrics.return_value = {"hit_rate": 0.0, "mrr": 0.0}
        mock_evaluator.get_last_degradation_reasons.return_value = {}
        # 刻意**不**配置 supports_retrieval_only —— 让它保持 Mock 默认行为
        # （调用返回真值 Mock）。这正是本用例要防的那个误判。
        path = _golden(tmp_path, [{"query": "q1", "expected": ["a"]}])

        report = _run(
            _runner(StubSearchWithRoutes({"q1": outcome}), evaluator=mock_evaluator), path
        )

        assert report.aggregate_metrics_by_route == {}


# ---------------------------------------------------------------------------
# T-1.3：自检判据
# ---------------------------------------------------------------------------


class TestScoringFailureIsNotZeroFilled:
    """打分抛异常时,分母按**实际参与条数**算,不补零。

    **这条守的是一个我们自己犯过的矛盾**(2026-08-25 修):``_score_routes`` 的
    注释写着「不静默补零 —— 那样这一路会被记成全未命中」,而聚合处却照样
    ``/ total``。于是打分失败的 case 虽然没写键,聚合仍按全样本取均值 ——
    **在聚合层等于补了零**,均值被压低且无任何标记。

    这与 ``metric_integrity`` 确立的规约直接冲突:**分母被收缩时必须披露,
    不能悄悄换掉分子。**

    注意要区分两种「没有数」:
    - 该路检索到空结果 → 计零值,**正常参与分母**(那是真实的检索表现)
    - 打分本身抛异常 → 不参与分母,并记账
    """

    class _FlakyEvaluator(CustomEvaluator):
        """对指定 query 的打分抛错,其余正常。"""

        def __init__(self, settings, fail_on: str) -> None:
            super().__init__(settings)
            self._fail_on = fail_on

        def evaluate_retrieval_only(self, query, retrieved_ids, golden_ids):
            if query == self._fail_on:
                raise RuntimeError("boom")
            return super().evaluate_retrieval_only(
                query=query, retrieved_ids=retrieved_ids, golden_ids=golden_ids
            )

    def _two_case_setup(self, tmp_path):
        outcomes = {
            "q1": SearchOutcome(
                results=[_r("a")], routes={ROUTE_DENSE: [_r("a")], ROUTE_SPARSE: [_r("a")]}
            ),
            "q2": SearchOutcome(
                results=[_r("b")], routes={ROUTE_DENSE: [_r("b")], ROUTE_SPARSE: [_r("b")]}
            ),
        }
        path = _golden(
            tmp_path,
            [{"query": "q1", "expected": ["a"]}, {"query": "q2", "expected": ["b"]}],
        )
        return outcomes, path

    def test_mean_uses_participating_count_not_total(self, tmp_path) -> None:
        """两条 case 全命中、其中一条打分失败 → 均值应为 1.0,不是 0.5。

        补零会给出 0.5 —— 一个看起来像「一半没命中」的数,而真相是
        「一条算不出来」。这两件事的处置完全不同。
        """
        outcomes, path = self._two_case_setup(tmp_path)
        settings = load_settings()

        report = _run(
            _runner(
                StubSearchWithRoutes(outcomes),
                evaluator=self._FlakyEvaluator(settings, fail_on="q1"),
            ),
            path,
        )

        for route in (ROUTE_DENSE, ROUTE_SPARSE):
            assert report.aggregate_metrics_by_route[route]["mrr"] == pytest.approx(1.0), (
                "分母用了 total 而不是实际参与条数 —— 相当于给失败的 case 补了零"
            )

    def test_incomplete_denominator_is_disclosed(self, tmp_path) -> None:
        """分母不足必须在报告里**留痕** —— 否则「2 条的均值」与「1 条的均值」
        长得一模一样。"""
        outcomes, path = self._two_case_setup(tmp_path)
        settings = load_settings()

        report = _run(
            _runner(
                StubSearchWithRoutes(outcomes),
                evaluator=self._FlakyEvaluator(settings, fail_on="q1"),
            ),
            path,
        )

        assert report.aggregate_metrics_by_route[ROUTE_DENSE]["_incomplete_cases"] == 1.0

    def test_no_marker_when_all_cases_participate(self, tmp_path) -> None:
        """全员参与时不输出该标记 —— 健康运行上不制造噪声。"""
        outcomes, path = self._two_case_setup(tmp_path)

        report = _run(_runner(StubSearchWithRoutes(outcomes)), path)

        assert "_incomplete_cases" not in report.aggregate_metrics_by_route[ROUTE_DENSE]

    def test_empty_route_still_counts_toward_denominator(self, tmp_path) -> None:
        """空结果与打分失败必须区别对待:空结果照样计入分母。"""
        outcomes = {
            "q1": SearchOutcome(
                results=[_r("a")], routes={ROUTE_DENSE: [_r("a")], ROUTE_SPARSE: []}
            ),
            "q2": SearchOutcome(
                results=[_r("b")], routes={ROUTE_DENSE: [_r("b")], ROUTE_SPARSE: [_r("b")]}
            ),
        }
        path = _golden(
            tmp_path,
            [{"query": "q1", "expected": ["a"]}, {"query": "q2", "expected": ["b"]}],
        )

        report = _run(_runner(StubSearchWithRoutes(outcomes)), path)

        # sparse:q1 空(0.0)+ q2 命中(1.0),分母 2 → 0.5,且**没有**不足标记
        assert report.aggregate_metrics_by_route[ROUTE_SPARSE]["mrr"] == pytest.approx(0.5)
        assert "_incomplete_cases" not in report.aggregate_metrics_by_route[ROUTE_SPARSE]


class TestSingleRouteEqualsFused:
    """只留一路时，该路的分路径指标必须**等于**此时的融合后指标。

    这是它们在定义上应当相等的情形，也是分路径口径**唯一的自检手段** ——
    没有这条，分路径指标算错了也没人会知道。
    """

    @staticmethod
    def _single_route_outcome(route: str, ids: Sequence[str]) -> SearchOutcome:
        """模拟「其余路权重为 0」：融合后结果就是这一路的结果。"""
        items = [_r(i) for i in ids]
        other = ROUTE_SPARSE if route == ROUTE_DENSE else ROUTE_DENSE
        return SearchOutcome(results=list(items), routes={route: list(items), other: []})

    @pytest.mark.parametrize("route", [ROUTE_DENSE, ROUTE_SPARSE])
    def test_route_metrics_equal_fused_metrics(self, tmp_path, route: str) -> None:
        outcomes = {
            "q1": self._single_route_outcome(route, ["x", "a", "y"]),
            "q2": self._single_route_outcome(route, ["b", "c"]),
        }
        path = _golden(
            tmp_path,
            [
                {"query": "q1", "expected": ["a", "y"]},
                {"query": "q2", "expected": ["c"]},
            ],
        )

        report = _run(_runner(StubSearchWithRoutes(outcomes)), path)

        fused = report.aggregate_metrics
        per_route = report.aggregate_metrics_by_route[route]
        for metric_name in ("hit_rate", "mrr", "recall", "ndcg"):
            assert per_route[metric_name] == pytest.approx(fused[metric_name]), (
                f"{route} 路的 {metric_name} 与融合后不等 —— 分路径口径算错了"
            )


class TestSameFormulaAsFused:
    """分路径与融合后必须共用**同一份**公式实现，不得各写一套。

    两套公式必然漂移，而漂移是静默的：数对不上但谁都不报错。
    """

    def test_evaluate_and_retrieval_only_agree(self) -> None:
        settings = load_settings()
        evaluator = CustomEvaluator(settings)
        retrieved = ["x", "a", "y", "b"]
        golden = ["a", "b"]

        via_evaluate = evaluator.evaluate(
            query="q", retrieved_ids=retrieved, golden_ids=golden
        )
        via_route = evaluator.evaluate_retrieval_only(
            query="q", retrieved_ids=retrieved, golden_ids=golden
        )

        for metric_name in ("hit_rate", "mrr", "recall", "ndcg"):
            assert via_route[metric_name] == pytest.approx(via_evaluate[metric_name])

    def test_empty_retrieved_is_zero_not_error(self) -> None:
        """分路径场景下「这一路没检索到」是正常情形，必须计零而不是抛错。"""
        evaluator = CustomEvaluator(load_settings())

        metrics = evaluator.evaluate_retrieval_only(
            query="q", retrieved_ids=[], golden_ids=["a"]
        )

        assert metrics == {"hit_rate": 0.0, "mrr": 0.0, "recall": 0.0, "ndcg": 0.0}

    def test_empty_golden_still_raises(self) -> None:
        """金标为空是**配置错误**，与「这一路没结果」是两回事，必须报错。"""
        evaluator = CustomEvaluator(load_settings())

        with pytest.raises(ValueError, match="golden_ids"):
            evaluator.evaluate_retrieval_only(query="q", retrieved_ids=["a"], golden_ids=[])
