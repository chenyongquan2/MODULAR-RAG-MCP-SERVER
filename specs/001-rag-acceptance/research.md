# Research: RAG 质量验收(中英双语基线)

**Feature**: 001-rag-acceptance | **Date**: 2026-04-25 | **Status**: Phase 0 complete

本文件记录 plan 阶段需要锁定的 7 个关键技术决策。每条采用"Decision / Rationale / Alternatives considered"三段式。

---

## Decision 1: RAGAS 库版本固定

**Decision**:本 feature MVP 锁定 RAGAS `0.1.x` 系列(具体次版本由 tasks 阶段第一个 setup task 在 `pyproject.toml` 中固定为单一已验证版本,例如 `ragas==0.1.21`),整个 Feature-001 实施期内**不允许升级**。

**Rationale**:
- RAGAS 0.x → 1.x 之间 API 大幅重构(metrics 类初始化方式、LLM/embedding 注入方式、`evaluate()` 入参 schema 全部变了),实施期升级会导致代码无法编译或行为漂移
- 本 feature 输出的"基线"是后续 SC-005 / SC-008 回归红线的依据;Judge LLM 之外,RAGAS 库本身的版本也属于"判分尺度"的一部分。版本变了 = 基线失效
- 锁单一版本符合宪法 § II 配置驱动的精神(行为差异由配置控制,非 implicit 库版本)

**Alternatives considered**:
- ❌ 用 `^0.1` 让 pip 自动选最新 0.1.x — 不同机器 / 不同时间装出来版本不同,多人协作或 CI 复现时基线不可比
- ❌ 一开始就上 RAGAS 1.x — 1.x 在 2026-04 周边稳定性还在迭代;且 0.1.x 的 8 项指标已覆盖本 spec 所需,无 1.x 独有功能依赖
- ❌ 不固定,允许 plan 期升级 — 违反"基线指标稳定"的核心约束;若必须升级,通过新 feature 走 SDD 流程登记影响

**实施提示**:tasks 阶段第一个 setup task(预计 T001)在 `pyproject.toml` 的 dependencies 中加一条精确版本号(`ragas==0.1.21` 或最终选定的版本),并在 README / quickstart 提示"该版本是基线锚定点,擅自升级会破坏 SC-005 / SC-008 的可比性"。

---

## Decision 2: Judge LLM 接入 RAGAS 的方式 — LangChain 包装层

**Decision**:在 `src/observability/evaluation/ragas_evaluator.py` 内新增一个**轻量包装层**,把项目 `LLMFactory.create(settings)` 产出的 `BaseLLM` 实例包装成 RAGAS 期待的 LangChain `BaseLLM` 子类,通过 `langchain-openai` 的 `ChatOpenAI` 兼容路径或自定义 LangChain `BaseLLM` 子类实现。Embedding 同理:把 `EmbeddingFactory.create(settings)` 的 `BaseEmbedding` 实例包装成 LangChain `Embeddings` 子类。

**Rationale**:
- RAGAS 0.1.x 的 metrics 类(`Faithfulness` / `AnswerRelevancy` / `ContextPrecision` / `ContextRecall`)都通过 `metric.llm = LangchainLLMWrapper(...)` 注入 LLM;它**不接受**项目自定义的 `BaseLLM` 接口
- 项目 `LLMFactory` 的 5 个 provider 中,GLM / OpenAI / Azure / DeepSeek 都走 OpenAI 兼容协议,**可以**用 LangChain 的 `ChatOpenAI` 直接接入(只换 base_url + model + api_key);Ollama 走 LangChain `ChatOllama`
- 包装层让宪法 § I "Provider 无关性"得到满足:`RagasEvaluator` 业务逻辑只 import `LLMFactory`,不 import 具体 provider;LangChain 包装层只是**适配 RAGAS 库期待的接口**,不是 provider 选择
- 同样的包装思路用在 embedding 上(`langchain.embeddings.OpenAIEmbeddings` 或自定义 `Embeddings` 子类)

**Alternatives considered**:
- ❌ 让 RAGAS 直接读环境变量 / RAGAS 自己的 OpenAI 配置 — 完全违反宪法 § I / § II,Judge 选择脱离了项目配置体系,无法保证 FR-016 的"复用 LLMFactory 的 5 个 provider"
- ❌ Fork RAGAS 改 metric 类源码让它接受项目 BaseLLM — 维护成本太高,与"MVP 不重写既有评估器"的本 feature 范围相悖
- ❌ 跳过 RAGAS 自己实现 4 项指标 — 重新发明轮子,违反 spec § Assumptions "现有评估代码可复用",也无法获得 RAGAS 论文级的实现保真度

**实施提示**:tasks 阶段相关任务(预计 T-Judge-Wrapper)只新增一个小工具函数 `_build_ragas_judge(settings)` 和 `_build_ragas_embedding(settings)`,在 `RagasEvaluator.__init__()` 中调用一次,把 8 个 RAGAS metrics 全部注入同一对 LLM + Embedding。

---

## Decision 3: 评估报告归档与基线标记的存储机制 — 文件系统 JSON

**Decision**:
- 评估报告归档:每次评估产出一份 `logs/evaluation_reports/<run_id>.json`(`run_id` 用 UUID4)+ 一份累积索引 `logs/evaluation_reports/index.jsonl`(每行一条 `{run_id, collection, created_at, acceptance_status, judge_llm_identifier, embedding_identifier}` 元数据,供 dashboard 趋势页读取)
- 基线标记:单一文件 `logs/baselines.json`,结构为 `{<collection>: {current_baseline_run_id: <uuid>, history: [<uuid>, ...]}}`;每个 collection 一个 entry

**Rationale**:
- 评估报告是天然 append-only 写,无更新需求 → 文件系统胜过数据库
- 基线标记是 collection 维度的小状态(每个 collection 一个 current + 短小 history),JSON 单文件足以,引入数据库是过度工程
- 与项目既有 `logs/traces.jsonl` 的 JSONL 累积模式一致,dashboard 已有读 JSONL 的代码可参考
- `index.jsonl` 让 dashboard 趋势页(US3 AS3)O(N) 扫描即可,N ~ 几十次评估,完全可接受

**Alternatives considered**:
- ❌ SQLite — MVP 阶段无并发写需求,引入 schema 演进成本(测试集 tags 字段后续可能扩展)
- ❌ 把基线标记藏在 `logs/baselines/<collection>/current.txt` 的目录结构里 — 比单文件复杂,不如显式 JSON
- ❌ 不归档报告,只把"当前基线"和"上一次评估"留在内存 — 无法支持 SC-005 30 天回看 + US3 AS3 趋势折线

**实施提示**:`BaselineManager` 用文件级原子写(写临时文件 + 重命名)避免半写状态;`logs/baselines.json` 加 schema 版本字段 `_schema_version: 1` 便于未来演进。

---

## Decision 4: 不新增 component 类型层 — `threshold_evaluator` / `baseline_manager` 不进 `src/libs/`

**Decision**:把 `threshold_evaluator.py` / `baseline_manager.py` / `testset_synthesizer.py` 三个新文件放在 `src/observability/evaluation/` 下,**不**作为新的 base + factory pattern 组件层注册到 `src/libs/`。

**Rationale**:
- 宪法 § "架构稳定性" 明确说"新增组件类型层级"需要"plan.md 中证明现有抽象层无法满足"——本 feature 这 3 个新文件:
  - `ThresholdEvaluator` 是无状态纯函数式类(读阈值,打 pass/fail),不是可替换的 provider
  - `BaselineManager` 是文件 I/O 工具类,也不是可替换 provider
  - `TestsetSynthesizer` 是 RAGAS TestsetGenerator 的薄包装,不需要"切换合成器 provider"语义
- 它们都是**评估编排层**的工具,逻辑上属于 `EvalRunner` 的伙伴,放 `src/observability/evaluation/` 最自然(`EvalRunner` 也在那)
- 强行抽象成 base + factory 是过度工程;后续若真有"换合成器 backend"需求,可再走 SDD 升级

**Alternatives considered**:
- ❌ 新建 `src/libs/baseline/` + `base_baseline.py` + `baseline_factory.py` — 当前只有一个实现(JSON 文件),未来无可见的备选 backend,抽象层是空壳
- ❌ 把 `threshold_evaluator` 直接合并进 `EvalRunner.run()` 的尾部 — 让 EvalRunner 职责膨胀,单独类便于单元测试覆盖 FR-013

**实施提示**:`src/observability/evaluation/` 不强制 base + factory(它本身就是"项目内评估编排"的位置,不是"评估算法 provider 池");新文件直接定义具体类即可。

---

## Decision 5: by-tag 聚合的 schema 与跳过策略

**Decision**:
- 命名规则:`aggregate_metrics_by_<dimension>.<value>.<metric>`,例如 `aggregate_metrics_by_content_type.code.ragas__faithfulness`
- 切片维度:MVP 阶段固定支持 `content_type` 与 `difficulty`(共两个维度),不做 `language` × `content_type` 的笛卡尔交叉切(避免噪声)
- 跳过策略:任一切片样本量 < 5 时,该切片在报告中存为 `null` 并在同 entry 加 `_skipped_reason: "n_samples=<n><5"`
- by-tag 切片**不参与** FR-013 的 pass/fail(spec § Clarifications Q2 已锁)

**Rationale**:
- 命名规则与 FR-015 一致(`aggregate_metrics_by_content_type.<value>.<metric>`),dashboard 解析容易
- 维度选 `content_type` 与 `difficulty` 是因为它们是**能力维度**,切片有诊断价值;`language` 单语种评估天然只有一个值;`doc_version` MVP 阶段只有 `v1`,切片冗余
- 不做笛卡尔交叉避免组合爆炸(2 × 2 × 2 × 4 = 32 切片,每片样本极少)
- < 5 样本跳过且显式标注,避免使用方误读"切片缺失 = 系统问题"

**Alternatives considered**:
- ❌ 全维度笛卡尔切 — 噪声大,可读性差
- ❌ < 5 样本时强行算 — 极小样本均值波动,误导
- ❌ 切片不显式标注 skipped,直接缺字段 — 使用方分不清"切片不存在"还是"系统漏算"

**实施提示**:`EvalRunner` 内 by-tag 聚合作为独立 helper 函数 `_aggregate_by_tag(case_results, dimension)` 实现,便于单测。

---

## Decision 6: RAGAS 内部 embedding 与项目 EmbeddingFactory 复用

**Decision**:本 feature **不**让 RAGAS 用它内部默认的 OpenAI ada-002 embedding;在 `RagasEvaluator.__init__()` 中通过包装层(同 Decision 2)把项目 `EmbeddingFactory` 实例注入到所有 RAGAS metrics(对每个 metric 设 `metric.embeddings = LangchainEmbeddingsWrapper(project_embedding)`)。

**Rationale**:
- FR-017 的强约束:**评估流程的所有 embedding 环节用同一配置**;若 RAGAS 用 ada-002 但 backfill_chunk_ids 用 BGE,FR-017 直接被破坏
- ada-002 与项目 production embedding 不一致 → context_precision / context_recall 反映的是 ada-002 在该语料的相似度尺度,不是项目真实查询体验
- 默认 OpenAI embedding 还会要求额外 API key,与"复用项目配置"的目标背离

**Alternatives considered**:
- ❌ 让 RAGAS 用默认 ada-002 — 违反 FR-017,且要求额外 API key
- ❌ 仅在 backfill 流程使用项目 EmbeddingFactory,RAGAS 内部仍走默认 — 表面满足"接入"假象,实际 spec § FR-017 的"all evaluation embedding sites must use the same config" 不达标
- ❌ 让 RAGAS 用本地 sentence-transformers — 与项目 production embedding 不一致,同样违反 FR-017

**实施提示**:`_build_ragas_embedding(settings)` 把项目 embedding 包装成 `langchain.embeddings.base.Embeddings` 子类,RAGAS metrics 在 `__init__` 时全部用同一实例。包装层在 ragas_evaluator.py 内部即可,不抽到 base 层(同 Decision 4 原则)。

---

## Decision 7: settings.yaml `evaluation` 段的校验时机与 schema 演进

**Decision**:
- `EvaluationSettings` 在 `src/core/settings.py::load_settings()` 启动期完成校验(沿用项目现有"快速失败"模式,宪法 § III)
- 校验项:
  - `acceptance_thresholds.<metric>` 取值必须 ∈ [0, 1](浮点)
  - `judge_llm.provider` 必须 ∈ LLMFactory 注册的 provider 列表
  - `embedding.provider` 必须 ∈ EmbeddingFactory 注册的 provider 列表
  - `by_tag_dimensions` 必须 ⊆ `{"content_type", "difficulty"}`(MVP 白名单)
  - `report_archive_dir` 父目录必须可写(若不可写直接抛 ValueError 而非默默 fallback)
- schema 演进:settings.yaml `evaluation` 段加 `_schema_version: 1` 字段,未来扩展时通过该字段 gate 兼容性

**Rationale**:
- 启动期校验符合宪法 § III 快速失败原则;运行时再发现 `acceptance_thresholds.faithfulness=2.0` 会浪费一整次评估
- 阈值取值范围明确(指标都是 0~1),非法值用户无意义
- by_tag_dimensions 白名单避免用户传 `tags.unknown_dim`(项目无法切片)
- `_schema_version` 是廉价的 forward-compat 钩子,未来若 acceptance_thresholds 改为 `{value, severity}` 结构,旧配置可识别后报错或迁移

**Alternatives considered**:
- ❌ 运行时(`EvalRunner.run()` 入口)再校验 — 违反 § III,延迟暴露问题
- ❌ 不做 schema_version,未来直接换字段 — 老配置静默失败或行为漂移
- ❌ 把 `judge_llm.provider` 校验交给 LLMFactory 创建时再抛 — Judge 是 RAGAS 后端独有的,custom-only 评估时不会触发 Judge 创建,问题被掩盖

**实施提示**:校验逻辑放在 `src/core/settings.py::_validate_evaluation_settings(settings)` 子函数,由 `load_settings()` 调用;新增 `tests/unit/test_evaluation_settings.py` 覆盖每条非法路径(共约 6 个 negative test cases)。

---

## Summary

| # | Decision | 锁定输出 |
|---|---|---|
| 1 | RAGAS 0.1.x 单一版本固定 | `pyproject.toml` 精确版本号 |
| 2 | Judge / embedding 经 LangChain 轻包装层接入 RAGAS | `_build_ragas_judge()` / `_build_ragas_embedding()` |
| 3 | 报告归档 `logs/evaluation_reports/` + 基线 `logs/baselines.json` | 文件系统 JSON,无数据库 |
| 4 | 3 个新文件直接放 `src/observability/evaluation/`,不新建 component 层 | 不动宪法"组件类型新增"流程 |
| 5 | by-tag 仅 `content_type` + `difficulty`,< 5 样本跳过且显式标注 | `_aggregate_by_tag()` helper |
| 6 | RAGAS 强制用项目 EmbeddingFactory 注入(不许用默认 ada-002) | `_build_ragas_embedding()` |
| 7 | settings 校验在 `load_settings()` 启动期 + `_schema_version` 演进钩子 | `_validate_evaluation_settings()` |

所有决策 0 个 NEEDS CLARIFICATION,可进 Phase 1。
