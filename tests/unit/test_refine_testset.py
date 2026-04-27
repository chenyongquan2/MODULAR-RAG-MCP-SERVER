"""Unit tests for refine_testset interactive loop (T024, refs FR-005).

测试范围:
- y/d/s 三个非编辑选择的决策处理
- e (edit) 路径用 mock 跳过 $EDITOR 真实启动
- q 中途退出后已处理的 case 全部保留(部分进度)
- _strip_synth_artifacts 过滤 _synth_* 临时字段
- 输出 JSON 含 _refine_summary 与正确的 keep/edit/drop 计数
"""

from __future__ import annotations

import io
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

import sys
import importlib.util
from pathlib import Path

# 加载 scripts/refine_testset.py 作为模块(它不在 src/ 包里)
_spec = importlib.util.spec_from_file_location(
    "refine_testset_module",
    Path(__file__).parent.parent.parent / "scripts" / "refine_testset.py",
)
refine_testset_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(refine_testset_module)


pytestmark = pytest.mark.unit


def _make_candidate(n_cases: int = 3) -> dict[str, Any]:
    return {
        "_schema_version": 1,
        "language": "zh",
        "_synthesis_metadata": {"distribution": {}},
        "test_cases": [
            {
                "query": f"q{i}",
                "ground_truth": f"gt{i}",
                "_synth_contexts": [f"ctx{i}_a", f"ctx{i}_b"],
                "expected_chunk_ids": [],
                "expected_sources": [],
                "tags": {
                    "content_type": "text",
                    "difficulty": "simple",
                    "language": "zh",
                    "doc_version": "v1",
                },
            }
            for i in range(n_cases)
        ],
    }


def _stdin(answers: list[str]) -> io.StringIO:
    return io.StringIO("\n".join(answers) + "\n")


# ---------------------------------------------------------------------------
# Decision processing
# ---------------------------------------------------------------------------


class TestDecisions:
    def test_all_keep_returns_all_cases(self) -> None:
        candidate = _make_candidate(3)
        result = refine_testset_module.interactive_refine(
            candidate, input_stream=_stdin(["y", "y", "y"])
        )
        assert len(result["test_cases"]) == 3
        assert result["_refine_summary"]["keep"] == 3
        assert result["_refine_summary"]["drop"] == 0

    def test_drop_excludes_case(self) -> None:
        candidate = _make_candidate(3)
        result = refine_testset_module.interactive_refine(
            candidate, input_stream=_stdin(["y", "d", "y"])
        )
        assert len(result["test_cases"]) == 2
        # 留下的应是 q0 / q2
        queries = [c["query"] for c in result["test_cases"]]
        assert "q0" in queries
        assert "q1" not in queries
        assert "q2" in queries
        assert result["_refine_summary"]["drop"] == 1

    def test_skip_does_not_keep_or_drop(self) -> None:
        """skip 既不入 final 也不算 drop;典型用例:留待下一轮 review。"""
        candidate = _make_candidate(3)
        result = refine_testset_module.interactive_refine(
            candidate, input_stream=_stdin(["y", "s", "y"])
        )
        assert len(result["test_cases"]) == 2
        assert result["_refine_summary"]["skip"] == 1
        assert result["_refine_summary"]["drop"] == 0

    def test_quit_saves_partial_progress(self) -> None:
        """q 中途退出,已处理的 case 全保留,后续未处理的不入 final。"""
        candidate = _make_candidate(5)
        # 前 2 条 keep,然后 q
        result = refine_testset_module.interactive_refine(
            candidate, input_stream=_stdin(["y", "y", "q"])
        )
        # 已 keep 2 条
        assert len(result["test_cases"]) == 2
        # version 应标记为 partial
        assert result["version"] == "v0.9-partial"

    def test_unrecognized_input_re_prompts(self) -> None:
        """非法输入 'x' 应提示重新输入,不消耗 case。"""
        candidate = _make_candidate(2)
        result = refine_testset_module.interactive_refine(
            candidate, input_stream=_stdin(["x", "y", "y"])
        )
        # 第一条 case 还是 kept(用户输错后 retry)
        assert len(result["test_cases"]) == 2
        assert result["_refine_summary"]["keep"] == 2


class TestEditPath:
    def test_edit_invokes_editor_and_uses_result(self) -> None:
        candidate = _make_candidate(1)
        edited = {
            "query": "EDITED query",
            "ground_truth": "EDITED gt",
            "expected_chunk_ids": [],
            "expected_sources": [],
            "tags": {
                "content_type": "text", "difficulty": "simple",
                "language": "zh", "doc_version": "v1",
            },
        }
        with patch.object(
            refine_testset_module, "_edit_case_in_editor", return_value=edited
        ):
            result = refine_testset_module.interactive_refine(
                candidate, input_stream=_stdin(["e"])
            )
        assert result["test_cases"][0]["query"] == "EDITED query"
        assert result["_refine_summary"]["edit"] == 1

    def test_edit_failure_keeps_original(self) -> None:
        """_edit_case_in_editor 返回 None(编辑失败)→ 保留原 case 计入 keep。"""
        candidate = _make_candidate(1)
        with patch.object(
            refine_testset_module, "_edit_case_in_editor", return_value=None
        ):
            result = refine_testset_module.interactive_refine(
                candidate, input_stream=_stdin(["e"])
            )
        assert result["test_cases"][0]["query"] == "q0"
        assert result["_refine_summary"]["keep"] == 1
        assert result["_refine_summary"]["edit"] == 0


class TestArtifactStripping:
    def test_synth_contexts_removed_from_final(self) -> None:
        """final 输出不应含 _synth_contexts 等临时合成字段。"""
        candidate = _make_candidate(1)
        result = refine_testset_module.interactive_refine(
            candidate, input_stream=_stdin(["y"])
        )
        case = result["test_cases"][0]
        assert "_synth_contexts" not in case
        # 但保留正常字段
        assert "query" in case
        assert "tags" in case


class TestFinalSchema:
    def test_final_has_required_top_level_fields(self) -> None:
        candidate = _make_candidate(2)
        result = refine_testset_module.interactive_refine(
            candidate, input_stream=_stdin(["y", "y"])
        )
        for key in ("_schema_version", "language", "version", "created_at",
                    "_refine_summary", "test_cases"):
            assert key in result
        assert result["_schema_version"] == 1
        assert result["language"] == "zh"
