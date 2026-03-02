"""VectorUpserter 幂等性测试。"""

import pytest
from unittest.mock import Mock, MagicMock
from typing import List
import os

from src.core.types import ChunkRecord
from src.core.settings import load_settings
from src.ingestion.storage.vector_upserter import VectorUpserter


class TestVectorUpserterIdempotency:
    """VectorUpserter 幂等性测试套件。"""

    @pytest.fixture
    def mock_vector_store(self):
        """创建模拟的向量存储后端。"""
        store = Mock()
        store.upsert = Mock(return_value=None)
        return store

    @pytest.fixture
    def settings(self):
        """创建测试配置。"""
        settings = load_settings("config/settings.yaml")
        return settings

    def test_same_chunk_twice_produces_same_id(
        self,
        mock_vector_store,
        settings,
    ):
        """同一 chunk 两次 upsert 产生相同 ID。"""
        upsert = VectorUpserter(settings, vector_store=mock_vector_store)

        record = ChunkRecord(
            id="original_id",
            text="Test content",
            metadata={
                "source_path": "/test/doc.pdf",
                "chunk_index": 0,
            },
            dense_vector=[0.1, 0.2, 0.3],
        )

        upsert.upsert([record])
        upsert.upsert([record])

        assert mock_vector_store.upsert.call_count == 2

        first_call_args = mock_vector_store.upsert.call_args_list[0][0][0]
        second_call_args = mock_vector_store.upsert.call_args_list[1][0][0]

        assert first_call_args[0]["id"] == second_call_args[0]["id"]

    def test_content_change_produces_different_id(
        self,
        mock_vector_store,
        settings,
    ):
        """内容变更时 ID 变更。"""
        upsert = VectorUpserter(settings, vector_store=mock_vector_store)

        record1 = ChunkRecord(
            id="original_id",
            text="Original content",
            metadata={
                "source_path": "/test/doc.pdf",
                "chunk_index": 0,
            },
            dense_vector=[0.1, 0.2, 0.3],
        )

        record2 = ChunkRecord(
            id="original_id",
            text="Modified content",
            metadata={
                "source_path": "/test/doc.pdf",
                "chunk_index": 0,
            },
            dense_vector=[0.1, 0.2, 0.3],
        )

        upsert.upsert([record1])

        first_call_args = mock_vector_store.upsert.call_args_list[0][0][0]
        first_id = first_call_args[0]["id"]

        upsert.upsert([record2])

        second_call_args = mock_vector_store.upsert.call_args_list[1][0][0]
        second_id = second_call_args[0]["id"]

        assert first_id != second_id

    def test_batch_upsert_preserves_order(
        self,
        mock_vector_store,
        settings,
    ):
        """批量 upsert 保持顺序。"""
        upsert = VectorUpserter(settings, vector_store=mock_vector_store)

        records = [
            ChunkRecord(
                id=f"chunk_{i}",
                text=f"Content {i}",
                metadata={
                    "source_path": "/test/doc.pdf",
                    "chunk_index": i,
                },
                dense_vector=[0.1 * i, 0.2 * i, 0.3 * i],
            )
            for i in range(5)
        ]

        upsert.upsert(records)

        call_args = mock_vector_store.upsert.call_args_list[0][0][0]
        assert len(call_args) == 5

        for i, record in enumerate(call_args):
            assert record["id"].startswith(f"/test/doc.pdf_{i}_")

    def test_empty_records_raises_error(self, mock_vector_store, settings):
        """空记录列表抛出错误。"""
        upsert = VectorUpserter(settings, vector_store=mock_vector_store)

        with pytest.raises(ValueError, match="Records list cannot be empty"):
            upsert.upsert([])

    def test_upsert_passes_trace_context(
        self,
        mock_vector_store,
        settings,
    ):
        """upsert 传递 trace 上下文。"""
        upsert = VectorUpserter(settings, vector_store=mock_vector_store)

        mock_trace = Mock()

        record = ChunkRecord(
            id="chunk_001",
            text="Test content",
            metadata={"source_path": "/test/doc.pdf", "chunk_index": 0},
            dense_vector=[0.1, 0.2, 0.3],
        )

        upsert.upsert([record], trace=mock_trace)

        mock_vector_store.upsert.assert_called_once()
        call_kwargs = mock_vector_store.upsert.call_args[1]
        assert call_kwargs.get("trace") == mock_trace

    def test_metadata_preserved(
        self,
        mock_vector_store,
        settings,
    ):
        """元数据被正确保留。"""
        upsert = VectorUpserter(settings, vector_store=mock_vector_store)

        record = ChunkRecord(
            id="chunk_001",
            text="Test content",
            metadata={
                "source_path": "/test/doc.pdf",
                "chunk_index": 0,
                "title": "Test Document",
                "custom_field": "custom_value",
            },
            dense_vector=[0.1, 0.2, 0.3],
        )

        upsert.upsert([record])

        call_args = mock_vector_store.upsert.call_args_list[0][0][0]
        stored_metadata = call_args[0]["metadata"]

        assert stored_metadata["source_path"] == "/test/doc.pdf"
        assert stored_metadata["chunk_index"] == 0
        assert stored_metadata["title"] == "Test Document"
        assert stored_metadata["custom_field"] == "custom_value"

    def test_sparse_vector_included(
        self,
        mock_vector_store,
        settings,
    ):
        """稀疏向量被包含在元数据中。"""
        upsert = VectorUpserter(settings, vector_store=mock_vector_store)

        record = ChunkRecord(
            id="chunk_001",
            text="Test content",
            metadata={"source_path": "/test/doc.pdf", "chunk_index": 0},
            dense_vector=[0.1, 0.2, 0.3],
            sparse_vector={"term1": 0.5, "term2": 0.3},
        )

        upsert.upsert([record])

        call_args = mock_vector_store.upsert.call_args_list[0][0][0]
        stored_metadata = call_args[0]["metadata"]

        assert "sparse_vector" in stored_metadata
        assert stored_metadata["sparse_vector"]["term1"] == 0.5
        assert stored_metadata["sparse_vector"]["term2"] == 0.3

    def test_stable_id_format(self, mock_vector_store, settings):
        """稳定 ID 格式正确。"""
        upsert = VectorUpserter(settings, vector_store=mock_vector_store)

        record = ChunkRecord(
            id="chunk_001",
            text="Test content for stable ID",
            metadata={
                "source_path": "/path/to/document.pdf",
                "chunk_index": 5,
            },
            dense_vector=[0.1, 0.2, 0.3],
        )

        stable_id = upsert._generate_stable_id(record)

        assert stable_id.startswith("/path/to/document.pdf_5_")
        assert len(stable_id) > 30
