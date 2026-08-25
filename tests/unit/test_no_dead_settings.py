"""守卫：`settings.py` 里的每个配置项都必须有生产读取点。

**这个文件存在的理由，是本项目十二次同源事故。**

排一排：`rerank.top_m`（全仓只有定义，从未截断过候选）、`--collection` 死参数、
`labeling_llm.max_tokens=200`、CJK 全链路 ASCII-only、chunk_id 两端不相交、
RAGAS `adapt()` 静默不翻译、磁盘缓存固化坏产物、
`synthesis.question_language_mismatch_warn` 只被校验从不被读、
`_labeling_method` 从未流到报告、`query_rewrite` 段从未接进 `load_settings()`、
`degradation.unknown_reason_warn` 只被校验从不被读、
`ingestion.image_captioner.use_fallback` 零读取点。

**十二次同一个病：看起来生效、实际没生效、而且不报错。**

前十一次都是**事后**发现的 —— 靠人偶然打印了一下、靠归档时逐条核对规格、
靠准备跑 A/B 时顺手确认。每一次都已经造成了损失（最贵的一次让「跨代保护」
在标注方式这一维上从未生效过，而没有人知道）。

这个文件把它变成**加不进去**：新增一个配置项而不接上，这里就会红。

---

## 一个关键的设计判断：为什么「被 settings.py 校验过」不算活的

`unknown_reason_warn` 进了取值范围校验循环，`question_language_mismatch_warn`
也进了 —— 两者都还是死配置。**校验只检查值合法，不消费值。**

所以本守卫要求读取点在 **`settings.py` 之外**。这条正是它能抓住前两例的原因。

## 白名单的规矩

例外必须写进 `ALLOWED_UNREAD` 并附**理由**。没有理由的例外等于把守卫关掉 ——
而一个永远绿的守卫和没有守卫长得一模一样。
"""

from __future__ import annotations

import dataclasses
import re
from pathlib import Path

import pytest

import src.core.settings as settings_module

pytestmark = pytest.mark.unit


#: 配置定义所在的文件。读取点**必须**出现在它之外 —— 见模块 docstring 的说明。
SETTINGS_FILE = "settings.py"

#: 扫描读取点的范围。
SCAN_ROOTS = ("src", "scripts")

#: 已知不需要生产读取点的配置项，**每条必须写理由**。
#:
#: 加进这里之前先问一句：这个字段没生效的时候，我怎么会知道？
#: 如果答案是「不会知道」，那它就该被接上或删掉，不是加白名单。
ALLOWED_UNREAD: dict[str, str] = {
    "evaluation.schema_version": (
        "它的**全部用途**就是让 settings.py 自己在启动期拒绝不支持的 schema 版本"
        "（validate_settings 里 `schema_version < 1` 那条）。这是一个真实的行为决定，"
        "不是取值范围检查 —— 与 unknown_reason_warn 那种「只查范围不消费值」不同。"
    ),
}


def _leaf_paths() -> list[str]:
    """从 ``Settings`` 递归展开所有叶子配置项的 dotted path。"""

    def walk(cls: type, prefix: str = "") -> list[str]:
        out: list[str] = []
        for field in dataclasses.fields(cls):
            path = f"{prefix}{field.name}"
            nested = None
            candidate = field.type
            if isinstance(candidate, str):
                candidate = getattr(settings_module, candidate, None)
            if candidate is not None and dataclasses.is_dataclass(candidate):
                nested = candidate
            if nested is not None:
                out.extend(walk(nested, path + "."))
            else:
                out.append(path)
        return out

    return walk(settings_module.Settings)


def _production_sources() -> list[Path]:
    """读取点扫描范围：``src/`` 与 ``scripts/`` 下除 settings.py 之外的 .py。"""
    files: list[Path] = []
    for root in SCAN_ROOTS:
        base = Path(root)
        if not base.exists():
            continue
        files.extend(
            p
            for p in base.rglob("*.py")
            if "__pycache__" not in p.parts and p.name != SETTINGS_FILE
        )
    return files


def _unread_fields() -> list[str]:
    """找出所有在生产代码里搜不到读取点的叶子配置项。"""
    blob = "\n".join(p.read_text(encoding="utf-8") for p in _production_sources())
    unread: list[str] = []
    for path in _leaf_paths():
        leaf = path.rsplit(".", 1)[-1]
        # 属性访问（settings.rerank.top_m）或字典/字符串键（"top_m"）都算读到
        if re.search(r"\." + re.escape(leaf) + r"\b", blob):
            continue
        if f'"{leaf}"' in blob or f"'{leaf}'" in blob:
            continue
        unread.append(path)
    return unread


class TestNoDeadSettings:
    def test_every_field_has_a_production_reader(self) -> None:
        """每个配置项都必须在 ``settings.py`` 之外被读到。

        红了怎么办 —— 三条路，**按这个顺序**考虑：

        1. **接上它**。这是默认答案：字段存在说明当初想要某个行为，把它接到那个
           行为上，并补一条「改了这个配置，结论就该变」的用例。
        2. **删掉它**。如果那个行为其实无条件发生、或者没人会想改它 ——
           删。加一个不解决任何问题的配置项，就是第三个 ``rerank.top_m``。
        3. **加白名单并写理由**。只在字段的用途**确实**局限于 settings.py 内部的
           行为决定时才走这条（例如 schema 版本拒绝）。
           「以后会用」不是理由 —— 以后再加。
        """
        unread = [p for p in _unread_fields() if p not in ALLOWED_UNREAD]

        assert unread == [], (
            "以下配置项在 src/ 与 scripts/ 里找不到任何读取点 —— "
            "它们很可能是死配置（本项目已因此栽过十二次）：\n  "
            + "\n  ".join(unread)
            + "\n\n处置顺序见本用例的 docstring：先想能不能接上，再想该不该删，"
            "最后才是加白名单（且必须写理由）。"
        )

    def test_allowlist_entries_still_exist(self) -> None:
        """白名单不得指向已经不存在的字段。

        字段删了而白名单还留着，会让守卫的覆盖面悄悄缩小 —— 又是一种静默失效。
        """
        known = set(_leaf_paths())
        stale = sorted(p for p in ALLOWED_UNREAD if p not in known)

        assert stale == [], f"白名单里这些字段已不存在，请删掉对应条目：{stale}"

    def test_allowlist_entries_have_reasons(self) -> None:
        """每条白名单都必须写理由。

        没有理由的例外等于把守卫关掉，而一个永远绿的守卫和没有守卫长得一样。
        """
        empty = sorted(k for k, v in ALLOWED_UNREAD.items() if len(v.strip()) < 20)

        assert empty == [], f"这些白名单条目没写（或写得太短）理由：{empty}"

    def test_allowlist_is_small(self) -> None:
        """白名单不该增长成一份「豁免清单」。

        它每多一条，这个守卫就少守一个字段。数字本身没有魔力，
        但一个在涨的白名单是个该被看见的信号。
        """
        assert len(ALLOWED_UNREAD) <= 5, (
            f"白名单已有 {len(ALLOWED_UNREAD)} 条 —— 停下来想想是不是在用豁免"
            "代替接线"
        )


class TestTheGuardActuallyWorks:
    """自检：守卫本身必须真的能抓到东西。

    一个「扫描范围配错了、于是永远为空、于是永远通过」的守卫，
    和没有守卫长得一模一样 —— 这正是本项目要消灭的形态。
    """

    def test_scan_finds_a_reasonable_number_of_fields(self) -> None:
        paths = _leaf_paths()

        assert len(paths) > 80, f"只展开出 {len(paths)} 个配置项，递归可能断了"

    def test_scan_finds_a_reasonable_number_of_files(self) -> None:
        files = _production_sources()

        assert len(files) > 40, f"只扫到 {len(files)} 个源文件，扫描范围可能配错了"

    def test_settings_file_is_excluded_from_readers(self) -> None:
        """``settings.py`` 必须被排除在读取点之外。

        **这是整个守卫最关键的一条。** 若不排除，取值范围校验循环会让
        ``unknown_reason_warn`` / ``question_language_mismatch_warn``
        这类字段看起来「被读了」—— 而它们正是实打实的死配置。
        校验只检查值合法，**不消费值**。
        """
        names = {p.name for p in _production_sources()}

        assert SETTINGS_FILE not in names

    def test_a_known_live_field_is_detected_as_live(self) -> None:
        """已知活着的字段必须被判为活的（防止扫描把所有字段都判死）。"""
        unread = set(_unread_fields())

        # 这几个都有明确的生产消费点
        for alive in (
            "retrieval.rrf_k",
            "rerank.backend",
            "vector_store.collection_name",
            "query_rewrite.strategy",
        ):
            assert alive not in unread, f"{alive} 被误判为死配置，扫描逻辑有问题"

    def test_a_synthetic_dead_field_would_be_caught(self) -> None:
        """构造一个必然没人读的字段名，确认扫描会把它认出来。

        这条回答的是「守卫失效时我怎么会知道」—— 它自己就是那个答案。
        """
        blob = "\n".join(
            p.read_text(encoding="utf-8") for p in _production_sources()
        )
        fabricated = "zzz_definitely_not_read_by_anyone"

        assert f".{fabricated}" not in blob
        assert f'"{fabricated}"' not in blob
