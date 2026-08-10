# Contract: 结果融合接口

**Feature**: 005-weighted-fusion
**Module**: `src/core/query_engine/fusion.py`
**Date**: 2026-08-10

本契约定义融合接口的入出参与权重语义。变更此契约必须同步更新本文件与 `tests/unit/test_fusion_rrf.py`。

---

## 为什么要改接口形态

v1 接口按**位置**接收各路结果：

```python
fuse(result_lists: List[List[RetrievalResult]], top_k: Optional[int]) -> List[RetrievalResult]
```

等权时这没问题。但代码里已经存在一处**顺序写反的注释**：

```python
# fusion.py:87        注释说   [sparse_result, dense_result]
# hybrid_search.py:204 实际传  [dense_results, sparse_results]
```

这个错误存活至今**正是因为等权时它无害**。一旦引入权重，同样的混淆会让语义路径拿到关键词路径的权重 —— 而系统照常运行、不报错，只是效果悄悄变差。

**因此 v2 按名字而非位置对应权重。**

---

## v2 接口

```python
def fuse(
    self,
    routes: Mapping[str, Sequence[RetrievalResult]],
    top_k: Optional[int] = None,
) -> List[RetrievalResult]
```

### 入参

| 参数 | 类型 | 约束 |
|---|---|---|
| `routes` | 路径键 → 该路的**有序**结果序列 | 键须为字符串；顺序即名次，调用方不得预先重排 |
| `top_k` | `Optional[int]` | `None` 或 ≤ 0 时返回全部 |

### 出参

按融合得分降序排列的 `List[RetrievalResult]`。每项的 `score` 为融合得分（**不是**任何单路的原始分数）；`text` / `metadata` 取自首个贡献该内容的路径。

### 得分公式

```
score(c) = Σ_r  weight[r] / (k + rank_r(c))
```

- `rank_r(c)`：内容 `c` 在路径 `r` 中的名次，从 1 起
- 未被路径 `r` 命中的内容，该项不计入
- `weight[r]`：构造融合器时注入；未指定的路径缺省为 `1.0`
- `k`：平滑参数，构造时注入，默认 `60`

---

## 行为契约

| 场景 | 行为 |
|---|---|
| `routes` 为空映射 | 返回 `[]` |
| 某路对应空序列 | 该路不贡献；**其余路的相对排序不变** |
| 全部路径均为空 | 返回 `[]` |
| 结果项 `chunk_id` 为空 | 跳过该项 |
| 同一 `chunk_id` 出现在多路 | 得分相加；`text`/`metadata` 取首个贡献者 |
| 权重全部相等 | 排序与 v1 **逐条一致** |
| 某路权重为 `0` | 该路不影响任何结果，等价于未传入 |
| 交换 `routes` 中键的插入顺序 | 输出**逐条完全不变** |

### 三条不变量（对应 SC-012 / SC-013 / SC-006）

1. **顺序无关**：`fuse({"dense": D, "sparse": S})` 与 `fuse({"sparse": S, "dense": D})` 输出逐条相等
2. **空路无副作用**：`fuse({"dense": D, "sparse": []})` 的排序与 `fuse({"dense": D})` 一致
3. **等权兼容**：所有权重相等时，输出排序与 v1 实现逐条一致

> 前两条的失败都是**静默的** —— 不抛异常、不告警，只是结果悄悄变差。因此必须由测试固定，不能靠 code review 兜底。

---

## 刻意不做的事：动态归一化

**不**在某路为空时把其权重重新分配给剩余路径。

理由：这样做**不改变任何可观测排序**（等比缩放是单调变换），却会让同一内容的绝对得分随「另一路是否恰好为空」跳变，使跨查询的得分不可比；且引入一个只在边界触发、无可观测收益的分支。

这条要求靠**不引入某段逻辑**来满足。需要测试守住它不被后人当作"优化"加回来。

---

## 构造契约

```python
Fusion(k: int = 60, weights: Optional[Mapping[str, float]] = None)
```

| 参数 | 来源 | 说明 |
|---|---|---|
| `k` | `settings.retrieval.rrf_k` | 此前是硬编码的 `DEFAULT_K = 60`，且 `Fusion()` 构造时不读任何配置 —— 属既有的配置驱动违规，本 feature 一并修正 |
| `weights` | `settings.retrieval.fusion_weights` | `None` 时全部路径按 `1.0` 处理，行为与 v1 一致 |

**权重的合法性校验在 `load_settings()` 完成**（宪法原则三，启动期快速失败），不在 `Fusion` 内重复校验 —— 单一校验点避免两处规则漂移。

---

## 与调用方的契约

`HybridSearch` 须：

1. 用 `settings` 构造 `Fusion`，不再无参构造（`hybrid_search.py:91`）
2. 按命名映射调用 `fuse`，不再传位置列表（`hybrid_search.py:204`）
3. 在 `finish_stage("fusion", ...)` 的 payload 中带上**本次生效的权重**（FR-008 / SC-008）
