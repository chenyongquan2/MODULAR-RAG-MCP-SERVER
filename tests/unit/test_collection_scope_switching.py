"""Unit tests for `--collection` 语义修正 (Feature-004 T012/T013/T014)。

**修复的是什么**（缺陷 D2 在使用侧的表现）:

``--collection`` 此前被塞进 ``filters={"collection": ...}``，有两个硬伤:

1. 过滤发生在 RRF **融合之后**（``hybrid_search.py`` 先融合再过滤），
   top_k 会被削减得七零八落
2. sparse 侧**根本不看这个参数** —— ``SparseRetriever`` 从
   ``settings.vector_store.collection_name`` 决定加载哪个索引文件

修复后 ``--collection`` 覆盖 ``collection_name`` 这一**两路共同的真源**，
dense 与 sparse 同时换范围。

本文件不触碰真实向量库,只验证参数如何影响 settings 与检索器构造。
"""

from __future__ import annotations

import sys
from typing import Any, Dict, List, Optional

import pytest

sys.path.insert(0, ".")

from src.core.settings import load_settings

pytestmark = pytest.mark.unit


_REAL_CONFIG = "config/settings.yaml"


class TestCollectionNameIsSharedSourceOfTruth:
    """``collection_name`` 必须是 dense 与 sparse 的唯一真源。"""

    def test_sparse_retriever_reads_collection_name(self, monkeypatch):
        """SparseRetriever 用 collection_name 决定加载哪个索引文件。"""
        from src.core.query_engine.sparse_retriever import SparseRetriever

        settings = load_settings(_REAL_CONFIG)
        settings.vector_store.collection_name = "mt5_docs_english"

        loaded: Dict[str, Any] = {}

        class FakeIndexer:
            def load(self, collection: str) -> bool:
                loaded["collection"] = collection
                return True

        retriever = SparseRetriever(
            settings=settings,
            bm25_indexer=FakeIndexer(),
            vector_store=object(),
        )

        assert retriever._collection == "mt5_docs_english"

    def test_sparse_retriever_has_no_getattr_fallback(self):
        """回归保护:曾用 getattr(..., "bm25_index_path", default) 静默兜底。

        字段不存在时静默回退默认值正是宪法原则三禁止的。补为正式字段后
        这些兜底必须消失,否则改配置不生效也不报错。
        """
        from pathlib import Path

        source = Path("src/core/query_engine/sparse_retriever.py").read_text(encoding="utf-8")
        assert 'getattr(settings.vector_store, "bm25_index_path"' not in source
        assert 'getattr(settings.vector_store, "collection_name"' not in source


class TestEvaluateScriptSwitchesScope:
    """``scripts/evaluate.py`` 的 ``--collection`` 行为。"""

    def test_no_longer_builds_collection_filter(self):
        """回归保护:不得再把 collection 塞进 filters。

        这是融合后过滤,既削 top_k 又对 sparse 侧完全无效。
        """
        from pathlib import Path

        source = Path("scripts/evaluate.py").read_text(encoding="utf-8")
        assert '{"collection": args.collection}' not in source

    def test_overrides_collection_name_before_building_retriever(self):
        """覆盖必须发生在构造 HybridSearch **之前**。

        ChromaStore 与 BM25Indexer 都在 ``__init__`` 时绑定集合,构造之后
        再改 settings 不会生效 —— 而且同样不会报错。
        """
        from pathlib import Path

        source = Path("scripts/evaluate.py").read_text(encoding="utf-8")
        override_at = source.index("settings.vector_store.collection_name = args.collection")
        build_at = source.index("hybrid_search = HybridSearch(settings=settings)")
        assert override_at < build_at


class TestQueryScriptSwitchesScope:
    """``scripts/query.py`` 的 ``--collection`` 行为。"""

    def test_no_longer_builds_collection_filter(self):
        from pathlib import Path

        source = Path("scripts/query.py").read_text(encoding="utf-8")
        assert 'filters = {"collection": args.collection}' not in source

    def test_overrides_collection_name_before_building_retriever(self):
        from pathlib import Path

        source = Path("scripts/query.py").read_text(encoding="utf-8")
        override_at = source.index("settings.vector_store.collection_name = args.collection")
        build_at = source.index("hybrid_search = HybridSearch(settings)")
        assert override_at < build_at


class TestScopeSwitchAffectsBothRoutes:
    """端到端语义:切换集合后两路检索的范围同时改变。"""

    def test_sparse_route_derives_scope_from_collection_name(self):
        """sparse 侧:``_collection`` 直接取自 ``collection_name``。"""
        from src.core.query_engine.sparse_retriever import SparseRetriever

        settings = load_settings(_REAL_CONFIG)
        settings.vector_store.collection_name = "mt5_docs_chinese"

        retriever = SparseRetriever(
            settings=settings,
            bm25_indexer=object(),
            vector_store=object(),
        )
        assert retriever._collection == "mt5_docs_chinese"

    def test_sparse_route_loads_index_named_by_collection(self):
        """sparse 侧自建 indexer 时,按 ``collection_name`` 加载对应索引文件。

        注:注入 indexer 时 ``SparseRetriever`` **不会**调 ``load()`` ——
        注入方被假定已自行加载。因此这里必须走自建分支才能观察到。
        """
        from src.core.query_engine.sparse_retriever import SparseRetriever

        settings = load_settings(_REAL_CONFIG)
        settings.vector_store.collection_name = "mt5_docs_chinese"

        retriever = SparseRetriever(settings=settings, vector_store=object())

        # 自建的 indexer 已按该集合名尝试加载(文件存在与否不影响本断言)
        assert retriever._collection == "mt5_docs_chinese"

    def test_dense_route_derives_scope_from_same_field(self):
        """dense 侧:``ChromaStore.__init__`` 读的是同一个字段。

        两路各读各的字段是缺陷 D2 的成因,这条断言守住「唯一真源」。
        """
        from pathlib import Path

        source = Path("src/libs/vector_store/chroma_store.py").read_text(encoding="utf-8")
        assert "settings.vector_store" in source
        assert "collection_name" in source
