"""Unit tests for BatchedInMemoryDocumentStore (Feature-001 closeout, 2026-04-28).

测试范围:
- ``add_nodes()`` 把 N 次单条 ``embed_text`` 改为一次批量 ``embed_documents``
  (核心性能优化, 实测 5000 nodes embed 阶段 50 min → 1 min, 60-100x)
- 已 embed 的 node(``embedding != None``)不应再次出现在 batch 调用里
- keyphrase 提取仍为 per-node Executor 并发(LLM-bound, 必要)
- 父类(InMemoryDocumentStore)的落库语义保持不变

为什么单元测试关键(refs constitution § VII NON-NEGOTIABLE):
我们覆盖了 RAGAS 内部 add_nodes,RAGAS 升级时如果父类签名 / 行为变化,本测试
能在 CI 早抓到回归,避免合成跑到 1 小时才发现 nodes.embedding 没被赋值。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

pytestmark = pytest.mark.unit


def _make_node(text: str, embedding=None, keyphrases=None, doc_id: str = "n1"):
    """构造一个最小 RAGAS Node mock(只满足 add_nodes 的字段访问)。"""
    n = MagicMock()
    n.page_content = text
    n.embedding = embedding
    n.keyphrases = keyphrases if keyphrases is not None else []
    n.doc_id = doc_id
    return n


def _build_batched_docstore_with_mocks(
    embed_documents_return: list[list[float]],
    extract_return: list,
):
    """构造一个 BatchedInMemoryDocumentStore 实例,内部依赖全 mock。

    注意:延迟 import,因 _ragas_wrappers 用 __getattr__ 在第一次访问时构造类。
    """
    from src.observability.evaluation._ragas_wrappers import (
        BatchedInMemoryDocumentStore,
    )

    # mock embeddings: embed_documents 返回固定 vectors
    embeddings = MagicMock()
    embeddings.embed_documents = MagicMock(return_value=embed_documents_return)

    # mock extractor: extract 是 async(RAGAS Executor 用 await 调,必须 AsyncMock)
    extractor = MagicMock()
    extractor.extract = AsyncMock(return_value=extract_return)

    # mock splitter(父类 __init__ 需要)
    splitter = MagicMock()

    store = BatchedInMemoryDocumentStore(
        splitter=splitter,
        embeddings=embeddings,
        extractor=extractor,
    )
    return store, embeddings, extractor


class TestBatchedAddNodes:
    """核心:add_nodes 的批量行为。"""

    def test_embed_documents_called_once_with_all_node_texts(self) -> None:
        """3 个未 embed 的 node → embed_documents 调 1 次,参数是 3 个 text 的列表。

        这是优化的核心:旧 RAGAS 会通过 Executor 串发 3 次 embed_text 单条调用。
        """
        store, embeddings, extractor = _build_batched_docstore_with_mocks(
            embed_documents_return=[[0.1, 0.2], [0.3, 0.4], [0.5, 0.6]],
            extract_return=["kp1", "kp2"],
        )
        nodes = [
            _make_node("text 1", doc_id="n1"),
            _make_node("text 2", doc_id="n2"),
            _make_node("text 3", doc_id="n3"),
        ]

        store.add_nodes(nodes, show_progress=False)

        # 关键断言:embed_documents 只调 1 次,batch 参数含 3 个 text
        assert embeddings.embed_documents.call_count == 1
        called_texts = embeddings.embed_documents.call_args.args[0]
        assert called_texts == ["text 1", "text 2", "text 3"]

    def test_embedding_results_assigned_to_each_node(self) -> None:
        """embed_documents 返回的 vectors 必须按顺序写到 each node.embedding。"""
        vectors = [[0.1, 0.2], [0.3, 0.4]]
        store, _, _ = _build_batched_docstore_with_mocks(
            embed_documents_return=vectors,
            extract_return=["kp"],
        )
        nodes = [
            _make_node("a", doc_id="n1"),
            _make_node("b", doc_id="n2"),
        ]

        store.add_nodes(nodes, show_progress=False)

        assert nodes[0].embedding == [0.1, 0.2]
        assert nodes[1].embedding == [0.3, 0.4]

    def test_already_embedded_nodes_skipped_from_batch(self) -> None:
        """已 embed 的 node(embedding != None)不应出现在 embed_documents 入参。

        防止重复嵌入浪费 token + 错位赋值 bug。
        """
        store, embeddings, _ = _build_batched_docstore_with_mocks(
            embed_documents_return=[[0.5, 0.5]],  # 只 1 个 vector,因只 1 个 node 需 embed
            extract_return=["kp"],
        )
        nodes = [
            _make_node("a", embedding=[0.9, 0.9], doc_id="n1"),  # 已 embed
            _make_node("b", embedding=None, doc_id="n2"),         # 待 embed
        ]

        store.add_nodes(nodes, show_progress=False)

        # batch 只含未 embed 的那个
        called_texts = embeddings.embed_documents.call_args.args[0]
        assert called_texts == ["b"]
        # 已 embed 的 node 保持原 embedding 不变
        assert nodes[0].embedding == [0.9, 0.9]
        # 待 embed 的拿到新 vector
        assert nodes[1].embedding == [0.5, 0.5]

    def test_no_embed_call_when_all_nodes_pre_embedded(self) -> None:
        """全部 node 已 embed → embed_documents 不应被调用(零开销)。"""
        store, embeddings, _ = _build_batched_docstore_with_mocks(
            embed_documents_return=[],
            extract_return=["kp"],
        )
        nodes = [
            _make_node("a", embedding=[0.1], doc_id="n1"),
            _make_node("b", embedding=[0.2], doc_id="n2"),
        ]

        store.add_nodes(nodes, show_progress=False)

        assert embeddings.embed_documents.call_count == 0


class TestBatchedKeyphraseExtraction:
    """keyphrase 提取仍 per-node 并发(LLM-bound, 不能批);验证仍正常工作。"""

    def test_extract_called_per_node(self) -> None:
        """3 个 node 都需 keyphrase → extract 调 3 次(Executor 并发,但调用次数仍 3)。"""
        store, _, extractor = _build_batched_docstore_with_mocks(
            embed_documents_return=[[0.1], [0.1], [0.1]],
            extract_return=["a", "b"],  # 每次返 keyphrases list
        )
        nodes = [
            _make_node(f"text {i}", doc_id=f"n{i}")
            for i in range(3)
        ]

        store.add_nodes(nodes, show_progress=False)

        # extract 至少调 3 次(每个 node 一次,Executor 并发执行)
        assert extractor.extract.call_count == 3

    def test_already_extracted_nodes_skipped(self) -> None:
        """已有 keyphrases 的 node 不再调 extract(避免重算 LLM)。"""
        store, _, extractor = _build_batched_docstore_with_mocks(
            embed_documents_return=[[0.1], [0.1]],
            extract_return=["new"],
        )
        nodes = [
            _make_node("a", keyphrases=["already"], doc_id="n1"),  # 已抽
            _make_node("b", keyphrases=[], doc_id="n2"),            # 待抽
        ]

        store.add_nodes(nodes, show_progress=False)

        # 只 1 次 extract
        assert extractor.extract.call_count == 1


class TestBatchedDocstoreLazyClass:
    """``BatchedInMemoryDocumentStore`` 通过模块级 __getattr__ 延迟构建。"""

    def test_class_constructed_on_first_access(self) -> None:
        """第一次 import 触发类构建;后续 import 拿到同一个类对象。"""
        from src.observability.evaluation._ragas_wrappers import (
            BatchedInMemoryDocumentStore as cls1,
        )
        from src.observability.evaluation._ragas_wrappers import (
            BatchedInMemoryDocumentStore as cls2,
        )

        assert cls1 is cls2
        # 是 RAGAS InMemoryDocumentStore 的子类
        from ragas.testset.docstore import InMemoryDocumentStore
        assert issubclass(cls1, InMemoryDocumentStore)
