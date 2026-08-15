"""Unit tests for adapt 产物校验与缓存治理。

change: expand-chinese-golden-set (T-2.1 / T-2.2 / T-2.3)

**本文件守的是本变更的核心机制**：让「适配静默不生效」无法发生。

实测背景（2026-08-14）：RAGAS 的 `adapt(language=chinese)` 在**不抛任何异常**
的情况下返回未翻译的英文提示词，并被写进磁盘缓存永久固化。五个「中文」文件的
CJK 字符数全部为 0。现有的 fail-fast 只捕获异常，对这种形态完全无效 ——
**「没报错」不等于「做对了」**。

不 import ragas、不联网：用假的 adapt 产物（写进临时目录的 json 文件）覆盖
全部路径。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.core.settings import (
    EvaluationSettings,
    JudgeLLMSettings,
    SynthesisSettings,
)
from src.observability.evaluation.testset_synthesizer import (
    ADAPT_METADATA_FILENAME,
    RAGAS_LANGUAGE_BY_CODE,
    _cached_adapt_is_usable,
    _validate_adapt_output,
    _write_adapt_metadata,
)

pytestmark = pytest.mark.unit


# 真实形态：RAGAS 声称已翻译成中文，实则一个汉字都没有
_UNTRANSLATED = json.dumps(
    {
        "name": "answer_formulate",
        "instruction": "Answer the question using the information from the given "
        "context. Output verdict as '1' if answer is present.",
    },
    ensure_ascii=False,
)
_TRANSLATED = json.dumps(
    {
        "name": "answer_formulate",
        "instruction": "使用给定上下文中的信息回答问题。如果上下文中存在答案则"
        "输出判定为 1，不存在则输出 -1。",
    },
    ensure_ascii=False,
)


class _FakeSettings:
    def __init__(self, threshold: float = 0.05, judge_model: str = "glm-x") -> None:
        self.evaluation = EvaluationSettings()
        self.evaluation.synthesis = SynthesisSettings(
            adapt_language_ratio_min=threshold
        )
        self.evaluation.judge_llm = JudgeLLMSettings(
            provider="glm", model=judge_model
        )


def _cache(tmp_path: Path, files: dict[str, str]) -> Path:
    d = tmp_path / "chinese"
    d.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (d / name).write_text(content, encoding="utf-8")
    return d


class TestValidateAdaptOutput:
    """T-2.1：校验产物本身，而不是等异常。"""

    def test_untranslated_output_fails(self, tmp_path: Path) -> None:
        """**核心场景** —— 这正是实测发生过的形态。"""
        cache = _cache(tmp_path, {"answer_formulate.json": _UNTRANSLATED})

        checks = _validate_adapt_output(cache, "zh", _FakeSettings())

        assert checks["answer_formulate.json"].passed is False
        assert checks["answer_formulate.json"].ratio == 0.0

    def test_translated_output_passes(self, tmp_path: Path) -> None:
        cache = _cache(tmp_path, {"answer_formulate.json": _TRANSLATED})

        checks = _validate_adapt_output(cache, "zh", _FakeSettings())

        assert checks["answer_formulate.json"].passed is True

    def test_mixed_files_reported_individually(self, tmp_path: Path) -> None:
        """逐文件报，因为部分翻译也是失败 —— 但要看得出是哪几个没翻。"""
        cache = _cache(
            tmp_path,
            {"a.json": _TRANSLATED, "b.json": _UNTRANSLATED, "c.json": _TRANSLATED},
        )

        checks = _validate_adapt_output(cache, "zh", _FakeSettings())

        assert checks["a.json"].passed is True
        assert checks["b.json"].passed is False
        assert checks["c.json"].passed is True

    def test_missing_directory_returns_empty(self, tmp_path: Path) -> None:
        assert _validate_adapt_output(tmp_path / "nope", "zh", _FakeSettings()) == {}

    def test_empty_directory_returns_empty(self, tmp_path: Path) -> None:
        """**空必须被调用方当作失败** —— 没有产物可以证明翻译成功。"""
        cache = _cache(tmp_path, {})

        assert _validate_adapt_output(cache, "zh", _FakeSettings()) == {}

    def test_metadata_file_excluded_from_validation(self, tmp_path: Path) -> None:
        """旁挂的元数据不是 prompt，不该参与语言校验（它本身是英文 JSON）。"""
        cache = _cache(
            tmp_path,
            {"a.json": _TRANSLATED, ADAPT_METADATA_FILENAME: '{"validated": true}'},
        )

        checks = _validate_adapt_output(cache, "zh", _FakeSettings())

        assert set(checks) == {"a.json"}


class TestCacheUsability:
    """T-2.2：缺元数据或未通过校验的缓存 MUST NOT 被使用。"""

    def test_cache_without_metadata_rejected(self, tmp_path: Path) -> None:
        """**最重要的一条**：来源不明的旧缓存不可信。

        实测中那份被污染的缓存就没有任何元数据，它让后续每次合成都读到英文
        提示词，而且没有任何迹象表明问题出在缓存上。
        """
        cache = _cache(tmp_path, {"a.json": _TRANSLATED})  # 内容是好的，但没元数据

        assert _cached_adapt_is_usable(cache, "zh", _FakeSettings()) is False

    def test_cache_with_failed_validation_rejected(self, tmp_path: Path) -> None:
        cache = _cache(tmp_path, {"a.json": _UNTRANSLATED})
        (cache / ADAPT_METADATA_FILENAME).write_text(
            json.dumps({"language": "zh", "validated": False}), encoding="utf-8"
        )

        assert _cached_adapt_is_usable(cache, "zh", _FakeSettings()) is False

    def test_validated_cache_accepted(self, tmp_path: Path) -> None:
        cache = _cache(tmp_path, {"a.json": _TRANSLATED})
        _write_adapt_metadata(
            cache, "zh", _validate_adapt_output(cache, "zh", _FakeSettings()),
            _FakeSettings(),
        )

        assert _cached_adapt_is_usable(cache, "zh", _FakeSettings()) is True

    def test_language_mismatch_rejected(self, tmp_path: Path) -> None:
        """元数据说是别的语言 → 不能拿来用。"""
        cache = _cache(tmp_path, {"a.json": _TRANSLATED})
        (cache / ADAPT_METADATA_FILENAME).write_text(
            json.dumps({"language": "ja", "validated": True}), encoding="utf-8"
        )

        assert _cached_adapt_is_usable(cache, "zh", _FakeSettings()) is False

    def test_metadata_present_but_no_prompt_files(self, tmp_path: Path) -> None:
        """只有元数据、没有 prompt 文件 → 不可用。"""
        cache = tmp_path / "chinese"
        cache.mkdir(parents=True)
        (cache / ADAPT_METADATA_FILENAME).write_text(
            json.dumps({"language": "zh", "validated": True}), encoding="utf-8"
        )

        assert _cached_adapt_is_usable(cache, "zh", _FakeSettings()) is False

    def test_corrupt_metadata_rejected(self, tmp_path: Path) -> None:
        cache = _cache(tmp_path, {"a.json": _TRANSLATED})
        (cache / ADAPT_METADATA_FILENAME).write_text("{ not json", encoding="utf-8")

        assert _cached_adapt_is_usable(cache, "zh", _FakeSettings()) is False

    def test_nonexistent_cache_rejected(self, tmp_path: Path) -> None:
        assert _cached_adapt_is_usable(tmp_path / "nope", "zh", _FakeSettings()) is False


class TestAdaptMetadata:
    """元数据必须能回答「这份缓存是谁、什么时候、怎么产出的」。"""

    def test_records_producing_model(self, tmp_path: Path) -> None:
        """换了模型却读到旧缓存 —— 靠这个字段才能事后发现。"""
        s = _FakeSettings(judge_model="minimax/minimax-m2.7")
        cache = _cache(tmp_path, {"a.json": _TRANSLATED})

        _write_adapt_metadata(cache, "zh", _validate_adapt_output(cache, "zh", s), s)
        meta = json.loads((cache / ADAPT_METADATA_FILENAME).read_text(encoding="utf-8"))

        assert meta["produced_by"] == "glm:minimax/minimax-m2.7"

    def test_records_measured_ratios(self, tmp_path: Path) -> None:
        s = _FakeSettings()
        cache = _cache(tmp_path, {"a.json": _TRANSLATED, "b.json": _UNTRANSLATED})

        _write_adapt_metadata(cache, "zh", _validate_adapt_output(cache, "zh", s), s)
        meta = json.loads((cache / ADAPT_METADATA_FILENAME).read_text(encoding="utf-8"))

        assert meta["file_ratios"]["b.json"] == 0.0
        assert meta["file_ratios"]["a.json"] > 0.05
        assert meta["validated"] is False  # 有一个没通过

    def test_records_language_threshold_and_time(self, tmp_path: Path) -> None:
        s = _FakeSettings(threshold=0.07)
        cache = _cache(tmp_path, {"a.json": _TRANSLATED})

        _write_adapt_metadata(cache, "zh", _validate_adapt_output(cache, "zh", s), s)
        meta = json.loads((cache / ADAPT_METADATA_FILENAME).read_text(encoding="utf-8"))

        assert meta["language"] == "zh"
        assert meta["threshold"] == 0.07
        assert "written_at" in meta

    def test_empty_checks_is_not_validated(self, tmp_path: Path) -> None:
        """没有任何产物 → validated 必须为 False，不能是「空即通过」。"""
        s = _FakeSettings()
        cache = tmp_path / "chinese"
        cache.mkdir(parents=True)

        _write_adapt_metadata(cache, "zh", {}, s)
        meta = json.loads((cache / ADAPT_METADATA_FILENAME).read_text(encoding="utf-8"))

        assert meta["validated"] is False


class TestLanguageMapping:
    """T-2.3：语言映射集中定义，未支持的语言明确报错。"""

    def test_mapping_is_centralised(self) -> None:
        assert RAGAS_LANGUAGE_BY_CODE["zh"] == "chinese"

    def test_unsupported_language_rejected_by_synthesize(self) -> None:
        """未支持的语言必须报错，**不能静默按英文 prompt 合成**。

        静默回落正是第一代产出 33 条英文问题的形态。
        """
        import inspect

        from src.observability.evaluation.testset_synthesizer import TestsetSynthesizer

        src = inspect.getsource(TestsetSynthesizer.synthesize)
        assert "unsupported target language" in src
        assert "_NO_ADAPT_LANGUAGES" in src


class TestFailureModesAreDistinguishable:
    """两类失败的错误信息必须能区分 —— 处置完全不同。"""

    def test_error_messages_are_distinct(self) -> None:
        import inspect

        from src.observability.evaluation.testset_synthesizer import TestsetSynthesizer

        src = inspect.getsource(TestsetSynthesizer.synthesize)

        # 情形 A：调用炸了 → 重试 / 查网关
        assert "RAISED after 2 attempts" in src
        assert "CALL failure" in src
        # 情形 B：调用成功但没翻译 → 换模型（重试同一模型必然复现）
        assert "COMPLETED WITHOUT ERROR" in src
        assert "NOT a transient failure" in src

    def test_bad_cache_is_deleted_on_validation_failure(self) -> None:
        """坏产物必须当场删掉，否则它会毒化后续每一次合成。"""
        import inspect

        from src.observability.evaluation.testset_synthesizer import TestsetSynthesizer

        src = inspect.getsource(TestsetSynthesizer.synthesize)
        assert "shutil.rmtree(lang_cache" in src
        assert "cannot poison later" in src
