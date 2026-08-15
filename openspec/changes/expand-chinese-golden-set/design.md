## Context

动机与实测证据见 [proposal.md](proposal.md) § Why，行为契约见 [specs/evaluation/testset-synthesis/spec.md](specs/evaluation/testset-synthesis/spec.md)。

现状约束：

- `testset_synthesizer.py:122-176` 已有 adapt 的重试 + 磁盘缓存 + 失败硬报错。**缺的只有一件事：校验产物**。它只捕获异常，而实测的失败形态是「不抛异常但没翻译」
- 缓存目录 `logs/ragas_adapt_cache/<language>/` 由 RAGAS 自己写，格式不受我们控制 —— 元数据只能旁挂，不能塞进 RAGAS 的文件
- 标注侧（第二代 `label_golden_chunks.py`）已完备且经英文 42 条实战：池化、分级判定、异源约束、续跑、上限、抽检导出全在
- 精修侧 `refine_testset.py --auto-mode` 已完备（Feature-003）
- 网关实测常态性中断，合成（单次 adapt 约 5 分钟 + 生成 ~100 条）需要能重来

## Goals / Non-Goals

范围边界见 proposal § Non-goals。设计层面两条：

- **Goal**：语言校验做成**独立可测的纯函数**，不依赖 RAGAS。它只回答「这段文本是不是目标语言」，因此不必联网、不必装 ragas 就能跑单测。
- **Non-Goal**：不做通用语言识别（不引入 `langdetect` 之类）。目标语言只需区分「有没有该语种的特征字符」，字符集判断足够且零依赖 —— 引入语言识别库会给一个二值判断带来模型不确定性。

## Decisions

**D1 · 语言校验用字符集占比，不用语言识别库**：中文查 CJK 统一表意文字区间占比。
否掉 `langdetect` / `fasttext` —— 给一个「这段 prompt 到底有没有被翻译」的判断引入概率模型，反而多一处不确定性；而且新增依赖违背「零依赖能解决就零依赖」。代价是每加一门语言要补一条字符集规则，但 `lang_to_ragas` 本来就要逐语言登记。

**D2 · 阈值用「占比」而非「计数」**：CJK 字符数 / 总字符数 ≥ 阈值。
否掉绝对计数 —— prompt 长度差异很大（1.6KB ~ 4.5KB），固定计数对短 prompt 过严、对长 prompt 过松。实测未翻译时占比恒为 **0.0%**，翻译后 prompt 中仍会保留大量 JSON schema 与英文字段名，所以阈值应取一个**远低于「纯中文」但明显高于 0** 的值（初值 0.05，需按首轮实测校准）。

**D3 · 缓存元数据旁挂为 `_adapt_metadata.json`**，与 RAGAS 自己的文件同目录。
否掉改写 RAGAS 的缓存文件 —— 那是上游格式，塞私货会在 RAGAS 升级时炸。旁挂文件缺失即视为「未校验的旧缓存」，按 spec 不得使用。

**D4 · 校验在 adapt 之后、写缓存之前**：RAGAS 的 `adapt()` 自己会写缓存，所以顺序上无法阻止它写。
处理方式：adapt 后立即校验，**不通过就删除刚写出的缓存目录**并报错。否掉「先写后标记无效」——留着坏缓存等下次判断，等于把 spec 的「MUST NOT 使用未通过校验的缓存」寄托在读取方永远记得检查上。

**D5 · 合成端模型的选择用实测定，不用既有印象**：先用一个只跑 adapt 的探针脚本，对候选模型各跑一次，看产物 CJK 占比。
否掉直接换成 `z-ai/glm-5.2` 就开跑 —— 那是把「max_tokens 误诊」的教训反向套用成另一个未经验证的假设。**本次会话的教训恰恰是：别在没看原始输出前下模型能力的结论。**

**D6 · 语种一致性统计在合成产物上做，不在 RAGAS 内部做**：拿到候选集后统计 question 字段的语种。
它与 D1 共用同一个纯函数。这样即使将来换掉 RAGAS，这条校验依然成立。

**D7 · 新中文金标走完整三步（合成 → 精修 → 第二代标注），不复用第一代的 6 条**。
否掉「补 34 条凑够 40」—— 两代标注口径不同，混在一起就再也分不清哪条是怎么来的，而本项目刚因为「两代不可比」吃过亏。旧文件原样保留作历史。

## 新增配置项

`config/settings.yaml` 的 `evaluation` 段：

```yaml
evaluation:
  synthesis:
    # 适配产物的目标语言字符占比下限。低于此值判定为「未翻译」，失败且不落盘。
    # ⚠️ 实测未翻译时恒为 0.0%；翻译后 prompt 仍含大量 JSON schema 与英文字段名，
    #    所以这个值应远低于「纯中文」的水平。0.05 是初值，需按首轮实测校准。
    adapt_language_ratio_min: 0.05
    # 合成候选中「问题语种与目标语言不一致」的比例上限，超过即告警。
    # 第一代实测是 70%(33/47) —— 那是适配未生效的典型信号。
    question_language_mismatch_warn: 0.20
```

`src/core/settings.py`：

```python
@dataclass
class SynthesisSettings:
    """金标合成配置。"""

    adapt_language_ratio_min: float = 0.05
    question_language_mismatch_warn: float = 0.20
```

`load_settings()` 校验：两项均在 `[0.0, 1.0]`，违规抛 `SettingsError`（沿用本模块既有约定，不是 `ValueError`）。

## 七条硬约束合规性

| # | 约束 | 本设计如何满足 |
|---|---|---|
| 1 | Provider 无关 | 合成端模型经 `LLMFactory` 创建；语言校验是纯函数，不知道任何 provider |
| 2 | 配置驱动 | 两个阈值均为配置项 + dataclass 字段；语言映射集中在 `lang_to_ragas`，不散落 |
| 3 | 快速失败 | 阈值启动期校验；**adapt 产物不通过语言校验即失败且删除坏缓存**（本变更的核心）；未支持的语言明确报错而非按默认语言合成 |
| 4 | 追踪显式 | 合成是离线脚本，不在查询链路；如需打点则 trace 作显式参数 |
| 5 | 结构化日志 | 走 `get_logger(__name__)` 写 stderr；**脚本运行须加 `-u`**（本项目已因 stdout 全缓冲误判过「卡死」） |
| 6 | 类型安全 | 新增 public 函数完整注解；语言校验的返回值定为明确的结果类型而非裸 bool |
| 7 | 测试支撑变更 | 语言校验是纯函数 → 单测不触网、不装 ragas；adapt 校验路径用假 adapt 产物覆盖 |

## Risks / Trade-offs

- **可能没有任何可用模型能完成中文 adapt** → 那本变更就止步于「把静默失效变成显式失败」，并如实记录哪些模型试过、各自的 CJK 占比。**这仍然是净收益**：现在的状态是「以为合成了中文、实际是英文」，届时至少是「知道做不到」。备选路径（不在本次范围）：绕开 RAGAS 的 evolution，直接用 LLM 从中文 chunk 生成问题。
- **阈值 0.05 是猜的** → 与本项目所有阈值同性质（`keep_threshold` / `relevance_threshold` / `human_agreement_warn` 都是初值）。首轮实测后校准，且实测的两端差异极大（未翻译 0.0% vs 翻译后应显著为正），落在中间的概率低。
- **换合成端模型会让 `acceptance_thresholds` 失效** → 这是本项目已记录的陷阱。若最终换了 `judge_llm`，必须在验收记录里显式标注，并说明既有英文基线是否受影响。
- **约 1400 次标注调用 + 网关常态中断** → 标注侧的续跑与上限已在上一个变更实战验证（跨 4 次中断累积完成 42 条）。合成侧无续跑，失败需整体重来，但单次成本远低于标注。
- **中文结论可能与英文相反** → proposal § Non-goals 已明确这是有价值的发现。上一个变更实测的跨语言压分现象（0.2973 vs 0.9998）提示中文侧确实可能不同。

## Migration Plan

1. 删除被污染的缓存：`logs/ragas_adapt_cache/chinese/`（现存内容已确认 CJK = 0，无保留价值）
2. 跑模型探针（D5），据实测选定合成端模型
3. 合成 → 精修（`--auto-mode`）→ 第二代标注，产出 `golden_test_set_zh_v2.json`
4. `settings.yaml` 的 `golden_test_sets_by_lang.zh` 指向新文件；旧文件保留
5. 重标中文基线（旧基线是 6 条 + 第一代标注，与新集合完全不可比）

**回滚**：`golden_test_sets_by_lang.zh` 指回第一代文件即可。旧金标与旧基线全程未被修改。

## Open Questions

- **翻译后的 prompt 里 CJK 占比实际会是多少** —— 决定阈值定在哪。这不改变 specs、方案或任务拆分，属首轮实测后调参的范围。
- **精修阶段的 `--auto-mode` 预筛端是否需要换模型** —— 取决于合成端最终选了谁（两者必须异源）。判据已由 Feature-003 确立，只是届时代入新值。
