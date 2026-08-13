"""Unit tests for 后端的分批打分能力与配置化清理。

change: activate-cross-encoder-rerank (T-4.1)

测试范围:

1. ``BaseReranker`` 的默认 opt-out(不支持分批)与两个实现的 opt-in
2. ``CrossEncoderReranker.score_batch`` 返回**原始未归一化**分数 —— 这是分批
   能合并排序的前提
3. ``model`` 的隐式兜底已删除:模型名必须来自配置
4. ``batch_size`` 已配置化(此前硬编码 32)
5. ``LLMReranker.score_batch`` 每条一次调用、解析失败沿用原分数

不加载任何真实模型 / 不调用任何 LLM。
"""

from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import Mock

import pytest

from src.core.settings import RerankSettings, Settings
from src.libs.reranker.base_reranker import BaseReranker, NoneReranker
from src.libs.reranker.cross_encoder_reranker import CrossEncoderReranker
from src.libs.reranker.llm_reranker import LLMReranker

pytestmark = pytest.mark.unit


def _settings(**rerank_kwargs: Any) -> Any:
    defaults: Dict[str, Any] = {
        "backend": "cross_encoder",
        "model": "BAAI/bge-reranker-base",
    }
    defaults.update(rerank_kwargs)
    settings = Mock(spec=Settings)
    settings.rerank = RerankSettings(**defaults)
    return settings


def _candidates(texts: List[str]) -> List[Dict[str, Any]]:
    return [
        {"id": f"c{i}", "text": t, "score": 0.5} for i, t in enumerate(texts)
    ]


class TestBatchScoringOptIn:
    """分批能力是 opt-in 的 —— 默认关闭,已有第三方后端不受影响。"""

    def test_base_class_defaults_to_unsupported(self) -> None:
        """默认 False。声明为 optional 而非 abstractmethod,是为了不让新增
        接口把已有的第三方后端全部变成抽象类实例化失败。"""

        class _Minimal(BaseReranker):
            def rerank(
                self,
                query: str,
                candidates: List[Dict[str, Any]],
                trace: Any = None,
                **kwargs: Any,
            ) -> List[Dict[str, Any]]:
                return list(candidates)

        assert _Minimal().supports_batch_scoring() is False

    def test_base_score_batch_raises_not_implemented(self) -> None:
        class _Minimal(BaseReranker):
            def rerank(
                self,
                query: str,
                candidates: List[Dict[str, Any]],
                trace: Any = None,
                **kwargs: Any,
            ) -> List[Dict[str, Any]]:
                return list(candidates)

        with pytest.raises(NotImplementedError, match="does not support batch scoring"):
            _Minimal().score_batch("q", [])

    def test_none_reranker_does_not_support_batching(self) -> None:
        """``NoneReranker`` 不打分,实现分批没有意义。"""
        assert NoneReranker().supports_batch_scoring() is False

    def test_cross_encoder_supports_batching(self) -> None:
        assert CrossEncoderReranker(settings=_settings()).supports_batch_scoring() is True

    def test_returns_literal_true_not_merely_truthy(self) -> None:
        """必须返回**字面** True。

        Core 层用 ``is True`` 严格判断(否则裸 ``Mock()`` 会被误判成支持分批),
        所以实现方返回真值但非 True 的对象会被当作不支持。
        """
        assert CrossEncoderReranker(settings=_settings()).supports_batch_scoring() is True


class TestCrossEncoderScoreBatch:
    """``score_batch`` 的核心契约:原始分数、等长、顺序对应。"""

    def _reranker(self, raw_scores: List[float]) -> CrossEncoderReranker:
        model = Mock()
        model.predict = Mock(return_value=raw_scores)
        return CrossEncoderReranker(settings=_settings(), model=model)

    def test_returns_one_score_per_candidate_in_order(self) -> None:
        reranker = self._reranker([2.5, -1.0, 7.25])

        scores = reranker.score_batch("q", _candidates(["a", "b", "c"]))

        assert scores == [2.5, -1.0, 7.25]

    def test_scores_are_not_normalized(self) -> None:
        """**不做 min-max 归一化** —— 这是本方法与 ``rerank()`` 的关键差别。

        归一化是按「本次看到的全部候选」算 min/max 的。如果对每一批各自归一化,
        各批的 0~1 就不是同一把尺子,放在一起排序会得出错误名次 —— 而分批的
        全部意义就在于各批分数要能合并排序。
        """
        reranker = self._reranker([2.5, -1.0, 7.25])

        scores = reranker.score_batch("q", _candidates(["a", "b", "c"]))

        # 归一化后应是 [0.42, 0.0, 1.0];原始值必须原样保留
        assert min(scores) == -1.0
        assert max(scores) == 7.25

    def test_negative_scores_preserved(self) -> None:
        """cross-encoder 输出的是 logit,可以是负数,不能被 clamp 掉。"""
        reranker = self._reranker([-3.0, -8.0])

        assert reranker.score_batch("q", _candidates(["a", "b"])) == [-3.0, -8.0]

    def test_empty_batch_returns_empty(self) -> None:
        reranker = self._reranker([])

        assert reranker.score_batch("q", []) == []

    def test_pairs_are_query_plus_text(self) -> None:
        model = Mock()
        model.predict = Mock(return_value=[1.0, 2.0])
        reranker = CrossEncoderReranker(settings=_settings(), model=model)

        reranker.score_batch("what is margin?", _candidates(["about margin", "noise"]))

        pairs = model.predict.call_args[0][0]
        assert pairs == [
            ("what is margin?", "about margin"),
            ("what is margin?", "noise"),
        ]

    def test_predict_batch_size_covers_whole_given_batch(self) -> None:
        """Core 层已切好批,后端一次算完 —— 不要在后端再切一层。"""
        model = Mock()
        model.predict = Mock(return_value=[1.0, 2.0, 3.0])
        reranker = CrossEncoderReranker(settings=_settings(), model=model)

        reranker.score_batch("q", _candidates(["a", "b", "c"]))

        assert model.predict.call_args[1]["batch_size"] == 3


class TestNoImplicitModelDefault:
    """模型名的隐式兜底已删除 —— 本组是本变更的核心清理之一。"""

    def test_model_name_comes_from_config(self) -> None:
        reranker = CrossEncoderReranker(settings=_settings(model="BAAI/bge-reranker-base"))

        assert reranker.model_name == "BAAI/bge-reranker-base"

    def test_no_english_only_fallback(self) -> None:
        """配置里写什么就是什么,不会悄悄替换成 ms-marco。

        此前是 ``getattr(settings.rerank, "model", "cross-encoder/ms-marco-
        MiniLM-L-6-v2")`` —— 配置留空就用一个纯英文模型,对中文语料完全无效
        且不报错。现在由 ``load_settings`` 强制显式配置,走到这里必然有值。
        """
        reranker = CrossEncoderReranker(settings=_settings(model="my/custom-reranker"))

        assert reranker.model_name == "my/custom-reranker"
        assert "ms-marco" not in reranker.model_name


class TestBatchSizeIsConfigurable:
    """``batch_size`` 已配置化(此前硬编码 32,违反宪法原则二)。"""

    def test_reads_from_settings(self) -> None:
        reranker = CrossEncoderReranker(settings=_settings(batch_size=4))

        assert reranker.batch_size == 4

    def test_kwargs_still_override(self) -> None:
        """kwargs 覆盖保留,供测试与特殊场景使用。"""
        reranker = CrossEncoderReranker(settings=_settings(batch_size=4), batch_size=16)

        assert reranker.batch_size == 16

    def test_default_matches_dataclass_default(self) -> None:
        """不传时用 dataclass 默认 8,而不是旧的硬编码 32。"""
        reranker = CrossEncoderReranker(settings=_settings())

        assert reranker.batch_size == 8


class TestLLMScoreBatch:
    """``LLMReranker.score_batch``:每条一次调用,解析失败沿用原分数。"""

    def _reranker(self, responses: List[str]) -> LLMReranker:
        llm = Mock()
        llm.chat = Mock(side_effect=responses)
        llm.get_model_name = Mock(return_value="test-model")
        return LLMReranker(settings=_settings(backend="llm", model="test-model"), llm=llm)

    def test_supports_batching(self) -> None:
        """LLM 后端的超时价值最大 —— 每条一次串行网关调用,40 条就是 40 次往返。"""
        assert self._reranker([]).supports_batch_scoring() is True

    def test_one_call_per_candidate(self) -> None:
        reranker = self._reranker(["8", "3", "10"])

        scores = reranker.score_batch("q", _candidates(["a", "b", "c"]))

        assert reranker.llm.chat.call_count == 3
        assert scores == [0.8, 0.3, 1.0]

    def test_unparseable_response_falls_back_to_original_score(self) -> None:
        """解析失败沿用重排前的分数,而不是打到 0 把该候选踢到末位。"""
        reranker = self._reranker(["7", "no number here"])

        scores = reranker.score_batch("q", _candidates(["a", "b"]))

        assert scores[0] == 0.7
        assert scores[1] == 0.5  # _candidates 里的原始 score

    def test_empty_batch_makes_no_calls(self) -> None:
        reranker = self._reranker([])

        assert reranker.score_batch("q", []) == []
        assert reranker.llm.chat.call_count == 0

    def test_passage_truncated_to_avoid_token_blowup(self) -> None:
        reranker = self._reranker(["5"])
        long_text = "x" * 5000

        reranker.score_batch("q", _candidates([long_text]))

        prompt = reranker.llm.chat.call_args[1]["messages"][0]["content"]
        assert "x" * 2000 in prompt
        assert "x" * 2001 not in prompt
