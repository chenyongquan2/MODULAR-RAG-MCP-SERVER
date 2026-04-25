# Modular RAG MCP Server Constitution

## Core Principles

### 一、Provider 无关性
所有可替换组件(LLM、Embedding、Splitter、向量库、Reranker、Evaluator)**必须**通过抽象基类访问;业务逻辑**禁止**引用具体 provider 名,**禁止**直接 import provider 实现模块。

**立法理由**:本项目的核心价值是"无需改代码即可换 provider"。一旦业务逻辑硬编码 `if provider == "openai"` 或 `from openai_llm import ...`,这条价值就破产 —— 后续每次换 provider 都要改业务代码,违背项目存在的理由。

**执行约束**:
- 所有组件在 `src/libs/<component>/base_<component>.py` 定义抽象接口
- Provider 实例化通过 `<component>_factory.py` 中的工厂创建
- 业务代码(`src/core/`、`src/mcp/`、`scripts/`)只 import base 类型,不 import 具体 provider 实现
- Code review 检查项:在业务代码中 grep `from .*_llm import` 应为零(允许出现在 factory 内部)

### 二、配置驱动
所有运行时行为差异(选哪个 provider、哪个模型、哪些参数)**必须**通过 `config/settings.yaml` 与环境变量控制;代码**禁止**包含基于环境名的分支(如 `if env == "prod"`)。

**立法理由**:配置漂移是多环境系统最大的隐性 bug 源。把行为决策放在代码里 → 测试环境跑通的代码到生产可能行为不同;放在配置里 → 行为差异可见、可 review、可回滚。

**执行约束**:
- 所有可调参数有对应 `src/core/settings.py` 的 dataclass 字段
- Provider 切换只改 `settings.yaml` 不改代码
- 允许从 env 读取**值**(如 API key);禁止据 env 改变**逻辑结构**

### 三、快速失败校验
配置校验**必须**在进程启动期由 `src/core/settings.py::load_settings()` 完成;非法配置**必须**立即抛出 `ValueError`,**禁止**静默回退到默认值。

**立法理由**:启动时 1 秒内发现错配 vs 运行时第 1000 个请求才发现 —— 后者会污染数据、误导 metrics、让根因排查从分钟变小时。

**执行约束**:
- `load_settings()` 检查所有必需字段、API key 存在性、provider 名合法性
- 校验失败抛 `ValueError`,禁止 try/except 吞掉后回退 default
- `tests/unit/test_settings.py` 验证非法配置被拒绝

### 四、追踪显式化
TraceContext **必须**作为显式函数参数传递,**禁止**通过 thread-local、`contextvars` 或全局状态隐式存放。

**立法理由**:显式 trace 让数据流可读、可测试、可在异步/多线程环境正确工作。隐式 trace 在 async/await 切换 context 时静默丢失,且排查问题需要追全栈装饰器。

**执行约束**:
- 所有 RAG pipeline 函数(retriever、reranker、response builder)签名包含 `trace_ctx: TraceContext` 参数
- 不使用 `contextvars.ContextVar` 或 `threading.local` 存放 trace 状态
- Code review 检查项:新增 pipeline 函数必须显式传 trace

### 五、结构化日志(NON-NEGOTIABLE)
所有日志**必须**通过 `observability.logger.get_logger()` 输出;日志**必须**写入 stderr(stdout 为 MCP 协议保留通道);`src/` 目录下**禁止**任何 `print()` 调用。

**立法理由**:MCP stdio transport 用 stdout 传输 JSON-RPC,任何混入 stdout 的 print 都会**直接破坏协议**(客户端解析失败 → 整个 MCP server 不可用)。这不是质量偏好而是正确性约束 —— 因此标记为 NON-NEGOTIABLE,不允许 plan.md 在 Complexity Tracking 中登记例外。

**执行约束**:
- `src/` 下禁止 `print(...)`(CLI 工具的人类可读输出应写在 `scripts/`)
- Logger 通过 `from observability.logger import get_logger; logger = get_logger(__name__)` 获取
- pytest 通过 `caplog` 验证关键事件被记录

### 六、类型安全
`src/` 下所有 public 函数(非 `_` 开头)**必须**有完整的参数与返回值类型注解;跨模块共享的领域类型**必须**集中定义在 `src/core/types.py`。

**立法理由**:Python 是动态类型语言,类型注解是把 bug 从运行时拉到 IDE/lint 阶段的唯一手段。共享类型集中定义避免"3 个文件 3 个版本的 SearchResult"。

**执行约束**:
- 所有 public 函数有完整类型注解
- 跨模块共享对象(Document、Chunk、SearchResult、TraceContext 等)定义在 `src/core/types.py`
- 后续可加 `mypy --strict` 到 CI(本宪法不强制阈值)

### 七、测试支撑变更(NON-NEGOTIABLE)
每个实现任务**必须**配套 `tests/unit/` 下的单元测试;任何修改 `src/` 的 commit 之前,既有测试套件**必须**全部通过。

**立法理由**:没测试的代码 = 没人能确认它正确、没人敢重构、回归不会被发现。NON-NEGOTIABLE 意味着这条不允许 plan.md 在 Complexity Tracking 里登记例外。

**执行约束**:
- `speckit-tasks` 生成的 tasks.md 必须为每个实现任务配套测试任务
- 提交前运行 `pytest tests/unit -v`,失败禁止 commit
- 集成/E2E 测试可分阶段补,但**单元测试不可缺位**

---

## 开发纪律(NON-NEGOTIABLE)

本节定义 SDD 工作流契约。这些规则**不可**被任何单个 feature 的 plan 覆盖。

### 八、Spec 先行
任何 feature 工作或非平凡变更**必须**先在 `.specify/features/<name>/` 下有 `spec.md`,然后才能新增或修改 `src/` 的代码。

**立法理由**:Spec 是 AI ↔ 人类的"输入合同"。没 spec 直接写代码 = AI 自由发挥 → 范围漂移、需求遗漏、决策不可追溯。

**例外清单**(以下场景不要求走 SDD):
- 单文件 typo / 注释修改
- 依赖版本升级
- `scripts/dev/` 下的一次性探索脚本
- 根因明确的 bug 修复(< 10 行)
- 文档变更(`docs/`、`DEV_SPEC.md`、`CLAUDE.md`)
- 为已有代码补充测试(纯 `tests/` 目录新增,不改 `src/`)

### 九、Plan 先于 Tasks
`tasks.md` **必须**由同一 feature 目录下既有的 `plan.md` 推导生成;**禁止**手工撰写脱钩 plan 的 tasks。

**立法理由**:没 plan 的 tasks 是战术噪音 —— 任务可能与架构选型矛盾、漏掉跨模块影响、无法做 Constitution Check。

**执行约束**:
- `speckit-tasks` skill 拒绝在缺失 plan.md 的目录生成 tasks
- Plan 中的 "Constitution Check" 区段必须显式列出对每条原则的合规性

### 十、可追溯性
任何修改 `src/` 的 commit,其 commit message **必须**引用对应任务 ID(如 `refs T-003` 或 `closes T-005`)。

**立法理由**:让 git 历史可反向追溯到 spec/plan/tasks。半年后排查"为什么这段代码这样写"时,从 commit → task → plan → spec → 用户故事的链路必须完整。

**执行约束**:
- Code review 检查 commit message 是否引用 task ID
- 例外:Spec 先行规则列出的 6 类例外场景不强制

---

## 附加约束

### 架构稳定性
新增组件类型(如未来引入 "Cache Layer" 这一新组件层级)的添加流程:
1. 写 `.specify/features/<name>/spec.md` 论证必要性
2. plan.md 中明确证明现有抽象层无法满足
3. 新组件层级必须遵循 base + factory 模式(见原则一)

框架级依赖更换(如 ChromaDB → 另一向量库)需要 MAJOR 版本号修订宪法。

### 文档边界
- **CLAUDE.md**:AI 工作指引 + 协作偏好(沟通语言、注释风格、code review 习惯)
- **constitution.md**:架构与流程的硬约束(本文件)
- **DEV_SPEC.md**:高层技术设计(过渡期文档,不用于 feature 任务追踪)
- **`.specify/features/<name>/`**:具体 feature 的 spec/plan/tasks
- 三者冲突时,以本宪法为准

---

## Governance

### 权威性
本宪法位于所有项目级文档之上;与 CLAUDE.md、DEV_SPEC.md、各 feature plan/tasks 冲突时以本宪法为准。

### 修宪流程
1. 修宪通过 `speckit-constitution` skill 执行,**禁止**直接 Edit 本文件
2. 若修宪由某 feature 触发,在该 feature 的 plan.md "Constitution Amendment Required" 区段说明
3. 修宪后必须同步更新 `.specify/templates/plan-template.md` 的 Constitution Check 区段
4. 修宪后必须 review 进行中的 feature plan 是否仍合规

### 版本号策略
- **MAJOR**:删除原则、反转原则、对现有 plan/tasks 造成不兼容变更
- **MINOR**:新增原则、对现有原则的实质性扩展
- **PATCH**:措辞澄清、补充示例、非语义性修订

### 合规性验证
- 每个 feature 的 plan.md "Constitution Check" 必须逐条评估合规性
- 偏离须在 plan.md 的 "Complexity Tracking" 区段登记理由
- **NON-NEGOTIABLE 条款除外**:违反则 feature 必须重设计,不允许例外登记
- 每 3-6 个月或大版本前跑一次 `speckit-constitution` 周期 review(即使不改内容)

### 运行期指引
日常 AI 工作指引参考 [CLAUDE.md](../../CLAUDE.md);本宪法只规定**不可妥协的架构与流程约束**。

---

**Version**: 1.0.0 | **Ratified**: 2026-04-25 | **Last Amended**: 2026-04-25
