"""Fusion (RRF) 单元测试。"""

import pytest

from src.core.query_engine.fusion import Fusion
from src.core.types import RetrievalResult


class TestFusion:
    """Fusion 类的单元测试。"""

    def test_fuse_empty_lists(self):
        """测试空结果列表融合。"""
        fusion = Fusion()
        result = fusion.fuse([])
        assert result == []

    def test_fuse_single_list(self):
        """测试单列表融合。"""
        fusion = Fusion()
        results = [
            RetrievalResult(chunk_id="1", score=0.9, text="text1", metadata={}),
            RetrievalResult(chunk_id="2", score=0.8, text="text2", metadata={}),
        ]
        fused = fusion.fuse([results])
        assert len(fused) == 2
        assert fused[0].chunk_id == "1"

    def test_fuse_two_lists_different_order(self):
        """测试两个不同顺序的列表融合。"""
        fusion = Fusion()
        dense = [
            RetrievalResult(chunk_id="1", score=0.9, text="text1", metadata={}),
            RetrievalResult(chunk_id="2", score=0.8, text="text2", metadata={}),
        ]
        sparse = [
            RetrievalResult(chunk_id="2", score=0.7, text="text2", metadata={}),
            RetrievalResult(chunk_id="1", score=0.6, text="text1", metadata={}),
        ]
        fused = fusion.fuse([dense, sparse])
        assert fused[0].chunk_id in ["1", "2"]
        assert fused[1].chunk_id in ["1", "2"]

    def test_fuse_duplicate_chunk_ids(self):
        """测试重复 chunk_id 的融合。"""
        fusion = Fusion(k=60)
        dense = [
            RetrievalResult(chunk_id="1", score=0.9, text="text1", metadata={}),
            RetrievalResult(chunk_id="2", score=0.8, text="text2", metadata={}),
        ]
        sparse = [
            RetrievalResult(chunk_id="1", score=0.7, text="text1_v2", metadata={}),
        ]
        fused = fusion.fuse([dense, sparse])
        assert len(fused) == 2

    def test_fuse_with_top_k(self):
        """测试 top_k 参数。"""
        fusion = Fusion()
        results = [
            RetrievalResult(chunk_id=str(i), score=1.0 - i * 0.1, text=f"text{i}", metadata={})
            for i in range(10)
        ]
        fused = fusion.fuse([results], top_k=3)
        assert len(fused) == 3

    def test_fuse_preserves_metadata(self):
        """测试融合后保留最高分结果的 metadata。"""
        fusion = Fusion()
        dense = [
            RetrievalResult(chunk_id="1", score=0.9, text="text1", metadata={"source": "dense"}),
        ]
        sparse = [
            RetrievalResult(chunk_id="1", score=0.7, text="text1", metadata={"source": "sparse"}),
        ]
        fused = fusion.fuse([dense, sparse])
        assert fused[0].metadata["source"] == "dense"

    def test_fuse_custom_k(self):
        """测试自定义 k 参数。"""
        fusion_aggressive = Fusion(k=1)
        fusion_conservative = Fusion(k=100)

        results1 = [
            RetrievalResult(chunk_id="1", score=0.9, text="text1", metadata={}),
            RetrievalResult(chunk_id="2", score=0.8, text="text2", metadata={}),
        ]
        results2 = [
            RetrievalResult(chunk_id="2", score=0.7, text="text2", metadata={}),
            RetrievalResult(chunk_id="1", score=0.6, text="text1", metadata={}),
        ]

        fused_aggressive = fusion_aggressive.fuse([results1, results2])
        fused_conservative = fusion_conservative.fuse([results1, results2])

        assert len(fused_aggressive) == 2
        assert len(fused_conservative) == 2

    def test_fuse_empty_result_in_list(self):
        """测试包含空列表的融合。"""
        fusion = Fusion()
        results = [
            RetrievalResult(chunk_id="1", score=0.9, text="text1", metadata={}),
        ]
        fused = fusion.fuse([results, []])
        assert len(fused) == 1

    def test_fuse_ignores_empty_chunk_id(self):
        """测试忽略空 chunk_id。"""
        fusion = Fusion()
        results = [
            RetrievalResult(chunk_id="", score=0.9, text="text1", metadata={}),
            RetrievalResult(chunk_id="1", score=0.8, text="text2", metadata={}),
        ]
        fused = fusion.fuse([results])
        assert len(fused) == 1
        assert fused[0].chunk_id == "1"
