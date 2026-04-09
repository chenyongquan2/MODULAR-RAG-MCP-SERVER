"""Tests for Pipeline progress callback functionality.

测试 IngestionPipeline 的 on_progress 回调功能：
1. 验证各阶段调用回调时参数正确
2. 验证 on_progress=None 时不影响现有行为
3. 验证失败时回调的行为
"""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from typing import List

from src.ingestion.pipeline import IngestionPipeline
from src.core.types import Document, Chunk, ChunkRecord
from src.core.settings import Settings


@pytest.fixture
def mock_settings():
    """Create mock settings with minimal configuration."""
    settings = MagicMock(spec=Settings)
    settings.ingestion = MagicMock()
    settings.ingestion.chunk_size = 500
    settings.ingestion.chunk_overlap = 50
    settings.embedding = MagicMock()
    settings.embedding.provider = "mock"
    return settings


@pytest.fixture
def mock_loader():
    """Create mock loader that returns a sample document."""
    loader = MagicMock()
    loader.load.return_value = Document(
        id="doc_test_123",
        text="这是一段测试文本。" * 100,
        metadata={
            "source_path": "/test/document.md",
            "title": "Test Document",
        },
    )
    return loader


@pytest.fixture
def mock_chunker():
    """Create mock chunker that returns sample chunks."""
    chunker = MagicMock()
    chunker.split_document.return_value = [
        Chunk(
            id="chunk_001",
            text="这是第一个 chunk 的内容。",
            metadata={"source_path": "/test/document.md"},
            source_ref="doc_test_123:0:50",
        ),
        Chunk(
            id="chunk_002",
            text="这是第二个 chunk 的内容。",
            metadata={"source_path": "/test/document.md"},
            source_ref="doc_test_123:50:100",
        ),
    ]
    return chunker


@pytest.fixture
def mock_dense_encoder():
    """Create mock dense encoder."""
    encoder = MagicMock()
    encoder.encode.return_value = [
        ChunkRecord(
            id="chunk_001",
            text="这是第一个 chunk 的内容。",
            metadata={"source_path": "/test/document.md"},
            dense_vector=[0.1] * 768,
        ),
        ChunkRecord(
            id="chunk_002",
            text="这是第二个 chunk 的内容。",
            metadata={"source_path": "/test/document.md"},
            dense_vector=[0.2] * 768,
        ),
    ]
    return encoder


@pytest.fixture
def mock_sparse_encoder():
    """Create mock sparse encoder."""
    encoder = MagicMock()
    encoder.encode.return_value = [
        ChunkRecord(
            id="chunk_001",
            text="这是第一个 chunk 的内容。",
            metadata={},
            sparse_vector={"token_1": 0.5, "token_2": 0.3},
        ),
        ChunkRecord(
            id="chunk_002",
            text="这是第二个 chunk 的内容。",
            metadata={},
            sparse_vector={"token_3": 0.4, "token_4": 0.6},
        ),
    ]
    return encoder


@pytest.fixture
def mock_integrity_checker():
    """Create mock integrity checker that allows processing."""
    checker = MagicMock()
    checker.compute_sha256.return_value = "test_hash_123"
    checker.should_skip.return_value = False
    return checker


@pytest.fixture
def mock_transform():
    """Create mock transform."""
    transform = MagicMock()
    transform.transform = lambda chunks, trace=None: chunks
    return transform


class TestPipelineProgressCallback:
    """测试 Pipeline 的 on_progress 回调功能。"""

    def test_progress_callback_called_for_all_stages(
        self,
        mock_settings,
        mock_loader,
        mock_chunker,
        mock_dense_encoder,
        mock_sparse_encoder,
        mock_integrity_checker,
        mock_transform,
        tmp_path,
    ):
        """验证所有阶段都调用了回调函数，且参数正确。

        预期调用序列：
        - integrity: (0, 1) 开始，(1, 1) 完成
        - load: (0, 1) 开始，(1, 1) 完成
        - split: (0, 1) 开始，(1, 1) 完成
        - transform: (0, 1) 开始，(1, 1) 完成
        - encode: (0, 1) 开始，(1, 1) 完成
        - store: (0, 1) 开始，(1, 1) 完成
        """
        progress_calls: List[tuple] = []

        def on_progress(stage_name: str, current: int, total: int):
            progress_calls.append((stage_name, current, total))

        pipeline = IngestionPipeline(
            settings=mock_settings,
            collection="test_collection",
            loader=mock_loader,
            chunker=mock_chunker,
            transform=mock_transform,
            metadata_enricher=MagicMock(transform=lambda chunks, **kwargs: chunks),
            image_captioner=MagicMock(transform=lambda chunks, **kwargs: chunks),
            text_enricher=MagicMock(transform=lambda chunks, **kwargs: chunks),
            dense_encoder=mock_dense_encoder,
            sparse_encoder=mock_sparse_encoder,
            vector_upserter=MagicMock(upsert=lambda records, trace=None: None),
            bm25_indexer=MagicMock(build=lambda records, collection=None: None, save=lambda collection=None: "/tmp/bm25.idx"),
            image_storage=MagicMock(),
            integrity_checker=mock_integrity_checker,
        )

        # 创建测试文件 (使用 .md 扩展名)
        test_file = tmp_path / "test.md"
        test_file.write_text("# Test Document\n\nThis is test content.")

        # Mock _get_loader 返回我们的 mock_loader
        with patch.object(pipeline, '_get_loader', return_value=mock_loader):
            # 运行 pipeline with callback
            result = pipeline.run(
                str(test_file),
                force=True,
                on_progress=on_progress,
            )

        # 验证结果
        assert result["status"] == "success"

        # 验证回调被调用
        # 每个阶段有 2 次调用（开始 + 完成），共 6 个阶段 = 12 次调用
        assert len(progress_calls) == 12

        # 验证各阶段的调用序列
        expected_stages = ["integrity", "load", "split", "transform", "encode", "store"]

        for i, expected_stage in enumerate(expected_stages):
            # 开始调用: (stage, 0, 1)
            start_idx = i * 2
            assert progress_calls[start_idx] == (expected_stage, 0, 1), \
                f"Stage {expected_stage} start call mismatch: {progress_calls[start_idx]}"

            # 完成调用: (stage, 1, 1)
            end_idx = i * 2 + 1
            assert progress_calls[end_idx] == (expected_stage, 1, 1), \
                f"Stage {expected_stage} end call mismatch: {progress_calls[end_idx]}"

    def test_progress_callback_none_does_not_affect_pipeline(
        self,
        mock_settings,
        mock_loader,
        mock_chunker,
        mock_dense_encoder,
        mock_sparse_encoder,
        mock_integrity_checker,
        mock_transform,
        tmp_path,
    ):
        """验证 on_progress=None 时 pipeline 正常运行，不影响现有行为。"""
        pipeline = IngestionPipeline(
            settings=mock_settings,
            collection="test_collection",
            loader=mock_loader,
            chunker=mock_chunker,
            transform=mock_transform,
            metadata_enricher=MagicMock(transform=lambda chunks, **kwargs: chunks),
            image_captioner=MagicMock(transform=lambda chunks, **kwargs: chunks),
            text_enricher=MagicMock(transform=lambda chunks, **kwargs: chunks),
            dense_encoder=mock_dense_encoder,
            sparse_encoder=mock_sparse_encoder,
            vector_upserter=MagicMock(upsert=lambda records, trace=None: None),
            bm25_indexer=MagicMock(build=lambda records, collection=None: None, save=lambda collection=None: "/tmp/bm25.idx"),
            image_storage=MagicMock(),
            integrity_checker=mock_integrity_checker,
        )

        # 创建测试文件 (使用 .md 扩展名)
        test_file = tmp_path / "test.md"
        test_file.write_text("# Test Document\n\nThis is test content.")

        # Mock _get_loader 返回我们的 mock_loader
        with patch.object(pipeline, '_get_loader', return_value=mock_loader):
            # 运行 pipeline without callback (默认 None)
            result = pipeline.run(str(test_file), force=True)

        # 验证 pipeline 正常完成
        assert result["status"] == "success"
        assert "stages" in result
        assert "load" in result["stages"]
        assert "split" in result["stages"]

    def test_progress_callback_with_failure(
        self,
        mock_settings,
        mock_integrity_checker,
        tmp_path,
    ):
        """验证失败时回调的行为。

        当某个阶段失败时，该阶段的"完成"回调不会被调用，
        只会有该阶段开始的回调。
        """
        progress_calls: List[tuple] = []

        def on_progress(stage_name: str, current: int, total: int):
            progress_calls.append((stage_name, current, total))

        # 创建一个会抛出异常的 mock loader
        mock_loader = MagicMock()
        mock_loader.load.side_effect = RuntimeError("Load failed")

        pipeline = IngestionPipeline(
            settings=mock_settings,
            collection="test_collection",
            loader=mock_loader,  # 注入 mock loader
            integrity_checker=mock_integrity_checker,
            image_storage=MagicMock(),
        )

        # 使用 patch 覆盖 _get_loader 方法，返回我们的 mock_loader
        with patch.object(pipeline, '_get_loader', return_value=mock_loader):
            # 创建测试文件 (使用 .md 扩展名避免 PDF 解析)
            test_file = tmp_path / "test.md"
            test_file.write_text("# Test Document\n\nThis is test content.")

            # 运行 pipeline，预期抛出异常
            with pytest.raises(RuntimeError, match="Load failed"):
                pipeline.run(
                    str(test_file),
                    force=True,
                    on_progress=on_progress,
                )

        # 验证回调序列：
        # - integrity 开始 (0, 1)
        # - integrity 完成 (1, 1)
        # - load 开始 (0, 1)  <- load 阶段开始
        # 但没有 load 完成，因为异常被抛出
        assert ("integrity", 0, 1) in progress_calls
        assert ("integrity", 1, 1) in progress_calls
        assert ("load", 0, 1) in progress_calls  # load 开始被调用
        assert ("load", 1, 1) not in progress_calls  # load 完成未被调用

    def test_progress_callback_with_skip(
        self,
        mock_settings,
        mock_integrity_checker,
        tmp_path,
    ):
        """验证跳过已处理文件时的回调行为。"""
        progress_calls: List[tuple] = []

        def on_progress(stage_name: str, current: int, total: int):
            progress_calls.append((stage_name, current, total))

        # 让 integrity checker 返回"应跳过"
        mock_integrity_checker.compute_sha256.return_value = "test_hash_123"
        mock_integrity_checker.should_skip.return_value = True  # 文件已处理

        pipeline = IngestionPipeline(
            settings=mock_settings,
            collection="test_collection",
            integrity_checker=mock_integrity_checker,
            image_storage=MagicMock(),
        )

        # 创建测试文件
        test_file = tmp_path / "test.md"
        test_file.write_text("# Test Document\n\nThis is test content.")

        # 运行 pipeline，预期返回 skipped 状态
        result = pipeline.run(
            str(test_file),
            force=False,  # 不强制重新处理
            on_progress=on_progress,
        )

        # 验证结果为 skipped
        assert result["status"] == "skipped"

        # 验证只有 integrity 开始回调被调用，没有完成回调（因为跳过）
        assert ("integrity", 0, 1) in progress_calls
        # 注意：integrity 完成不会被调用，因为抛出了 SKIP 异常

    def test_progress_callback_signature_types(
        self,
        mock_settings,
        mock_loader,
        mock_chunker,
        mock_dense_encoder,
        mock_sparse_encoder,
        mock_integrity_checker,
        mock_transform,
        tmp_path,
    ):
        """验证回调签名中的参数类型正确。"""
        received_args = []

        def on_progress(stage_name: str, current: int, total: int):
            received_args.append({
                "stage_name": stage_name,
                "current": current,
                "total": total,
            })

        pipeline = IngestionPipeline(
            settings=mock_settings,
            collection="test_collection",
            loader=mock_loader,
            chunker=mock_chunker,
            transform=mock_transform,
            metadata_enricher=MagicMock(transform=lambda chunks, **kwargs: chunks),
            image_captioner=MagicMock(transform=lambda chunks, **kwargs: chunks),
            text_enricher=MagicMock(transform=lambda chunks, **kwargs: chunks),
            dense_encoder=mock_dense_encoder,
            sparse_encoder=mock_sparse_encoder,
            vector_upserter=MagicMock(upsert=lambda records, trace=None: None),
            bm25_indexer=MagicMock(build=lambda records, collection=None: None, save=lambda collection=None: "/tmp/bm25.idx"),
            image_storage=MagicMock(),
            integrity_checker=mock_integrity_checker,
        )

        # 创建测试文件 (使用 .md 扩展名)
        test_file = tmp_path / "test.md"
        test_file.write_text("# Test Document\n\nThis is test content.")

        # Mock _get_loader 返回我们的 mock_loader
        with patch.object(pipeline, '_get_loader', return_value=mock_loader):
            # 运行 pipeline
            result = pipeline.run(
                str(test_file),
                force=True,
                on_progress=on_progress,
            )

        assert result["status"] == "success"

        # 验证所有参数类型
        for args in received_args:
            assert isinstance(args["stage_name"], str), \
                f"stage_name should be str, got {type(args['stage_name'])}"
            assert isinstance(args["current"], int), \
                f"current should be int, got {type(args['current'])}"
            assert isinstance(args["total"], int), \
                f"total should be int, got {type(args['total'])}"
            assert args["total"] == 1, \
                f"total should be 1, got {args['total']}"
            assert args["current"] in [0, 1], \
                f"current should be 0 or 1, got {args['current']}"
