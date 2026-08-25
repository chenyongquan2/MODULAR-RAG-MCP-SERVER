## Context

动机见 [proposal.md](proposal.md) § Why；行为契约见两份 delta 规格。这里只记与实现相关的现状：

- `QueryProcessor.process()` 产出 `ProcessedQuery`，`HybridSearch` 用 `keywords` 喂 sparse、用
  `original_query` 喂 dense。
- **`ProcessedQuery.rewritten_query` 已经存在但是个死字段** —— 定义了、有文档、`from_dict`
  会读，但**全仓没有任何生产路径写它或读它**（[types.py:302](../../../../src/core/types.py#L302)）。
  它是当初为改写预留的钩子。
- `EvalRunner` 只通过 `hybrid_search.search()` 拿**融合并重排后**的结果，
  两路各自的名次在它眼里不存在。
- `Fusion.weight_for()` 是 `self._weights.get(route, 1.0)`，查不到路径名**静默回落 1.0**。

## Goals / Non-Goals

**Goals**（设计层边界，范围见 proposal）：
- 分路径指标不改变检索行为本身 —— 它只是对已有的两路结果各打一次分
- 改写挂载点唯一，不在 dense 与 sparse 两侧各留一份
- 让死字段 `rewritten_query` 变成活的，而不是另起一个新字段

**Non-Goals**：
- 不引入路径族权重查找（本变更不新增路径名，见 D4）
- 不改 `HybridSearch.search()` 的既有签名与返回类型

## Decisions

**D1 · 分路径结果经新增的显式返回通道暴露，不动 `search()`**
`HybridSearch` 增一个返回「融合结果 + 各路原始有序结果」的方法，`search()` 原样保留并转调它。
- 否掉「改 `search()` 返回类型」：MCP 与 `scripts/query.py` 都在用，是无谓的 breaking。
- 否掉「让 `EvalRunner` 自建 dense/sparse 检索器」：`calibrate_fusion_weights.py` 正是这么做的，
  代价是生产链路一改它就悄悄漂移 —— 本变更不该再造一个漂移点。
- 否掉「从 trace 里读」：trace 是观测通道，拿它当数据通道会让「关掉 trace 就算不出指标」。

**D2 · 分路径指标复用现有指标函数，只换输入**
把某一路的有序 chunk_id 列表当作「检索结果」喂给同一套 `hit_rate/mrr/ndcg/recall` 计算。
- 否掉「为分路径另写一套打分」：两套公式必然漂移，而漂移是静默的。
- 自检手段写进了规格：`fusion_weights` 只留一路时，该路的分路径指标必须等于融合后指标。

**D3 · 改写挂在 `QueryProcessor.process()` 内、`_extract_keywords()` 之后**
扩展出的词与原关键词一起过 `src/core/text/tokenizer.py`，结果写进 `ProcessedQuery.keywords`；
原始与改写后的词面同时留在 `ProcessedQuery` 上供追踪。
- 否掉「挂在 `HybridSearch` 里」：那样 dense 与 sparse 两侧要各自决定用不用改写结果，
  等于把一个决策拆成两处。
- **同义词扩展只改 `keywords`（sparse 的输入），不改喂给 dense 的 `original_query`** ——
  dense 的 embedding 本就对同义词鲁棒，往里塞同义词只是加噪。

**D4 · 不新增融合路径名，因此本变更不触发权重查表陷阱**
同义词扩展是「把一路的输入变好」，不是「多开一路」，融合仍是 `{"dense", "sparse"}` 两路。
⚠️ **但后续的 Multi-Query 会新增路径名**，届时 `weight_for()` 查不到就回落 1.0，
会让 Feature-005 校准出的 `sparse=0.1` 被悄悄作废且不报错。**本变更在
`fusion.py` 留一条指向该风险的注释，把修复留给引入多路的那个变更**（在这里改属于
为不存在的需求做设计）。

**D5 · 词表格式：`词 → 同义词列表`，双向展开**
```yaml
# config/synonyms_zh.yaml
止损: [SL, stop loss, stoploss]
点差: [spread]
```
命中 `止损`、`SL`、`stop loss` 任一者，都展开出该组全部词面。
- 否掉「单向展开」：用户既可能写术语也可能写缩写，单向会漏掉一半情形。
- 否掉「正则/模式匹配」：本次是种子词表，先验证有没有用；模式匹配的维护成本与误伤面都更大。

**D6 · 词表在 `load_settings()` 期加载并校验，不在每次查询时读盘**
校验含：文件存在、可解析、值必须是列表。任一不满足抛 `SettingsError`（本模块既有约定，
**不是 `ValueError`**）。

## 新增配置

```yaml
# config/settings.yaml
query_rewrite:
  # none（默认）| synonym
  # 默认关闭 —— 与 rerank.backend 同构，一个默认不启用的能力不该向所有调用方收税。
  strategy: none
  # strategy: synonym 时必填。刻意不设隐式默认值 —— 重排那次的兜底默认值
  # （纯英文 ms-marco 模型）对中文语料无效且不报错，是「看起来可配、实际取
  # 默认值」的典型。缺失/不可解析 → load_settings() 抛 SettingsError。
  synonym_dict: ""
```

```python
# src/core/settings.py
@dataclass
class QueryRewriteSettings:
    strategy: str = "none"          # VALID_QUERY_REWRITE_STRATEGIES 校验
    synonym_dict: str = ""          # strategy != none 时必填
```

## 七条硬约束合规性

| # | 约束 | 本变更的合规方式 |
|---|---|---|
| 1 | Provider 无关 | 改写策略按既有可插拔模式注册（基类 + 工厂），`src/core/` 不 import 具体策略实现，无 `if strategy == "synonym"` 分支 |
| 2 | 配置驱动 | `query_rewrite.*` 全部经 `settings.yaml`，每个可调项有 dataclass 字段对应；词表路径可配 |
| 3 | 快速失败 | 未知策略、词表缺失/不可解析均在 `load_settings()` 抛 `SettingsError`，**不 try/except 后静默回落 none** |
| 4 | 追踪显式 | 改写留痕经既有的显式 `trace` 参数打点，不引入 `contextvars` / 全局状态 |
| 5 | 结构化日志 | 走 `observability.logger.get_logger()`，无 `print()` |
| 6 | 类型安全 | 新增 public 函数带完整注解；`ProcessedQuery` 是既有共享类型，不新建平行类型 |
| 7 | 测试支撑变更 | 每个实现任务配 `tests/unit/`；含一条「零成本策略不得引入模型调用」的断言测试（规格硬要求）与一条「改了词表结论就该变」的用例 |

## Risks / Trade-offs

- **种子词表可能对这份语料完全无效** → 这是可接受的结果而非失败。proposal 的验收判据
  刻意不设提升门槛：零提升说明「query 与文档用词本就一致」，同样是有价值的发现，
  且**分路径指标会让这个结论第一次可被看见**。
- **分路径指标让报告变大** → 只多 8 个聚合数与每 case 两个 id 列表；`case_results`
  本就存了 contexts 全文，占比可忽略。
- **`recall` / `hit_rate` 仍偏向 dense** → 已在 proposal 验收判据里限定为「看 MRR / nDCG 判定」。
- **改写让 `sparse=0.1` 更过时** → 已知。当前最优实测是 0.75（端到端 MRR +0.0163），
  刻意留给后续变更与改写联合校准，避免在本变更里把两个变量搅在一起。
- **词表维护成本随语料走** → 与 `fusion_weights`、`acceptance_thresholds` 同属「语料相关、
  换语料需重校准」那一类，在配置注释里标注。

## Migration Plan

无数据迁移。默认 `strategy: none` 时行为逐条不变，分路径指标是新增字段，旧报告仍可读。
回滚 = 把 `strategy` 改回 `none`（或整段删除），无需回滚代码。
