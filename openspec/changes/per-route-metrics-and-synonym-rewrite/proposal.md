## Why

**融合后的指标量不出单路的改善,而本项目的瓶颈恰恰在单路。**

Feature-005 校准出的生效权重是 `sparse=0.1`,原因写在 `fusion.py` 开头:等权融合时
「关键词路径的噪音命中挤掉了语义路径的正确结果」。**把权重压到 0.1 是止血,不是治疗** ——
BM25 那一路的信噪比低才是根因。

问题是:现有 8 项指标量的**都是融合后的最终结果**。任何针对 sparse 的改进,
其效果都会被 `weight=0.1` 稀释到几乎看不见 —— 于是会得出「改写没用」的错误结论,
而改善其实真的发生了,只是被融合口径这把尺子量丢了。

这与本项目反复出现的失败模式同源:**尺子不对时,做对的事会被判为做错**。
上一次是第一代金标结构性惩罚重排(实测 MRR −0.1246,换金标后翻转为 +0.0764);
这一次是融合口径结构性掩盖 sparse 侧的改进。**所以分路径指标是硬前置,不是配套设施。**

同义词/术语扩展是四种改写策略里**唯一不需要 LLM** 的一个(零调用、零延迟、零 token),
且直击 BM25 的字面匹配缺陷 —— query 写 `SL` 而文档写 `止损` 时命中为零,而 dense 的
embedding 本来就对同义词鲁棒。**性价比最高,所以先做它。**

## What Changes

- **新增分路径评估口径**:评估报告在融合后指标之外,额外产出 **dense 单路**与
  **sparse 单路**各自的 `hit_rate` / `mrr` / `ndcg` / `recall`。这是本变更的**硬前置** ——
  没有它,后面那半个变更无法被判定成败
- **新增查询改写能力,默认关闭**:`query_rewrite.strategy` 取 `none`(默认) | `synonym`。
  `synonym` 从一份**人工维护的种子词表**把 query 关键词展开为同义词/缩写/别名
- **扩展词必须过同一个 tokenizer**:扩展发生在 `_extract_keywords()` **之后**,
  产出的词与索引端共用 `src/core/text/tokenizer.py`。两端切分口径漂移的失败是静默的
  (不报错,只是召回恒为空)
- **快速失败**:`strategy != none` 且词表缺失/不可解析时,`load_settings()` 直接抛
  `SettingsError`,**不留隐式默认值**(参照重排那条教训:兜底成纯英文 `ms-marco` 模型,
  对中文语料无效且不报错)

**不是 BREAKING**:默认 `none` 时行为与现在逐条相同,分路径指标是**新增字段**,
既有报告字段与基线 schema 不变。

## Capabilities

### New Capabilities

- `retrieval/query-rewrite`: 查询改写能力 —— 改写在什么位置发生、扩展词的切分口径约束、
  策略的开关语义与快速失败、以及改写必须在单次检索调用内部完成(调用方无插入点)。

### Modified Capabilities

- `evaluation/run-integrity`: 评估报告的完整性契约新增一项 —— 报告 MUST 按**检索路径**
  分别披露检索类指标,使「某一路的改善」不被融合口径掩盖。这与该能力既有的
  `metric_integrity`(按指标披露分母)是同一类要求的另一个维度。

## Impact

**代码**
- `src/core/query_engine/query_processor.py`:关键词扩展的挂载点
- `src/core/query_engine/`:新增改写器及其工厂(provider 无关,按既有可插拔模式)
- `src/observability/evaluation/eval_runner.py`:分路径指标的计算与落盘
- `src/core/settings.py` + `config/settings.yaml`:`query_rewrite.*` 配置段
- `config/synonyms_*.yaml`:新增人工种子词表

**数据**
- 评估报告 JSON 新增分路径指标字段;既有字段不变,旧报告仍可读

**成本**
- 运行期:**零** —— 查表,无 LLM 调用、无额外网络往返
- 评估期:分路径指标需对每条 case 额外记录两路的原始名次,**不增加检索次数**
  (两路结果本来就都在手里,现在只是也各自打一次分)

## 验收判据

**金标**:`tests/fixtures/golden_test_set_en_v2.json`(41 条,`pooled-llm-judged`)。
中文 `golden_test_set_zh_v2.json` 只有 6 条(一条 case 值 16.7%),**其 delta 一律按噪声
处理,不作为判定依据**,只用于确认没有明显倒退。

**主判据是 sparse 单路的 `MRR` 与 `nDCG`** —— 这是本变更唯一直接作用的对象:

1. **分路径指标本身可信**:`strategy: none` 时,分路径指标与用同一份金标手工核算的结果
   一致;且 dense 单路的数与 `fusion_weights.sparse=0` 时的融合后指标一致(这是它们
   在定义上应当相等的情形,可作为自检)
2. **同义词扩展提升 sparse 单路**:`sparse__mrr` / `sparse__ndcg` 相对 `strategy: none`
   有提升。**幅度不预设门槛** —— 词表是人工种子表,覆盖面有限,小幅提升即为有效信号;
   零提升或负提升同样是有价值的发现(说明这份语料的 query 与文档用词本就一致)
3. **融合后不倒退**:融合后的 8 项指标无显著下降。⚠️ 注意 `recall` / `hit_rate`
   **结构性偏向 dense** —— 它们由 dense 检索回填的历史包袱在第二代金标下已减轻,但
   sparse 贡献挤掉 dense 命中仍会拉低它们。**看 `MRR` / `nDCG` 判定,不看 `recall` / `hit_rate`**
4. **零成本得到验证**:改写路径不产生任何 LLM 调用(断言测试守住,不靠人工检查)
5. 单元测试全绿(硬约束 7)

⚠️ **A/B 必须用 `--no-generate-answers` + `backends: [custom]`** —— 本变更是纯检索改动,
带上答案生成与 judge 会把耗时从分钟级推到小时级,且引入与本变更无关的方差。

## Non-goals

- **不做 HyDE**。它只帮 dense(已经调得不错的那一路),且生成的散文会往 BM25 里引入语料
  中不存在的词,**对 sparse 有害** —— 正好打在本项目的弱项上。它也是四个策略里唯一需要
  改动检索层接口的(dense 与 sparse 的输入不再是同一个 `ProcessedQuery`),改造量不在
  同一量级
- **不做 Multi-Query**。对症,但需要 LLM 调用(每次查询烧 token + 1-2s 延迟),
  留作独立变更。届时可零改动复用 `Fusion.fuse()` 的多路签名
- **不做 Step-back / 策略路由**。适用面窄,且需额外一层分类
- **不重新校准 `fusion_weights`**。改写提升 sparse 信噪比后 `0.1` 必然过时,但那要等
  本变更测出实际提升幅度之后才有依据。⚠️ 已知事实:在第二代金标上重测,当前最优是
  **0.75** 而非生产的 0.1(端到端 MRR +0.0163),曲线见 `openspec/BACKLOG.md` 的 C4 条目 ——
  **留作后续变更,与改写联合校准**
- **不从语料自动挖掘词表**。本次用人工种子表,先验证「同义词扩展对这份语料到底有没有用」
  这个更根本的问题。有用再谈自动化
- **不改 `custom_evaluator.py` 的指标公式**。分路径是换输入,不是换算法
- **不动融合算法本身**
