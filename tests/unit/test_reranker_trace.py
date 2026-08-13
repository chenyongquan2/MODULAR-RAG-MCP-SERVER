"""Unit tests for rerank 阶段的 trace 打点。

change: activate-cross-encoder-rerank (T-3.3)

**为什么这组测试是本变更的验收信号本身**:重排是否真的执行了,**无法从分数
变化推断** —— 分数可能因任何环节变化(embedding、融合权重、语料、Judge)。
trace 是唯一可靠的判据。所以 proposal 把「跑通」的判据定为 trace 中
``fallback: false`` + 真实模型名,而不是任何分数指标。

规格要求三种非正常路径用**互不重叠的字段**区分,不能用同一个标记表达多种
含义:

- ``enabled=False``  → 压根没配重排,什么都没发生
- ``fallback=True``  → 后端炸了,原序返回(是**错**)
- ``timed_out=True`` → 打分没跑完,部分生效(是**慢**)

不触发任何模型加载 / LLM 调用。
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

import pytest

from src.core.query_engine.reranker import Reranker
from src.core.settings import RerankSettings
from src.core.types import RetrievalResult

pytestmark = pytest.mark.unit


class _FakeSettings:
    def __init__(self, **rerank_kwargs: Any) -> None:
        self.rerank = RerankSettings(**rerank_kwargs)


class _RecordingTrace:
    def __init__(self) -> None:
        self.stages: Dict[str, Dict[str, Any]] = {}
        self.started: List[str] = []

    def start_stage(self, name: str) -> None:
        self.started.append(name)

    def finish_stage(self, name: str, payload: Dict[str, Any]) -> None:
        self.stages[name] = payload


class _HealthyBackend:
    """正常工作的分批后端,自报后端名与模型名。"""

    def __init__(self, model: str = "BAAI/bge-reranker-base") -> None:
        self.model_name = model

    def supports_batch_scoring(self) -> bool:
        return True

    def score_batch(self, query: str, candidates: List[Dict[str, Any]]) -> List[float]:
        return [float(len(candidates) - i) for i in range(len(candidates))]

    def get_backend_name(self) -> str:
        return "cross_encoder"


class _BoomBackend:
    def supports_batch_scoring(self) -> bool:
        return True

    def score_batch(self, query: str, candidates: List[Dict[str, Any]]) -> List[float]:
        raise RuntimeError("inference exploded")

    def get_backend_name(self) -> str:
        return "cross_encoder"


class _SlowBackend:
    def __init__(self, sleep_per_batch: float) -> None:
        self.sleep_per_batch = sleep_per_batch
        self.model_name = "BAAI/bge-reranker-base"

    def supports_batch_scoring(self) -> bool:
        return True

    def score_batch(self, query: str, candidates: List[Dict[str, Any]]) -> List[float]:
        time.sleep(self.sleep_per_batch)
        return [1.0] * len(candidates)

    def get_backend_name(self) -> str:
        return "cross_encoder"


def _candidates(n: int) -> List[RetrievalResult]:
    return [
        RetrievalResult(
            chunk_id=f"c{i}", score=1.0 - i * 0.01, text=f"passage {i}", metadata={}
        )
        for i in range(n)
    ]


def _run(impl: Any, n: int = 10, **rerank_kwargs: Any) -> Dict[str, Any]:
    """跑一次重排并返回 trace 载荷。

    ``impl`` 是注入的后端实例;``rerank_kwargs`` 是 ``RerankSettings`` 的字段
    (含 ``backend``,故位置参数不能也叫 backend —— 会撞名)。
    """
    kwargs: Dict[str, Any] = {"top_m": 50, "batch_size": 4, "timeout_sec": 30.0}
    kwargs.update(rerank_kwargs)
    reranker = Reranker(_FakeSettings(**kwargs), reranker_backend=impl)
    trace = _RecordingTrace()
    reranker.rerank("q", _candidates(n), trace=trace)
    return trace.stages["rerank"]


class TestHealthyRerankTrace:
    """重排真实执行:降级与超时都为假,模型名是实际模型。"""

    def test_flags_all_clear(self) -> None:
        payload = _run(_HealthyBackend())

        assert payload["enabled"] is True
        assert payload["fallback"] is False
        assert payload["timed_out"] is False

    def test_backend_and_model_recorded(self) -> None:
        """这两个字段是判别静默降级的核心信号。"""
        payload = _run(_HealthyBackend(model="BAAI/bge-reranker-base"))

        assert payload["backend"] == "cross_encoder"
        assert payload["model"] == "BAAI/bge-reranker-base"

    def test_backend_name_comes_from_backend_not_config(self) -> None:
        """标识从后端自报,不从配置读。

        配置写了什么与实际装配了什么可能不一致(后端是可注入的),trace 要记的
        是**实际发生的事**。这里配置故意留 backend=none,但注入的是 cross_encoder。
        """
        payload = _run(_HealthyBackend(), backend="none")

        assert payload["backend"] == "cross_encoder"
        assert payload["enabled"] is True

    def test_counts_recorded(self) -> None:
        payload = _run(_HealthyBackend())

        assert payload["input_count"] == 10
        assert payload["output_count"] == 10
        assert payload["scored_count"] == 10

    def test_elapsed_recorded(self) -> None:
        payload = _run(_HealthyBackend())

        assert "elapsed_sec" in payload
        assert payload["elapsed_sec"] >= 0


class TestDisabledRerankTrace:
    """未启用重排:必须明确体现为未重排,而非缺失或伪装成已重排。"""

    def test_none_backend_marked_not_enabled(self) -> None:
        from src.libs.reranker.base_reranker import NoneReranker

        payload = _run(NoneReranker(), backend="none")

        assert payload["enabled"] is False
        assert payload["backend"] == "none"

    def test_none_backend_has_no_model(self) -> None:
        from src.libs.reranker.base_reranker import NoneReranker

        payload = _run(NoneReranker(), backend="none")

        assert payload["model"] == "n/a"

    def test_none_backend_is_not_a_fallback_or_timeout(self) -> None:
        """「没配重排」不等于「重排失败」,也不等于「超时」。

        这是三态区分的要点:此前只有 ``fallback`` 一个标记时,无从区分
        「压根没配」与「配了但炸了」—— 而这两者的处置完全不同。
        """
        from src.libs.reranker.base_reranker import NoneReranker

        payload = _run(NoneReranker(), backend="none")

        assert payload["fallback"] is False
        assert payload["timed_out"] is False


class TestFallbackTrace:
    """运行期降级:fallback 为真,且不谎报超时。"""

    def test_fallback_marked(self) -> None:
        payload = _run(_BoomBackend())

        assert payload["fallback"] is True

    def test_fallback_is_not_timeout(self) -> None:
        """降级是「错」,超时是「慢」—— 不能共用一个标记。"""
        payload = _run(_BoomBackend())

        assert payload["timed_out"] is False

    def test_fallback_still_reports_enabled(self) -> None:
        """降级不改变「用户确实配了重排」这个事实。

        若降级时把 enabled 也置假,就无从区分「没配」与「配了但失败」,
        静默降级又会变得不可见 —— 那正是本变更要消灭的东西。
        """
        payload = _run(_BoomBackend())

        assert payload["enabled"] is True
        assert payload["backend"] == "cross_encoder"

    def test_fallback_preserves_all_candidates_in_counts(self) -> None:
        payload = _run(_BoomBackend())

        assert payload["input_count"] == 10
        assert payload["output_count"] == 10


class TestTimeoutTrace:
    """超时:timed_out 为真,且不谎报降级。"""

    def test_timeout_marked(self) -> None:
        payload = _run(_SlowBackend(0.1), batch_size=2, timeout_sec=0.05)

        assert payload["timed_out"] is True

    def test_timeout_is_not_fallback(self) -> None:
        """超时时部分结果**是生效的**,标成降级会让人以为整批白跑了。"""
        payload = _run(_SlowBackend(0.1), batch_size=2, timeout_sec=0.05)

        assert payload["fallback"] is False

    def test_timeout_reports_partial_scored_count(self) -> None:
        payload = _run(_SlowBackend(0.1), batch_size=2, timeout_sec=0.05)

        assert payload["scored_count"] == 2
        assert payload["output_count"] == 10  # 一条都没丢

    def test_timeout_records_the_limit_that_was_hit(self) -> None:
        payload = _run(_SlowBackend(0.1), batch_size=2, timeout_sec=0.05)

        assert payload["timeout_sec"] == 0.05


class TestThreeStatesAreMutuallyDistinguishable:
    """规格要求:三种情况能相互区分,不用同一个标记表达多种含义。"""

    def test_each_state_has_a_unique_signature(self) -> None:
        from src.libs.reranker.base_reranker import NoneReranker

        def signature(payload: Dict[str, Any]) -> tuple[bool, bool, bool]:
            return (payload["enabled"], payload["fallback"], payload["timed_out"])

        healthy = signature(_run(_HealthyBackend()))
        disabled = signature(_run(NoneReranker(), backend="none"))
        degraded = signature(_run(_BoomBackend()))
        expired = signature(_run(_SlowBackend(0.1), batch_size=2, timeout_sec=0.05))

        # 四种签名两两不同 —— 这就是「互不重叠」的可测形式
        assert len({healthy, disabled, degraded, expired}) == 4

    def test_stage_is_always_recorded(self) -> None:
        """任何路径下 rerank 阶段都要出现在 trace 里,不能悄悄缺席。"""
        from src.libs.reranker.base_reranker import NoneReranker

        for impl, overrides in [
            (_HealthyBackend(), {}),
            (NoneReranker(), {"backend": "none"}),
            (_BoomBackend(), {}),
            (_SlowBackend(0.1), {"batch_size": 2, "timeout_sec": 0.05}),
        ]:
            kwargs: Dict[str, Any] = {
                "top_m": 50,
                "batch_size": 4,
                "timeout_sec": 30.0,
            }
            kwargs.update(overrides)
            reranker = Reranker(_FakeSettings(**kwargs), reranker_backend=impl)
            trace = _RecordingTrace()
            reranker.rerank("q", _candidates(6), trace=trace)

            assert "rerank" in trace.stages
            assert trace.started == ["rerank"]


class TestObservabilityNeverBreaksTheQuery:
    """可观测性字段取不到时,绝不能让查询失败。"""

    def test_backend_without_get_backend_name(self) -> None:
        class _Nameless:
            def supports_batch_scoring(self) -> bool:
                return False

            def rerank(
                self,
                query: str,
                candidates: List[Dict[str, Any]],
                trace: Optional[Any] = None,
                **kwargs: Any,
            ) -> List[Dict[str, Any]]:
                return list(candidates)

        payload = _run(_Nameless())

        # 回退到类名,不抛异常
        assert payload["backend"] == "_Nameless"
        assert payload["model"] == "n/a"

    def test_backend_whose_name_getter_raises(self) -> None:
        class _Hostile:
            def supports_batch_scoring(self) -> bool:
                return False

            def get_backend_name(self) -> str:
                raise RuntimeError("nope")

            def rerank(
                self,
                query: str,
                candidates: List[Dict[str, Any]],
                trace: Optional[Any] = None,
                **kwargs: Any,
            ) -> List[Dict[str, Any]]:
                return list(candidates)

        payload = _run(_Hostile())

        assert payload["backend"] == "_Hostile"
        assert payload["fallback"] is False  # 主流程未受影响
