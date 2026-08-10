# Quickstart: 带权重的结果融合

**Feature**: 005-weighted-fusion
**Date**: 2026-08-10

面向执行者的操作手册。

> ⚠️ **所有命令必须在 `.venv` 下运行。** 全局 Python 的 protobuf 是 5.29.3，`import chromadb` 会直接失败；`.venv` 里是 3.20.3。

---

## 前置检查

确认生效集合与索引就绪（Feature-004 的产物）：

```bash
.venv/Scripts/python.exe scripts/rebuild_bm25_index.py --inspect-only
```

预期看到 `default_text-embedding-v4` 为 v2 格式、含中文词条约 76%。

---

## 配置

`config/settings.yaml` 的 `retrieval` 段新增两项：

```yaml
retrieval:
  sparse_backend: bm25
  fusion_algorithm: rrf
  rrf_k: 60                 # 融合平滑参数，此前硬编码
  fusion_weights:           # 各检索路径的相对分量
    dense: 1.0
    sparse: 1.0
  top_k_dense: 20
  top_k_sparse: 20
  top_k_final: 10
```

**只有相对比例有意义**：`{dense: 1.0, sparse: 0.5}` 与 `{dense: 2.0, sparse: 1.0}` 产出完全相同的排序。写比值即可，别纠结绝对值。

**特殊取值**：

| 配置 | 效果 |
|---|---|
| `sparse: 0` | 关闭关键词路径，等价于纯语义检索 |
| 两路相等 | 与本 feature 之前的行为逐条一致 |
| 任一为负 / 全部为 0 / 非数值 | **启动即报错**，不静默回退 |

---

## 校准权重

### 第一步：产出检索缓存（有 API 成本，只需一次）

```bash
.venv/Scripts/python.exe scripts/calibrate_fusion_weights.py --build-cache --lang en
```

对 42 条英文金标各执行一次两路检索，把两路的**有序**标识列表缓存下来。

> **为什么先缓存**：权重只影响融合、不影响检索。缓存后扫权重是纯离线计算 —— 8 组权重从 384 次 API 调用降到 48 次，且后续可反复重跑。Feature-004 期间反复遭遇网关 503 与超时，这一步是让校准能跑完的前提。

### 第二步：离线扫描（零 API 成本，可反复跑）

```bash
.venv/Scripts/python.exe scripts/calibrate_fusion_weights.py --sweep --lang en
```

固定 `dense=1.0`，扫 `sparse ∈ {0, 0.1, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0}`。

**选择判据**（按优先级）：

1. **硬约束**：`recall ≥ 45.7%`（纯语义检索的水平）—— 消除倒退是本 feature 存在的理由
2. 满足硬约束者中选 `MRR` 最大
3. 若无人满足，选 `recall` 最大，并在记录中说明未达成

### 第三步：中文验证（不作为调优目标）

```bash
.venv/Scripts/python.exe scripts/calibrate_fusion_weights.py --build-cache --lang zh
.venv/Scripts/python.exe scripts/calibrate_fusion_weights.py --sweep --lang zh
```

中文金标仅 6 条，单条 case 即 16.7% 摆动，**只用于确认选定权重在中文上不倒退**。

---

## 三方对比（US3 的交付物）

```bash
.venv/Scripts/python.exe scripts/calibrate_fusion_weights.py --compare --lang en
```

产出「纯语义 / 等权混合 / 带权混合」的逐指标对比。三种配置**全部由同一份缓存重放**，因此差异纯粹来自融合权重，不含检索层面的随机波动 —— 这正是对照实验想要的干净。

### 验收要点

| 判据 | 期望 |
|---|---|
| 带权混合 recall | **≥ 45.7%**（纯语义水平），即倒退消除 |
| 带权混合 hit_rate | **≥ 69.0%**（纯语义水平） |
| 带权混合 MRR | 不低于等权混合的 0.502 |

> **可能的结果**：若最优权重落在 `sparse` 极低处（如 0.1），带权混合会收敛到接近纯语义检索。这仍是有效结果（倒退消除），但「混合严格优于任一单路」可能达不成 —— 届时校准记录须直说，不粉饰。「关键词路径在当前语料上贡献有限」本身就是有价值的工程结论。

---

## 回归验证

```bash
.venv/Scripts/python.exe -m pytest tests/unit -v
```

三条守卫测试必须通过（它们守的失败都是**静默的**）：

| 测试 | 守什么 |
|---|---|
| 顺序无关 | 交换传入路径的顺序，输出逐条不变。**权重与路径错配不会报错，只会让效果悄悄变差** |
| 空路无副作用 | 某路为空时，另一路的相对排序不变 |
| 等权兼容 | 权重相等时结果与本 feature 之前逐条一致 |

---

## 常见问题

**Q：改了 `fusion_weights` 但结果没变？**
A：确认改的是生效配置文件，且已重启。`Fusion` 在构造时读取权重，运行中改配置不生效。

**Q：启动报 `SettingsError: fusion_weights ...`？**
A：检查是否有负权重、全零、或非数值。这是刻意的**硬失败** —— 全零权重会让所有得分归零、排序退化为字典序，而这不会有任何报错。

**Q：配置里少写了某条路径的权重？**
A：缺省按 `1.0` 处理，不报错。设计如此：新增检索路径时不应强制所有部署同步改配置。

**Q：校准结论能直接搬到别的语料上吗？**
A：不能。权重是语料相关的，结论绑定当前的 MT5 技术文档语料。换语料需重新校准 —— 与项目既有的「换 Judge 需重新校准阈值」是同一类约束。

**Q：为什么不做「某路为空时把权重归一化到剩余路径」？**
A：那样**不改变任何可观测排序**（等比缩放是单调变换），却会让绝对得分随「另一路是否恰好为空」跳变、跨查询不可比，纯粹增加复杂度。详见 [research.md](./research.md) Decision 4。
