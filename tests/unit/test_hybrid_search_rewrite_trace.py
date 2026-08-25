"""Unit tests for 改写留痕 (T-2.4)。

change: per-route-metrics-and-synonym-rewrite

**为什么留痕是硬要求而不是「顺手加的日志」**：改写**没生效**与改写**生效但无
收益**，在最终指标上可能表现完全相同 —— 两次评估的分数一模一样。没有痕迹就
无法区分这两件事，而它们的处置完全相反：前者去查配置（是不是 strategy 没打开、
词表路径写错了），后者去改词表（词条覆盖面不够）。

这与本项目在 `rerank.top_m` 上踩的坑是同一件事：**一个不留痕的功能，
「它没生效」和「它生效了但没用」长得一模一样。**

不联网、不调用任何模型。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

import pytest
import yaml

from src.core.query_engine.fusion import Fusion
from src.core.query_engine.hybrid_search import HybridSearch
from src.core.query_engine.query_processor import QueryProcessor
from src.core.types import RetrievalResult
from src.libs.query_rewriter import SynonymQueryRewriter

pytestmark = pytest.mark.unit


class StubRetriever:
    def retrieve(self, *args: Any, **kwargs: Any) -> List[RetrievalResult]:
        return [RetrievalResult(chunk_id="a", score=1.0, text="t-a", metadata={})]


class PassthroughReranker:
    def rerank(self, query: str, results: Sequence[RetrievalResult], trace: Any = None):
        return list(results)


class RecordingTrace:
    """只记录 finish_stage payload 的 trace 替身。"""

    def __init__(self) -> None:
        self.stages: Dict[str, Dict[str, Any]] = {}

    def start_stage(self, name: str) -> None:
        pass

    def finish_stage(self, name: str, payload: Optional[Dict[str, Any]] = None) -> None:
        self.stages[name] = dict(payload or {})


def _build(processor: Optional[QueryProcessor] = None) -> HybridSearch:
    return HybridSearch(
        settings=None,
        query_processor=processor,
        dense_retriever=StubRetriever(),
        sparse_retriever=StubRetriever(),
        fusion=Fusion(k=60),
        reranker=PassthroughReranker(),
    )


def _synonym_processor(tmp_path, mapping) -> QueryProcessor:
    path = tmp_path / "syn.yaml"
    path.write_text(yaml.safe_dump(mapping, allow_unicode=True), encoding="utf-8")
    return QueryProcessor(
        query_rewriter=SynonymQueryRewriter(settings=None, synonym_dict=str(path))
    )


class TestRewriteIsTraced:
    def test_payload_present_when_disabled(self) -> None:
        """未改写时**同样留痕** —— 省略会让「没启用」与「启用了但没匹配到」
        无法区分。"""
        trace = RecordingTrace()

        _build().search("configure llm", top_k=3, trace=trace)

        rewrite = trace.stages["query_processing"]["rewrite"]
        assert rewrite["strategy"] == "none"
        assert rewrite["added_count"] == 0

    def test_payload_records_strategy_and_before_after(self, tmp_path) -> None:
        trace = RecordingTrace()
        processor = _synonym_processor(tmp_path, {"stoploss": ["sl"]})

        _build(processor).search("set stoploss", top_k=3, trace=trace)

        rewrite = trace.stages["query_processing"]["rewrite"]
        assert rewrite["strategy"] == "synonym"
        assert "stoploss" in rewrite["original_keywords"]
        assert "sl" not in rewrite["original_keywords"]
        assert "sl" in rewrite["expanded_keywords"]
        assert rewrite["added_count"] >= 1

    def test_enabled_but_no_match_is_distinguishable_from_disabled(self, tmp_path) -> None:
        """两者的 ``added_count`` 都是 0 —— 只有 ``strategy`` 能区分。

        这正是留痕存在的理由：没有它，这两种状态在任何数据上都一模一样。
        """
        disabled_trace = RecordingTrace()
        _build().search("configure llm", top_k=3, trace=disabled_trace)

        enabled_trace = RecordingTrace()
        processor = _synonym_processor(tmp_path, {"止损": ["SL"]})
        _build(processor).search("configure llm", top_k=3, trace=enabled_trace)

        disabled = disabled_trace.stages["query_processing"]["rewrite"]
        enabled = enabled_trace.stages["query_processing"]["rewrite"]

        assert disabled["added_count"] == enabled["added_count"] == 0
        assert disabled["strategy"] == "none"
        assert enabled["strategy"] == "synonym"

    def test_existing_payload_fields_survive(self) -> None:
        """既有的 query / keywords 字段不能被挤掉 —— 老的看板还在读它们。"""
        trace = RecordingTrace()

        _build().search("configure llm", top_k=3, trace=trace)

        stage = trace.stages["query_processing"]
        assert stage["method"] == "query_processor"
        assert stage["query"] == "configure llm"
        assert stage["keywords"] == ["configure", "llm"]

    def test_no_trace_does_not_break_search(self, tmp_path) -> None:
        """不传 trace 时照常检索 —— 留痕不是必需路径。"""
        processor = _synonym_processor(tmp_path, {"stoploss": ["sl"]})

        results = _build(processor).search("set stoploss", top_k=3)

        assert [r.chunk_id for r in results] == ["a"]

    def test_keywords_field_reflects_expansion(self, tmp_path) -> None:
        """打点里的 ``keywords`` 是**送进 sparse 的最终词** —— 含扩展词。

        否则事后看 trace 会以为 sparse 用的是原始关键词，那就白留痕了。
        """
        trace = RecordingTrace()
        processor = _synonym_processor(tmp_path, {"stoploss": ["sl"]})

        _build(processor).search("set stoploss", top_k=3, trace=trace)

        assert "sl" in trace.stages["query_processing"]["keywords"]
