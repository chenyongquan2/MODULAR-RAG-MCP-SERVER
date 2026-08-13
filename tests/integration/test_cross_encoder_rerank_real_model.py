"""集成测试:cross-encoder 重排的**真实模型**装配。

change: activate-cross-encoder-rerank (T-5.1)

**为什么必须有这一层**:本项目的 4 个 rerank 单元测试全部通过依赖注入喂 mock
模型,对「依赖是否可用、真实模型能否加载、分数是否真的可排序」这一层完全无感
—— 于是「代码能力完备、运行能力为零」的状态维持了很久而没人发现。更极端的
例子是 ``test_model_loading_raises_import_error_if_library_missing``:它压根
没模拟「库缺失」,之所以一直通过只是因为依赖真的没装,依赖装上后它反而去真连
HuggingFace 下载模型。

本文件是唯一会真实加载权重的测试。因此:

- 标 ``integration`` marker,**不进** ``pytest tests/unit`` 默认路径
- 依赖或权重不可用时整体 skip,不让 CI 因为下不到 1GB 权重而红
- 用 ``BAAI/bge-reranker-base``(中英双语),不是纯英文的 ms-marco

运行方式::

    .venv/Scripts/python.exe -m pytest tests/integration/test_cross_encoder_rerank_real_model.py -v -m integration

国内首次运行需设镜像(权重约 1.08 GB,一次性)::

    $env:HF_ENDPOINT="https://hf-mirror.com"
"""

from __future__ import annotations

import importlib.util
from typing import Any, Dict, List

import pytest

from src.core.query_engine.reranker import Reranker
from src.core.settings import RerankSettings
from src.core.types import RetrievalResult

pytestmark = pytest.mark.integration


MODEL = "BAAI/bge-reranker-base"


# ── skip 条件:依赖不可用,或权重未落盘且拉不下来 ──────────────────────────

_HAS_DEP = importlib.util.find_spec("sentence_transformers") is not None

skip_no_dep = pytest.mark.skipif(
    not _HAS_DEP,
    reason='sentence-transformers 未安装（pip install -e ".[rerank]"）',
)


@pytest.fixture(scope="module")
def real_model() -> Any:
    """真实加载一次模型,module 级复用 —— 加载很贵,不要每个测试重来。"""
    if not _HAS_DEP:
        pytest.skip("sentence-transformers 未安装")

    from sentence_transformers import CrossEncoder

    try:
        return CrossEncoder(MODEL, max_length=512)
    except Exception as e:  # noqa: BLE001
        pytest.skip(
            f"无法加载 {MODEL}（权重约 1.08GB，首次需联网）: {e}. "
            "国内可设 HF_ENDPOINT=https://hf-mirror.com"
        )


class _Settings:
    """最小 Settings 替身,用真实 RerankSettings 以免与配置结构漂移。"""

    def __init__(self, **kwargs: Any) -> None:
        defaults: Dict[str, Any] = {
            "backend": "cross_encoder",
            "model": MODEL,
            "top_m": 50,
            "timeout_sec": 60.0,
            "batch_size": 8,
        }
        defaults.update(kwargs)
        self.rerank = RerankSettings(**defaults)


class _RecordingTrace:
    def __init__(self) -> None:
        self.stages: Dict[str, Dict[str, Any]] = {}

    def start_stage(self, name: str) -> None:
        pass

    def finish_stage(self, name: str, payload: Dict[str, Any]) -> None:
        self.stages[name] = payload


# ── 语料:同一份 MT5 文档的中英双版本(与本项目真实语料形态一致)──────────

_QUERY_ZH = "如何配置保证金计算方式？"
_QUERY_EN = "How to configure the margin calculation mode?"

_RELEVANT_ZH = "保证金计算方式在 group 设置中通过 margin mode 字段配置，支持 forex、CFD 等多种模式。"
_RELEVANT_EN = (
    "The margin calculation mode is configured per group via the margin mode "
    "field, supporting forex, CFD and other modes."
)
_NOISE_ZH = "服务器日志文件默认保存在 logs 目录下，按日期轮转，保留 30 天。"
_NOISE_EN = (
    "Daily reports are generated at midnight server time and emailed to the "
    "address configured in the notifications section."
)


def _candidates(texts: List[str]) -> List[RetrievalResult]:
    """构造候选,分数刻意**递减**且与相关性相反。

    这样如果重排没真正生效(原序返回),相关项会留在末位 —— 断言就会失败。
    换句话说:这些测试无法靠「什么都不做」通过。
    """
    return [
        RetrievalResult(
            chunk_id=f"c{i}", score=1.0 - i * 0.1, text=t, metadata={}
        )
        for i, t in enumerate(texts)
    ]


@skip_no_dep
class TestRealModelLoads:
    """依赖与权重真的可用。"""

    def test_model_loads(self, real_model: Any) -> None:
        assert real_model is not None

    def test_model_produces_orderable_scores(self, real_model: Any) -> None:
        """相关项得分必须高于噪声项 —— 模型真的在判断相关性,不是返回常量。"""
        scores = real_model.predict(
            [(_QUERY_ZH, _RELEVANT_ZH), (_QUERY_ZH, _NOISE_ZH)],
            show_progress_bar=False,
        )
        assert float(scores[0]) > float(scores[1])


@skip_no_dep
class TestBackendWithRealModel:
    """``CrossEncoderReranker`` 装上真实模型后的行为。"""

    def _backend(self, real_model: Any) -> Any:
        from src.libs.reranker.cross_encoder_reranker import CrossEncoderReranker

        return CrossEncoderReranker(settings=_Settings(), model=real_model)

    def test_score_batch_returns_raw_orderable_scores(self, real_model: Any) -> None:
        backend = self._backend(real_model)

        scores = backend.score_batch(
            _QUERY_ZH,
            [
                {"id": "a", "text": _NOISE_ZH, "score": 0.9},
                {"id": "b", "text": _RELEVANT_ZH, "score": 0.1},
            ],
        )

        assert len(scores) == 2
        assert scores[1] > scores[0]  # 相关项分更高

    def test_backend_reports_real_model_name(self, real_model: Any) -> None:
        backend = self._backend(real_model)

        assert backend.model_name == MODEL
        assert backend.get_backend_name() == "cross_encoder"


@skip_no_dep
class TestEndToEndRerankChangesOrder:
    """Core 层 + 真实模型:重排必须真的改变名次。"""

    def _reranker(self, real_model: Any, **kwargs: Any) -> Reranker:
        from src.libs.reranker.cross_encoder_reranker import CrossEncoderReranker

        backend = CrossEncoderReranker(
            settings=_Settings(**kwargs), model=real_model
        )
        return Reranker(_Settings(**kwargs), reranker_backend=backend)

    def test_chinese_relevant_promoted_to_top(self, real_model: Any) -> None:
        """中文:相关项从末位被提到首位。"""
        reranker = self._reranker(real_model)
        # 原序:噪声在前(分数高),相关项在后
        candidates = _candidates([_NOISE_ZH, _NOISE_EN, _RELEVANT_ZH])

        results = reranker.rerank(_QUERY_ZH, candidates)

        assert results[0].text == _RELEVANT_ZH
        assert results[0].chunk_id == "c2"  # 原本排第 3

    def test_english_relevant_promoted_to_top(self, real_model: Any) -> None:
        """英文:同样有效(模型是双语的,不是只对一种语言起作用)。"""
        reranker = self._reranker(real_model)
        candidates = _candidates([_NOISE_EN, _NOISE_ZH, _RELEVANT_EN])

        results = reranker.rerank(_QUERY_EN, candidates)

        assert results[0].text == _RELEVANT_EN

    def test_no_candidate_lost(self, real_model: Any) -> None:
        reranker = self._reranker(real_model)
        candidates = _candidates([_NOISE_ZH, _RELEVANT_ZH, _NOISE_EN, _RELEVANT_EN])

        results = reranker.rerank(_QUERY_ZH, candidates)

        assert len(results) == 4
        assert {r.chunk_id for r in results} == {"c0", "c1", "c2", "c3"}


@skip_no_dep
class TestTraceProvesRerankActuallyRan:
    """**本文件最重要的一组** —— trace 是「重排真的跑了」的唯一可靠判据。

    proposal 把「跑通」的验收信号定为 trace 而非任何分数指标,理由是:分数变化
    可以归因于任何环节(embedding / 融合权重 / 语料 / Judge),只有 trace 能证明
    重排这一步真的执行了。这组测试就是那个信号的可执行形式。
    """

    def _reranker(self, real_model: Any) -> Reranker:
        from src.libs.reranker.cross_encoder_reranker import CrossEncoderReranker

        backend = CrossEncoderReranker(settings=_Settings(), model=real_model)
        return Reranker(_Settings(), reranker_backend=backend)

    def test_trace_shows_not_fallback(self, real_model: Any) -> None:
        reranker = self._reranker(real_model)
        trace = _RecordingTrace()

        reranker.rerank(_QUERY_ZH, _candidates([_NOISE_ZH, _RELEVANT_ZH]), trace=trace)

        payload = trace.stages["rerank"]
        assert payload["fallback"] is False, (
            "fallback=True 意味着重排静默降级了 —— 这正是本变更要消灭的状态"
        )

    def test_trace_carries_the_real_model_name(self, real_model: Any) -> None:
        """模型名必须是实际加载的模型,不是类名、不是配置里的字符串。"""
        reranker = self._reranker(real_model)
        trace = _RecordingTrace()

        reranker.rerank(_QUERY_ZH, _candidates([_NOISE_ZH, _RELEVANT_ZH]), trace=trace)

        assert trace.stages["rerank"]["model"] == MODEL
        assert trace.stages["rerank"]["backend"] == "cross_encoder"

    def test_trace_shows_enabled_and_not_timed_out(self, real_model: Any) -> None:
        reranker = self._reranker(real_model)
        trace = _RecordingTrace()

        reranker.rerank(_QUERY_ZH, _candidates([_NOISE_ZH, _RELEVANT_ZH]), trace=trace)

        payload = trace.stages["rerank"]
        assert payload["enabled"] is True
        assert payload["timed_out"] is False

    def test_trace_records_real_elapsed_time(self, real_model: Any) -> None:
        """真实推理耗时 > 0 —— mock 测不出这一点,而 T-6.2 要用这个数。"""
        reranker = self._reranker(real_model)
        trace = _RecordingTrace()

        reranker.rerank(_QUERY_ZH, _candidates([_NOISE_ZH, _RELEVANT_ZH]), trace=trace)

        assert trace.stages["rerank"]["elapsed_sec"] > 0

    def test_rerank_scores_land_in_metadata(self, real_model: Any) -> None:
        reranker = self._reranker(real_model)

        results = reranker.rerank(_QUERY_ZH, _candidates([_NOISE_ZH, _RELEVANT_ZH]))

        assert all("rerank_score" in r.metadata for r in results)
        assert all(r.metadata["reranked_by"] == "cross_encoder" for r in results)


@skip_no_dep
class TestTopMWithRealModel:
    """``top_m`` 截断在真实模型下同样生效。"""

    def test_only_top_m_participate(self, real_model: Any) -> None:
        from src.libs.reranker.cross_encoder_reranker import CrossEncoderReranker

        settings = _Settings(top_m=2)
        backend = CrossEncoderReranker(settings=settings, model=real_model)
        reranker = Reranker(settings, reranker_backend=backend)

        # 相关项放在第 3 位 —— top_m=2 时它不参与重排,不该被提上来
        candidates = _candidates([_NOISE_ZH, _NOISE_EN, _RELEVANT_ZH])
        trace = _RecordingTrace()

        results = reranker.rerank(_QUERY_ZH, candidates, trace=trace)

        assert trace.stages["rerank"]["reranked_count"] == 2
        assert trace.stages["rerank"]["carried_over_count"] == 1
        assert results[-1].text == _RELEVANT_ZH  # 仍在末位
        assert len(results) == 3


@skip_no_dep
class TestCrossLingualScoringIsConservative:
    """已知局限:跨语言 pair 的分数被显著压低(T-1.1 实测发现)。

    本项目语料是同一份 MT5 文档的中英双版本,所以这不是理论问题:中文 query
    命中英文 chunk 时重排会把它往下压。把它固化成测试是为了让这个局限**显式**
    —— T-6.1 的 A/B 若在中文金标上出现负增益,要先排查这里,而不是直接归因于
    「重排无效」。
    """

    def test_same_language_scores_higher_than_cross_language(
        self, real_model: Any
    ) -> None:
        scores = real_model.predict(
            [
                (_QUERY_ZH, _RELEVANT_ZH),  # 同语言,语义相关
                (_QUERY_ZH, _RELEVANT_EN),  # 跨语言,语义等价
            ],
            show_progress_bar=False,
        )
        same_lang, cross_lang = float(scores[0]), float(scores[1])

        assert same_lang > cross_lang, (
            "若这条不再成立说明模型的跨语言对齐变好了 —— 是好事,"
            "但需要重新评估 A/B 结论中关于跨语言压分的那部分"
        )

    def test_cross_language_still_beats_noise(self, real_model: Any) -> None:
        """跨语言虽被压低,但仍应高于无关内容 —— 否则语义对齐就完全失效了。"""
        scores = real_model.predict(
            [(_QUERY_ZH, _RELEVANT_EN), (_QUERY_ZH, _NOISE_ZH)],
            show_progress_bar=False,
        )
        assert float(scores[0]) > float(scores[1])
