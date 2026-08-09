"""Unit tests for OpenAIEmbedding 的模型规格查表 (Feature-004 追加)。

**背景**：2026-08-09 网关把 ``text-embedding-3-small`` 整体下架，切换到
``qwen/text-embedding-v4``。切换时发现规格查表有一个静默失效：

网关把模型暴露成带 vendor 前缀的 ``qwen/text-embedding-v4``，而
``MODEL_DIMENSIONS`` / ``MODEL_BATCH_SIZES`` 里登记的是裸名
``text-embedding-v4``。两处 ``dict.get(self.model, <默认值>)`` 都会 miss，
于是：

- 维度被当成 **1536**（实际 1024）→ 向量库以错误维度建集合，问题要到检索时
  才以"维度不匹配"暴露，那时已经写进去几万条向量
- 批大小被当成 **100**（Qwen v4 硬上限是 10）→ 整批调用直接失败

两个都是"查不到就用默认值"这一类最难排查的 bug —— 它们不报错。

本文件守住修复：归一化查表 + 未知模型硬失败。

不发起任何真实 API 调用。
"""

from __future__ import annotations

import sys

import pytest

sys.path.insert(0, ".")

from src.core.settings import load_settings
from src.libs.embedding.openai_embedding import OpenAIEmbedding

pytestmark = pytest.mark.unit


_REAL_CONFIG = "config/settings.yaml"


def _embedder(model: str) -> OpenAIEmbedding:
    settings = load_settings(_REAL_CONFIG)
    settings.embedding.model = model
    return OpenAIEmbedding(settings)


class TestModelIdNormalization:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("qwen/text-embedding-v4", "text-embedding-v4"),
            ("text-embedding-v4", "text-embedding-v4"),
            ("text-embedding-3-small", "text-embedding-3-small"),
            ("vendor/sub/model-x", "model-x"),
        ],
    )
    def test_strips_vendor_prefix(self, raw, expected):
        assert OpenAIEmbedding._normalize_model_id(raw) == expected


class TestDimensionLookup:
    def test_prefixed_model_resolves_to_correct_dimension(self):
        """核心回归:带前缀的模型必须查到 1024,而不是静默回落 1536。"""
        assert _embedder("qwen/text-embedding-v4").get_dimension() == 1024

    def test_bare_model_still_works(self):
        assert _embedder("text-embedding-v4").get_dimension() == 1024

    def test_legacy_model_unchanged(self):
        assert _embedder("text-embedding-3-small").get_dimension() == 1536

    def test_unknown_model_raises_instead_of_defaulting(self):
        """未知模型必须硬失败。

        此前返回默认 1536,会让向量库以错误维度建集合 —— 而错误要到检索时
        才暴露,那时几万条向量已经写进去了。宪法原则三:禁止静默回退默认值。
        """
        with pytest.raises(ValueError, match="Unknown embedding model"):
            _embedder("vendor/never-heard-of-it").get_dimension()

    def test_error_message_lists_known_models(self):
        """报错要能直接指导修复。"""
        with pytest.raises(ValueError, match="text-embedding-v4"):
            _embedder("nope").get_dimension()


class TestBatchSizeLookup:
    def test_prefixed_model_resolves_to_hard_limit(self):
        """Qwen v4 硬上限是 10;拿到默认 100 会让整批调用失败。"""
        assert _embedder("qwen/text-embedding-v4").get_max_batch_size() == 10

    def test_instance_batch_size_matches_lookup(self):
        """``__init__`` 与 ``get_max_batch_size()`` 必须走同一条查表路径。

        此前两处各查一次且都用裸 ``self.model``,前缀会双双 miss ——
        典型的"同一逻辑写两遍然后漂移"。
        """
        embedder = _embedder("qwen/text-embedding-v4")
        assert embedder.batch_size == embedder.get_max_batch_size() == 10

    def test_legacy_model_batch_size_unchanged(self):
        assert _embedder("text-embedding-3-small").get_max_batch_size() == 500

    def test_unknown_model_falls_back_to_conservative_default(self):
        """批大小未知时回落 100 是可接受的 —— 它只影响吞吐,不会像维度那样
        污染数据。若上限更小,API 会明确报错而非静默写坏。
        """
        assert _embedder("vendor/unknown").get_max_batch_size() == 100


class TestConfiguredModelIsUsable:
    """当前 settings.yaml 配的模型必须在规格表里登记齐全。"""

    def test_configured_model_has_registered_dimension(self):
        settings = load_settings(_REAL_CONFIG)
        if settings.embedding.provider != "openai":
            pytest.skip("当前 provider 不是 openai")
        # 不抛异常即通过
        assert OpenAIEmbedding(settings).get_dimension() > 0

    def test_configured_model_has_registered_batch_size(self):
        settings = load_settings(_REAL_CONFIG)
        if settings.embedding.provider != "openai":
            pytest.skip("当前 provider 不是 openai")
        assert OpenAIEmbedding(settings).get_max_batch_size() > 0
