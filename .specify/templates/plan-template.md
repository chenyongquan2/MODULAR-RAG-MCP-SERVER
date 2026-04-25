# Implementation Plan: [FEATURE]

**Branch**: `[###-feature-name]` | **Date**: [DATE] | **Spec**: [link]
**Input**: Feature specification from `/specs/[###-feature-name]/spec.md`

**Note**: This template is filled in by the `/speckit.plan` command. See `.specify/templates/plan-template.md` for the execution workflow.

## Summary

[Extract from feature spec: primary requirement + technical approach from research]

## Technical Context

<!--
  ACTION REQUIRED: Replace the content in this section with the technical details
  for the project. The structure here is presented in advisory capacity to guide
  the iteration process.
-->

**Language/Version**: [e.g., Python 3.11, Swift 5.9, Rust 1.75 or NEEDS CLARIFICATION]  
**Primary Dependencies**: [e.g., FastAPI, UIKit, LLVM or NEEDS CLARIFICATION]  
**Storage**: [if applicable, e.g., PostgreSQL, CoreData, files or N/A]  
**Testing**: [e.g., pytest, XCTest, cargo test or NEEDS CLARIFICATION]  
**Target Platform**: [e.g., Linux server, iOS 15+, WASM or NEEDS CLARIFICATION]
**Project Type**: [e.g., library/cli/web-service/mobile-app/compiler/desktop-app or NEEDS CLARIFICATION]  
**Performance Goals**: [domain-specific, e.g., 1000 req/s, 10k lines/sec, 60 fps or NEEDS CLARIFICATION]  
**Constraints**: [domain-specific, e.g., <200ms p95, <100MB memory, offline-capable or NEEDS CLARIFICATION]  
**Scale/Scope**: [domain-specific, e.g., 10k users, 1M LOC, 50 screens or NEEDS CLARIFICATION]

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

逐条标记 **PASS / VIOLATION / N/A** 并附一行说明。**NON-NEGOTIABLE** 条款不允许通过 Complexity Tracking 豁免 —— 违反则 feature 必须重设计。其他条款的偏离必须在 Complexity Tracking 区段登记理由。

### 架构原则

- [ ] **一、Provider 无关性** — 业务代码不 import 具体 provider;新组件经 base + factory 接入
- [ ] **二、配置驱动** — 新增可调参数有 `settings.yaml` 字段 + `src/core/settings.py` dataclass
- [ ] **三、快速失败校验** — 配置/输入校验在启动期或入口处完成,失败立即抛 `ValueError`
- [ ] **四、追踪显式化** — pipeline 函数签名包含 `trace_ctx: TraceContext`,无隐式 trace 状态
- [ ] **五、结构化日志(NON-NEGOTIABLE)** — `src/` 内零 `print()`,日志通过 `observability.logger`,输出到 stderr
- [ ] **六、类型安全** — 所有 public 函数完整类型注解;共享类型放 `src/core/types.py`
- [ ] **七、测试支撑变更(NON-NEGOTIABLE)** — 每个实现任务配套 unit test,提交前 `pytest tests/unit -v` 通过

### SDD 纪律

- [ ] **八、Spec 先行(NON-NEGOTIABLE)** — 本 feature 已有 `spec.md`,代码改动均围绕其展开
- [ ] **九、Plan 先于 Tasks(NON-NEGOTIABLE)** — `tasks.md` 将由本 plan 推导,不脱钩生成
- [ ] **十、可追溯性(NON-NEGOTIABLE)** — 实施期 commit message 引用 task ID(`refs T-XXX`)

> 完整原则定义见 [.specify/memory/constitution.md](../../.specify/memory/constitution.md)。

## Project Structure

### Documentation (this feature)

```text
specs/[###-feature]/
├── plan.md              # This file (/speckit.plan command output)
├── research.md          # Phase 0 output (/speckit.plan command)
├── data-model.md        # Phase 1 output (/speckit.plan command)
├── quickstart.md        # Phase 1 output (/speckit.plan command)
├── contracts/           # Phase 1 output (/speckit.plan command)
└── tasks.md             # Phase 2 output (/speckit.tasks command - NOT created by /speckit.plan)
```

### Source Code (repository root)
<!--
  ACTION REQUIRED: Replace the placeholder tree below with the concrete layout
  for this feature. Delete unused options and expand the chosen structure with
  real paths (e.g., apps/admin, packages/something). The delivered plan must
  not include Option labels.
-->

```text
# [REMOVE IF UNUSED] Option 1: Single project (DEFAULT)
src/
├── models/
├── services/
├── cli/
└── lib/

tests/
├── contract/
├── integration/
└── unit/

# [REMOVE IF UNUSED] Option 2: Web application (when "frontend" + "backend" detected)
backend/
├── src/
│   ├── models/
│   ├── services/
│   └── api/
└── tests/

frontend/
├── src/
│   ├── components/
│   ├── pages/
│   └── services/
└── tests/

# [REMOVE IF UNUSED] Option 3: Mobile + API (when "iOS/Android" detected)
api/
└── [same as backend above]

ios/ or android/
└── [platform-specific structure: feature modules, UI flows, platform tests]
```

**Structure Decision**: [Document the selected structure and reference the real
directories captured above]

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| [e.g., 4th project] | [current need] | [why 3 projects insufficient] |
| [e.g., Repository pattern] | [specific problem] | [why direct DB access insufficient] |
