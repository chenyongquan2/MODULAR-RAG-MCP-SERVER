"""查询改写器的抽象基类。

**查询改写在做什么**：把用户的查询变成更容易被某一条检索路径命中的形式。
它发生在检索**之前** —— 与重排（检索之后重新排序候选）是两个不同阶段。

**为什么这件事有意义**：混合检索的两路对「措辞」的敏感度天差地别。

- **稠密（dense）路**把查询编码成向量，再找语义上最近的片段。embedding 天然
  吸收同义关系 ——「止损」和「stop loss」的向量本来就近，所以换个说法对它
  几乎没有影响。
- **稀疏（sparse / BM25）路**是**字面匹配**：查询里出现的词必须在文档里
  真的出现过，才可能命中。查询写 ``SL`` 而文档写「止损」时，命中数为 **零**。

所以「多给几组词面」类的改写，主要受益方是 sparse 而不是 dense。这不是偏好
问题，是两种检索机制的构造决定的。

**本模块的接口刻意收得很窄**：改写器只对**关键词列表**做变换，不碰原始查询。
原因见 ``SynonymQueryRewriter`` 的说明 —— 稠密路吃的是原始查询，往它的输入
里塞同义词只会加噪。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, List, Optional, Sequence


class BaseQueryRewriter(ABC):
    """查询改写器接口。

    所有实现必须是**确定性**的：同样的输入必须产出同样的输出。改写发生在
    一次检索调用的内部，调用方不维持任何跨调用状态 —— 第二个消费方的
    ``KnowledgeSearchPort`` 是「单次调用、无状态、进查询出文档」的形状，
    任何要求调用方配合的改写形态在那个接口下无法落地。
    """

    @abstractmethod
    def rewrite_keywords(
        self,
        keywords: Sequence[str],
        query: str = "",
        trace: Optional[Any] = None,
    ) -> List[str]:
        """把关键词列表改写（通常是扩展）成新的关键词列表。

        Args:
            keywords: 已经过停用词过滤的原始关键词，**顺序有意义**
                （靠前的词通常更贴近用户意图，实现应保持原有顺序）。
            query: 原始查询文本，供需要上下文的策略使用；``synonym`` 用不到。
            trace: 可选的链路追踪上下文。

        Returns:
            改写后的关键词列表。**不改写时必须原样返回**（含顺序），
            这样 ``strategy: none`` 的行为与引入本能力之前逐条相同。
        """

    @abstractmethod
    def get_strategy_name(self) -> str:
        """返回本策略的标识，用于追踪打点与报告。

        追踪里必须记得下「本次到底用了哪个策略」—— 改写不生效与改写生效但
        无收益，在最终指标上可能表现相同，没有痕迹就无法区分这两件事，
        而它们的处置完全相反。
        """

    def uses_llm(self) -> bool:
        """本策略是否会调用生成模型。

        默认 ``False``。会调用 LLM 的策略必须覆盖为 ``True``。

        **这不是装饰性的元数据**：``synonym`` 被选中的**全部理由**就是
        「零 token、零延迟」。若实现里悄悄引入了一次模型调用，这个理由就不
        成立了，而它不会以任何错误的形式表现出来 —— 只是查询慢了、账单涨了。
        本项目为此配了断言测试（见 ``tests/unit/test_query_rewriter_zero_cost.py``）。
        """
        return False


class NoneQueryRewriter(BaseQueryRewriter):
    """不改写 —— 默认策略。

    存在的意义是让「关闭」也走同一条代码路径，调用方不必写
    ``if rewriter is not None``。一个默认不启用的能力不该向所有调用方收税，
    也不该在调用点留下分支。
    """

    def __init__(self, settings: Any = None, **kwargs: Any) -> None:
        self.settings = settings

    def rewrite_keywords(
        self,
        keywords: Sequence[str],
        query: str = "",
        trace: Optional[Any] = None,
    ) -> List[str]:
        """原样返回 —— 含顺序，不去重、不排序。"""
        return list(keywords)

    def get_strategy_name(self) -> str:
        return "none"
