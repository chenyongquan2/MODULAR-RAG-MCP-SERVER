"""结果融合 (带权重的 RRF 算法)。

本模块实现 Reciprocal Rank Fusion (RRF)，把多路检索的排名聚合成一个统一
排序。RRF 只依赖**名次**而不依赖原始分数 —— 这正是它被选用的理由：语义
相似度与 BM25 分数的量纲完全不同（前者 0~1、后者可到几十），基于名次规避
了归一化难题。

算法公式（feature-005 起带权重）::

    score(c) = Σ_r  weight[r] / (k + rank_r(c))

其中：

- ``c`` 是内容（chunk）
- ``r`` 是检索路径（``dense`` / ``sparse``）
- ``rank_r(c)`` 是 ``c`` 在路径 ``r`` 结果中的名次（从 1 起）；未被该路命中
  则该项不计入
- ``weight[r]`` 是该路的相对分量；未指定的路径缺省 1.0
- ``k`` 是平滑参数，控制排名靠后结果的衰减速度

**为什么需要权重**（缺陷背景）：Feature-004 实测发现，等权融合在英文金标上
recall 42.4% **低于**纯语义检索的 45.7%、hit_rate 61.9% 低于 69.0%，而 MRR
0.502 高于 0.437。根因就是两路一视同仁 —— 关键词路径的噪音命中挤掉了语义
路径的正确结果压低召回，而两路同时命中的内容得分叠加、排名上升抬高 MRR。

**为什么入参是命名映射而不是位置列表**：权重必须按路径**名字**查找。此前
``fuse()`` 收位置列表靠下标区分两路，而本文件曾有一条注释把两路顺序写反
（写作 ``[sparse_result, dense_result]``，实际调用是 ``[dense, sparse]``）——
等权时这个错误完全无害，所以它一直存活。加权重后同样的混淆会让语义路径拿到
关键词路径的权重，**而系统照常运行、不报错，只是效果悄悄变差**。

完整契约见 specs/005-weighted-fusion/contracts/fusion.contract.md。
"""

from __future__ import annotations

from typing import Dict, List, Mapping, Optional, Sequence

from src.core.types import RetrievalResult

#: 路径未在权重配置中出现时的缺省分量。
#:
#: 取 1.0 而非报错，是为了让新增检索路径不必强制所有部署同步改配置。
DEFAULT_ROUTE_WEIGHT = 1.0


class Fusion:
    """带权重的 Reciprocal Rank Fusion。

    Design Principles Applied:
    - Stateless: 除构造期注入的 k 与权重外无内部状态，纯函数式算法
    - Deterministic: 相同输入必得相同输出
    - Graceful Degradation: 空路径列表被跳过，不影响其余路径

    Example:
        >>> fusion = Fusion(k=60, weights={"dense": 1.0, "sparse": 0.25})
        >>> fused = fusion.fuse({"dense": dense_results, "sparse": sparse_results},
        ...                     top_k=5)
        >>> [r.chunk_id for r in fused]
        ['2', '1']
    """

    DEFAULT_K = 60

    def __init__(
        self,
        k: Optional[int] = None,
        weights: Optional[Mapping[str, float]] = None,
    ) -> None:
        """初始化融合器。

        Args:
            k: RRF 平滑参数。值越大，排名靠后的结果获得的相对分量越多。
                默认 60。
            weights: 路径名 → 相对分量。``None`` 时所有路径按
                :data:`DEFAULT_ROUTE_WEIGHT` 处理，行为与 feature-005 之前
                一致。

        Note:
            **权重的合法性校验在 ``load_settings()`` 完成**（宪法原则三，
            启动期快速失败），此处不重复校验 —— 单一校验点避免两处规则漂移。

            权重**只有相对比例有意义**：``{dense: 1.0, sparse: 0.5}`` 与
            ``{dense: 2.0, sparse: 1.0}`` 产出完全相同的排序，因为所有得分
            等比缩放，而排序对单调变换不变。
        """
        self._k = k if k is not None else self.DEFAULT_K
        self._weights: Dict[str, float] = dict(weights) if weights else {}

    @property
    def weights(self) -> Dict[str, float]:
        """本融合器生效的权重映射（副本，避免外部改动内部状态）。

        供追踪打点使用（FR-008）—— 调用方需要把「本次实际生效的权重」写进
        trace，否则事后无法判断某次检索到底用的什么配比。
        """
        return dict(self._weights)

    def weight_for(self, route: str) -> float:
        """取某路径的生效权重；未配置的路径返回缺省值。"""
        return float(self._weights.get(route, DEFAULT_ROUTE_WEIGHT))

    def fuse(
        self,
        routes: Mapping[str, Sequence[RetrievalResult]],
        top_k: Optional[int] = None,
    ) -> List[RetrievalResult]:
        """按带权 RRF 融合多路检索结果。

        Args:
            routes: 路径名 → 该路的**有序**结果序列。顺序即名次，调用方不得
                预先重排。
            top_k: 返回前 N 条；``None`` 或 ≤ 0 时返回全部。

        Returns:
            按融合得分降序排列的结果列表。每项的 ``score`` 是融合得分（**不是**
            任何单路的原始分数）；``text`` / ``metadata`` 取自首个贡献该内容的
            路径。

        Note:
            三条不变量（由 tests/unit/test_fusion_rrf.py 固定，因为违反它们
            的失败都是**静默的** —— 不抛异常、不告警，只是结果悄悄变差）：

            1. **顺序无关**：改变 *routes* 中键的插入顺序，输出逐条不变。
               权重按键查找，与顺序无关。
            2. **空路无副作用**：某路为空时其余路的相对排序不变。RRF 是加法，
               空路贡献 0，**因此这条靠「不引入动态归一化」来满足，而非新增
               代码**（见下方"刻意不做"）。
            3. **等权兼容**：所有权重相等时，排序与 feature-005 之前逐条一致
               （等权时新公式是旧公式的常数倍，排序不变）。

            **刻意不做**：不在某路为空时把其权重重新分配给剩余路径。那样
            **不改变任何可观测排序**（等比缩放是单调变换），却会让同一内容的
            绝对得分随「另一路是否恰好为空」跳变，使跨查询的得分不可比；且
            引入一个只在边界触发、无可观测收益的分支。
        """
        if not routes:
            return []

        chunk_scores: Dict[str, float] = {}
        chunk_data: Dict[str, RetrievalResult] = {}

        for route_name, results in routes.items():
            if not results:
                # 空路跳过。其余路的得分不做任何补偿性调整 —— 见 docstring
                # 的"刻意不做"。
                continue

            weight = self.weight_for(route_name)
            if weight == 0.0:
                # 权重 0 等价于该路未传入。提前跳过既省计算，也让"关闭某路"
                # 的语义在代码里显式可见。
                continue

            # enumerate(start=1)：rank 从 1 起，与 RRF 公式的人类直觉一致
            for rank, result in enumerate(results, start=1):
                if not result.chunk_id:
                    continue

                contribution = weight / (self._k + rank)

                if result.chunk_id in chunk_scores:
                    # 同一 chunk_id 的 text/metadata 在各路中相同，无需更新
                    chunk_scores[result.chunk_id] += contribution
                else:
                    chunk_scores[result.chunk_id] = contribution
                    chunk_data[result.chunk_id] = result

        fused_results: List[RetrievalResult] = [
            RetrievalResult(
                chunk_id=chunk_data[chunk_id].chunk_id,
                score=score,
                text=chunk_data[chunk_id].text,
                metadata=chunk_data[chunk_id].metadata,
            )
            for chunk_id, score in chunk_scores.items()
        ]

        # 以 chunk_id 为次级键排序。这是不变量 1（顺序无关）能成立的关键。
        #
        # 旧实现是 sort(key=score, reverse=True)。Python 的排序是稳定的，因此
        # **同分项的相对次序由插入顺序决定，而插入顺序又随路径遍历顺序变化**
        # —— 也就是说旧行为在同分时本来就是顺序依赖的（同分在 RRF 里并不罕见：
        # 两个不同 chunk 分别在两路拿到相同名次就会同分）。
        #
        # 因此加 chunk_id 次级键不是「破坏了向后兼容」，而是把一处原本
        # 不确定的行为变确定。不变量 3（等权兼容）相应地只对非同分输入断言
        # 逐条相等，同分部分断言的是「确定性」——理由记在
        # tests/unit/test_fusion_rrf.py 对应用例的 docstring 里。
        fused_results.sort(key=lambda x: (-x.score, x.chunk_id))

        if top_k is not None and top_k > 0:
            fused_results = fused_results[:top_k]

        return fused_results
