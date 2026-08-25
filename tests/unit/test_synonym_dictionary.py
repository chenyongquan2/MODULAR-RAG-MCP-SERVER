"""守住仓库里那份种子词表本身 (T-2.6)。

change: per-route-metrics-and-synonym-rewrite

**词表不是想出来的，是量出来的**：从金标 query 里实际出现的缩写出发，到 BM25
索引里查两种写法各自覆盖多少 chunk，只收「缩写近乎零信号、全称大量存在」的组。
那种情况下扩展几乎是纯增益 —— 原本这个词对 BM25 的贡献是 0。

本文件守的是**词表文件本身**（能被加载、条目合法、没有把该排除的类别混进来），
不是改写逻辑（那在 ``test_query_rewriter.py``）。

不联网、不调用任何模型。
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from src.core.settings import QueryRewriteSettings, _validate_query_rewrite_settings
from src.libs.query_rewriter import SynonymQueryRewriter

pytestmark = pytest.mark.unit

DICT_PATH = "config/synonyms.yaml"


@pytest.fixture(scope="module")
def raw() -> dict:
    return yaml.safe_load(Path(DICT_PATH).read_text(encoding="utf-8")) or {}


class TestDictionaryIsUsable:
    def test_file_exists(self) -> None:
        assert Path(DICT_PATH).exists()

    def test_passes_startup_validation(self) -> None:
        """必须能通过 ``load_settings()`` 的校验 —— 否则配上去就启动不了。"""
        cfg = QueryRewriteSettings(strategy="synonym", synonym_dict=DICT_PATH)

        _validate_query_rewrite_settings(cfg)

    def test_loads_into_rewriter(self) -> None:
        rewriter = SynonymQueryRewriter(settings=None, synonym_dict=DICT_PATH)

        assert rewriter.group_count > 0

    def test_size_is_a_seed_table_not_an_engineering_project(self, raw) -> None:
        """规模控制在几十条。

        本次目的是**验证同义词扩展对这份语料到底有没有用**，不是做词表工程。
        表越大，A/B 的结果越难归因到具体机制。
        """
        assert 10 <= len(raw) <= 80, f"词表 {len(raw)} 条，超出「种子表」的预期规模"


class TestEntriesAreWellFormed:
    def test_every_value_is_a_list(self, raw) -> None:
        bad = [k for k, v in raw.items() if not isinstance(v, list)]
        assert bad == [], f"这些条目的值不是列表：{bad}"

    def test_no_empty_groups(self, raw) -> None:
        """单词面的「组」没有扩展意义 —— 写了也不会生效，属于死条目。"""
        empty = [k for k, v in raw.items() if not v]
        assert empty == [], f"这些条目没有同义词，等于死条目：{empty}"

    def test_no_self_reference(self, raw) -> None:
        selfref = [k for k, v in raw.items() if k in v]
        assert selfref == [], f"这些条目把自己列进了同义词：{selfref}"

    def test_keys_are_lowercase(self, raw) -> None:
        """匹配是大小写不敏感的，键写成大写只会让人误以为大小写有意义。"""
        upper = [k for k in raw if k != k.lower()]
        assert upper == [], f"这些键含大写：{upper}"


class TestDeliberateExclusions:
    """刻意排除的三类必须真的不在表里。

    这些不是洁癖 —— 每一类都有具体理由，混进来会让 A/B 的结果失去意义。
    """

    def test_no_chinese_entries(self, raw) -> None:
        """中文词条**验证不了**：中文金标只有 6 条。

        凭印象加中文条目就是在编证据。等中文金标扩容后再基于实测补。
        """

        def has_cjk(text: str) -> bool:
            return any("一" <= ch <= "鿿" for ch in str(text))

        offenders = [
            k for k, v in raw.items() if has_cjk(k) or any(has_cjk(x) for x in v)
        ]
        assert offenders == [], (
            f"词表里出现了中文条目：{offenders}。"
            "中文金标只有 6 条，验证不了它们 —— 等 C1 扩容后再基于实测补"
        )

    def test_no_ambiguous_common_abbreviations(self, raw) -> None:
        """缩写本身在语料里也很常见的组不收。

        ``ret``(11859) / ``pos``(2435) / ``err``(1868) 在 API 文档里常是**参数名**，
        与「返回 / 持仓 / 错误」不是一回事 —— 扩展等于引入语义漂移，
        同时实打实地加长 BM25 查询、稀释权重。
        """
        forbidden = {"ret", "pos", "err", "param", "params", "info", "app", "mem"}
        offenders = sorted(forbidden & set(raw))
        assert offenders == [], (
            f"这些缩写在语料里本身就常见，扩展是净加噪：{offenders}"
        )

    def test_no_plural_singular_pairs(self, raw) -> None:
        """单复数是**另一种机制**，混进同一次 A/B 会让结果无法归因。

        缺口是真实的（tokenizer 不做词干还原），但要单独测。
        """
        offenders = []
        for key, values in raw.items():
            for value in values:
                text = str(value).lower()
                # 只查「键是值去掉尾部 s」这种最直白的单复数对
                if text == f"{key}s" or key == f"{text}s":
                    offenders.append((key, value))
        assert offenders == [], f"词表里混进了单复数对：{offenders}"


class TestExpansionActuallyFires:
    """拿金标 query 里真实出现过的缩写走一遍，确认能扩开。

    没有这条，一份「格式全对但一个词都命中不了」的词表也能通过上面全部检查 ——
    那正是本项目的招牌病形态。
    """

    @pytest.mark.parametrize(
        "abbrev,expected",
        [
            ("grp", "group"),
            ("mgr", "manager"),
            ("cfg", "config"),
            ("srv", "server"),
            ("bal", "balance"),
            ("sym", "symbol"),
            ("req", "request"),
            ("resp", "response"),
            ("evts", "events"),
            ("imtsrvapi", "imtserverapi"),
        ],
    )
    def test_known_abbreviation_expands(self, abbrev: str, expected: str) -> None:
        rewriter = SynonymQueryRewriter(settings=None, synonym_dict=DICT_PATH)

        result = [w.lower() for w in rewriter.rewrite_keywords([abbrev])]

        assert expected in result, f"{abbrev!r} 没有扩展出 {expected!r}"

    def test_multiword_entry_is_tokenized(self) -> None:
        """``th: [trade history]`` 这种多词写法必须被切开。

        索引里不存在「trade history」这个整体词条。
        """
        rewriter = SynonymQueryRewriter(settings=None, synonym_dict=DICT_PATH)

        result = [w.lower() for w in rewriter.rewrite_keywords(["th"])]

        assert "trade" in result
        assert "history" in result
        assert "trade history" not in result

    def test_unrelated_query_is_untouched(self) -> None:
        rewriter = SynonymQueryRewriter(settings=None, synonym_dict=DICT_PATH)

        assert rewriter.rewrite_keywords(["quantum", "banana"]) == ["quantum", "banana"]
