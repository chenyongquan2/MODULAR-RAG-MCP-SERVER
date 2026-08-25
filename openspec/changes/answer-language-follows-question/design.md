## Context

动机与实测数据见 [proposal.md](proposal.md)；行为契约见 delta 规格。这里只记与实现相关的现状：

- `ResponseBuilder.build(query, results, trace=None, **kwargs)` 返回
  `StructuredContent(markdown, citations)`（[citation_generator.py:36](../../../src/core/response/citation_generator.py#L36)），
  **已经收 `trace` 参数**，所以打点不需要改签名。
- 提示词有两处：`chat()` 的 system 消息（硬编码中文一句）与
  `_load_default_prompt()` 返回的模板。**两处都没提输出语言。**
- `language_check` 只登记了 `zh` 一种语言（`_LANGUAGE_RANGES`）。
  `language_char_ratio(text, "en")` 会**抛 `ValueError`**。
- `evaluation.synthesis.adapt_language_ratio_min = 0.05` 已存在，语义是
  「目标语言字符占比下限」，校准锚点是「未翻译时实测恒为 0.0%」。

## Goals / Non-Goals

**Goals**（设计层边界，范围见 proposal）：
- 答案语言由**问题**决定，判定规则单一且可从配置读到阈值
- 语言一致性随每次回答产出，且**复用**既有判定实现
- 检索侧零改动 —— 有回归判据守住

**Non-Goals**：
- 不做通用语言识别（见 D2）
- 不引入 `answer_language` 配置项
- 不改 `StructuredContent` 之外的返回契约

## Decisions

**D1 · 提示词双语书写 + 显式声明输出语言**
system 消息与模板改为中英并列，并加一句「用提问所用的语言回答」。
- 否掉「按检测到的语言动态换整份提示词」：那要维护 N 份模板，且模板漂移是静默的
  （中文版改了英文版没改，只有英文提问才暴露）。一份双语模板只有一处真相。
- 否掉「只加一句英文要求、模板其余保持中文」：那仍是「一屋子中文指令 + 一句例外」，
  模型的语言倾向来自整体而非单句。

**D2 · 语言判定 = CJK 占比二分，并且**只**声称这么多
用 `language_char_ratio(text, "zh")` 取 CJK 占比：≥ 阈值判为 `zh`，否则判为 `non-zh`。
- **这不是通用语言识别**，是「中文 vs 非中文」。本项目语料是中英双语，够用；
  声称更多就是过度承诺 —— 一段法文会被判成 `non-zh`，而我们不会知道。
  规格里的用词因此是「按占主导的那种语言」，不是「识别出语种」。
- 否掉「引入 langdetect / fasttext」：新增依赖 + 概率输出 + 短文本不稳，
  换来的精度对一个双语语料毫无价值。
- 否掉「在 `language_check` 里登记 `en` 字符集」：拉丁字母在中文文本里也大量出现
  （API 标识符），按占比判 `en` 会与按占比判 `zh` 互相矛盾。**二分只能有一个基准语言。**

**D3 · 阈值复用 `synthesis.adapt_language_ratio_min`，不新增配置项**
它的语义正是「目标语言字符占比下限」，与这里要的判定完全同构，且已有 0.05 这个
经过校准的锚点。
- 否掉新增 `response.language_threshold`：两个字段量同一件事必然漂移，
  而且第二个字段的值没人会去校准 —— 那就是又一个 `top_m`。
- ⚠️ 代价：语义上它挂在 `synthesis` 下，而这里是生成端在用。**在两处都加注释指明
  这次复用**，避免后来者以为它只服务合成。若将来两者需要不同阈值，届时再拆
  （那时会有真实的调用方要求，不是现在的猜测）。

**D4 · 一致性结论挂在 `StructuredContent` 上，同时打 trace**
`StructuredContent` 增一个可选的语言元数据字段；`build()` 同时把它写进 trace 的
生成阶段打点。
- 两处都要：MCP 调用方拿到的是 `StructuredContent`（trace 可能没开），
  而评估侧与仪表盘读 trace。只留一处会让另一条路看不见。
- 否掉「只打 trace」：那样「关掉 trace 就测不出语言一致性」——
  把观测通道当数据通道，本项目在分路径指标那里已经拒绝过一次。

**D5 · 无法判定时记 `measured: false`，不回落成「一致」**
问题或答案为空、或只有标点/数字/代码时，显式标未判定。
- 这是本项目反复确立的形态（`_synthesis_metadata.language_consistency`、
  `aggregate_metrics_by_route` 皆然）：**回落成看起来正常的默认值，会让「没测」
  和「测过且没问题」长得一模一样。**

## 提示词改动（示意，非最终文案）

```
system: You are a professional knowledge assistant. Answer strictly based on the
        provided context. **Reply in the same language as the question.**
        你是一个专业的知识助手，仅基于所提供的上下文回答。**用提问所用的语言回答。**
```

模板同样并列书写，并保留既有的 `{context}` / `{query}` 占位符与引用标记要求
（`[1]` `[2]`）—— 引用格式不在本变更范围内，不得顺手改。

## 七条硬约束合规性

| # | 约束 | 本变更的合规方式 |
|---|---|---|
| 1 | Provider 无关 | 只改提示词与判定逻辑，不 import 任何具体 LLM 实现；无 `if provider == ...` |
| 2 | 配置驱动 | 阈值走 `settings`（复用既有字段，见 D3），不硬编码；**刻意不新增**语言开关 |
| 3 | 快速失败 | 复用字段已有 `[0.0, 1.0]` 校验。判定不到时**显式标未判定**而非静默回落（D5） |
| 4 | 追踪显式 | 走 `build()` **既有**的 `trace` 参数，不新增签名、不用全局状态 |
| 5 | 结构化日志 | `observability.logger.get_logger()`，无 `print()` |
| 6 | 类型安全 | `StructuredContent` 是既有共享类型，加可选字段而非新建平行类型 |
| 7 | 测试支撑变更 | 每个实现任务配 `tests/unit/`；含「检索侧逐位不变」的回归断言与「答案语言跟随问题」的正反用例 |

## Risks / Trade-offs

- **双语提示词让模型偶尔回两种语言** → 由语言一致率这个指标直接暴露；
  真出现就是文案问题，改文案而不是加逻辑。
- **CJK 占比二分对「中文问题里大量英文标识符」可能误判** → 阈值 0.05 很低
  （5% 汉字即判中文），偏向把混合问题判成中文，与语料实际（81.4% 中文）一致。
  ⚠️ 反向误判（纯英文问题被判成中文）需要 5% 以上汉字，正常英文提问不会触发。
- **RAGAS 降级率可能降得不如预期** → 见 proposal 的「已知上限」：中文侧本来就修不好。
  **验收的主判据是语言一致率，不是 RAGAS 分数** —— 后者分母浮动，不可靠。
- **复用 `synthesis` 下的阈值语义别扭** → 已在 D3 权衡；两处加注释，不拆字段。

## Migration Plan

无数据迁移。行为变化是**刻意的**（英文问题的答案从中文变英文），这就是本变更的目的。
回滚 = 还原提示词文案，无需回滚代码结构。

⚠️ 历史评估报告里的答案仍是旧语言 —— 跨本变更比较 RAGAS 生成类指标时，
差异同时包含「语言修好了」与「模型输出变了」两个因素，**不可归因到单一原因**。
