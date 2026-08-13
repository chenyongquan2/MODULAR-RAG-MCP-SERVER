"""配置类的密钥字段不得出现在 repr 中。

**这条不是理论洁癖** —— 2026-08-08 一次 pytest 断言失败,直接把完整的
GLM API key 打到了控制台:

    ScreeningLLMSettings(provider='glm', model='z-ai/glm-5.2-free',
                         api_key='0hHyjwarV7lyUB7ZSVmAhq...', ...)

dataclass 的默认 ``__repr__`` 会把每个字段原样渲染,所以任何 traceback、
日志、断言失败都可能泄漏密钥。修法是给字段标 ``field(repr=False)``。

本文件用**遍历**而非硬编码清单来断言,这样将来新增配置类时同样会被拦下,
不必依赖有人记得来改测试。
"""

from __future__ import annotations

import dataclasses
import inspect

import pytest

from src.core import settings as settings_module

pytestmark = pytest.mark.unit

# 字段名含这些词即视为敏感
SECRET_TOKENS = ("api_key", "token", "secret", "password", "credential")


def _is_secret_typed(field_obj: dataclasses.Field) -> bool:
    """密钥一定是字符串;数值字段不可能是密钥。

    为什么需要这道过滤(2026-08-13 实测踩到):名字含 ``token`` 的字段并不都是
    密钥 —— ``LabelingLLMSettings.max_tokens: int`` 就被 ``"token" in name``
    的启发式误判成了密钥,要求它 ``repr=False``。那是荒谬的:把 max_tokens 从
    repr 里藏起来毫无意义,只会让调试变难。

    按类型过滤比维护一份名字白名单更有原则 —— 新增 ``max_tokens`` /
    ``token_limit`` / ``n_tokens`` 之类的数值参数都不必再来改这个测试。

    注意这**不削弱**检查:任何字符串类型且名字含敏感词的字段仍然被要求
    ``repr=False``。
    """
    annotation = str(field_obj.type)
    return "int" not in annotation and "float" not in annotation and "bool" not in annotation


def _secret_fields() -> list[tuple[str, dataclasses.Field]]:
    """收集 src.core.settings 中所有配置类的敏感字段。"""
    found: list[tuple[str, dataclasses.Field]] = []
    for name, obj in inspect.getmembers(settings_module, inspect.isclass):
        if not dataclasses.is_dataclass(obj):
            continue
        if obj.__module__ != settings_module.__name__:
            continue  # 跳过 import 进来的外部 dataclass
        for f in dataclasses.fields(obj):
            if any(tok in f.name.lower() for tok in SECRET_TOKENS) and _is_secret_typed(f):
                found.append((f"{name}.{f.name}", f))
    return found


def test_secret_fields_exist_at_all() -> None:
    """兜底:若收集逻辑因重构失效而收不到任何字段,本测试会退化为空断言。"""
    assert _secret_fields(), "未收集到任何敏感字段,收集逻辑可能已失效"


@pytest.mark.parametrize(
    "qualified_name,field_obj",
    _secret_fields(),
    ids=[name for name, _ in _secret_fields()],
)
def test_secret_field_is_excluded_from_repr(
    qualified_name: str, field_obj: dataclasses.Field
) -> None:
    """每个敏感字段都必须 repr=False。"""
    assert field_obj.repr is False, (
        f"{qualified_name} 会被 dataclass 默认 repr 打印出来,密钥可能随 "
        f"traceback / 日志泄漏。请改为 field(default=..., repr=False)。"
    )


def test_loaded_settings_repr_does_not_contain_key_material() -> None:
    """端到端:用真实配置构造 Settings,其 repr 不得包含任何非空密钥值。"""
    from src.core.settings import load_settings

    s = load_settings()
    rendered = repr(s)

    checked = 0
    for section in (
        s.llm,
        s.embedding,
        s.evaluation.judge_llm,
        s.evaluation.embedding,
        s.evaluation.screening_llm,
    ):
        key = getattr(section, "api_key", "") or ""
        if len(key) < 8:
            continue  # 未配置或占位值,不具判别力
        checked += 1
        assert key not in rendered, f"{type(section).__name__} 的密钥出现在 repr 中"

    if checked == 0:
        pytest.skip("当前环境未配置任何真实密钥,无法做端到端校验")
