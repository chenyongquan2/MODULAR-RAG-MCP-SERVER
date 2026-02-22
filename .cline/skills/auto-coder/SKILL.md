---
name: auto-coder
description: Autonomous spec-driven development agent. Reads DEV_SPEC.md, identifies next task, implements code, runs tests, and persists progress — all in one command with minimal user intervention. Use when user says "auto code", "自动开发", "自动写代码", "auto dev", "一键开发", "autopilot", or wants fully automated spec-to-code workflow. Replaces manual dev-workflow pipeline with autonomous execution.
---

# Auto Coder

Autonomous agent: one trigger completes **read spec → find task → code → test → persist progress**.

## Execution Mode

此 skill 采用 **半自动模式**：

- **🤖 自动执行**（无需用户干预）：步骤 1-4
  - Sync Spec → Find Task → Implement → Test & Fix
  
- **👤 交互确认**（必须等待用户）：步骤 5
  - 使用 `ask_followup_question` 暂停并询问用户选择：commit / skip / next
  
**设计原因：** Git commit 是不可逆操作，需用户明确同意，确保代码质量可控。

---

## Trigger

| User Says | Behavior |
|-----------|----------|
| "auto code" / "自动开发" | Next task, full cycle |
| "auto code B2" | Specific task |
| "auto code --no-commit" | Skip git commit |

---

## Pipeline with Checkpoints

```
Step 1 → [✓ CHECKPOINT] → Step 2 → [✓ CHECKPOINT] → Step 3 
  ↓
[✓ CHECKPOINT] → Step 4 → [✓ CHECKPOINT] → Step 5 → [✓ USER CONFIRMATION] → END
```

**每个 CHECKPOINT 都必须完成才能进入下一步。**

> **⚠️ CRITICAL: ALL Python commands MUST run inside the project venv.**
> Before executing ANY `python` or `pytest` command, activate the venv first:
> ```powershell
> .\.venv\Scripts\Activate.ps1
> ```
> Verify by checking `Get-Command python` points to `.venv\Scripts\python.exe`.
> **Never use system Python. Never skip this step.**

---

### 1. Sync Spec

**执行步骤：**

1. Activate venv first:
```powershell
.\.venv\Scripts\Activate.ps1
```

2. Run sync script:
```powershell
python .github/skills/auto-coder/scripts/sync_spec.py
```

3. Read the schedule file:
- Read `.github/skills/auto-coder/specs/06-schedule.md`

**Task markers:**

| Marker | Status |
|--------|--------|
| `[ ]` / `⬜` | Not started |
| `[~]` / `🔶` / `(进行中)` | In progress |
| `[x]` / `✅` / `(已完成)` | Completed |

**✅ CHECKPOINT - 必须完成：**
- [ ] Venv 已激活（确认 python 路径指向 `.venv`）
- [ ] Spec 同步成功（sync_spec.py 运行无错误）
- [ ] Schedule 文件已读取（知道总任务数和当前进度）

**⚠️ 未完成此 CHECKPOINT 不得进入步骤 2**

---

### 2. Find Task

**执行步骤：**

Priority: first `IN_PROGRESS`, then first `NOT_STARTED`. If user specified a task ID, use that directly.

Quick-check predecessor artifacts exist (file-level only). On mismatch, log warning and continue — only stop if the target task itself is blocked.

**✅ CHECKPOINT - 必须完成：**
- [ ] 已确定目标任务 ID 和名称
- [ ] 已检查前置依赖（至少文件级别）
- [ ] 明确知道要实现什么功能

**⚠️ 未完成此 CHECKPOINT 不得进入步骤 3**

---

### 3. Implement

**执行步骤：**

1. **Read relevant spec** from `.github/skills/auto-coder/specs/`:
   - Architecture: `05-architecture.md`
   - Tech details: `03-tech-stack.md`
   - Testing conventions: `04-testing.md`

2. **Extract** from spec: inputs/outputs, design principles (Pluggable? Config-driven? Factory?), file list, acceptance criteria.

3. **Plan** files to create/modify before writing any code.

4. **Code** — mandatory standards:
   - Type hints on all signatures
   - Google-style docstrings on public APIs
   - No hardcoded values (use config)
   - Single responsibility, short functions
   - Error handling for external integrations

5. **Write tests** alongside code:
   - `tests/unit/test_<module>.py` or `tests/integration/` per spec
   - Naming: `test_<func>_<scenario>_<expected>`
   - Mock external deps in unit tests

6. **Self-review** before running tests: all planned files exist, type hints present, no hardcoded values, tests import correctly.

**✅ CHECKPOINT - 必须完成：**
- [ ] 所有计划的文件都已创建/修改
- [ ] 代码包含完整类型提示和文档字符串
- [ ] 测试文件已编写（覆盖主要场景）
- [ ] 自我审查通过（无明显遗漏）

**⚠️ 未完成此 CHECKPOINT 不得进入步骤 4**

---

### 4. Test & Auto-Fix

**执行步骤：**

```
Round 0..2:
  Run pytest on relevant test file
  If pass → go to step 5
  If fail → analyze error, apply fix, re-run

Round 3 still failing → STOP, show failure report to user
```

**✅ CHECKPOINT - 必须满足以下之一：**
- [ ] 测试全部通过（进入步骤 5）
- [ ] 达到 3 轮修复上限仍失败（暂停并报告给用户）

**⚠️ 未完成此 CHECKPOINT 不得进入步骤 5**

---

### 5. Persist

**执行步骤：**

1. **Update `DEV_SPEC.md`** (global file):
   - Locate task in relevant chapter (e.g., "## 阶段 B" section)
   - Change marker: `[ ]` → `[x]`
   - Fill completion date if column exists

2. **Update schedule file**:
   - Open `.github/skills/auto-coder/specs/06-schedule.md`
   - Find task row in progress table
   - Update: 状态 `[ ]` → `[x]`, 完成日期 `2026-02-22` (or current date)
   - Update stage progress: 已完成任务数 +1, 重新计算百分比

3. **Re-sync for verification**: 
```powershell
python .github/skills/auto-coder/scripts/sync_spec.py --force
```

4. **🚨 MANDATORY: 使用 ask_followup_question 工具暂停并询问用户**

**✅ CHECKPOINT - 必须执行以下操作：**

使用 `ask_followup_question` 工具，格式如下：

```python
ask_followup_question(
    question="""
✅ [任务ID] 任务名称 — 已完成

📊 执行摘要：
   - 创建/修改文件：[列出所有文件]
   - 测试结果：X/X passed (Y skipped)
   - 建议提交信息：feat(模块): [任务ID] 简短描述

请选择下一步操作：
""",
    options=[
        "commit - 提交代码到 git",
        "skip - 跳过提交直接结束", 
        "next - 提交并继续下一个任务"
    ]
)
```

**根据用户选择执行：**

- **"commit"**: 
  ```powershell
  git add .
  git commit -m "feat(模块): [任务ID] 简短描述"
  ```
  然后使用 `attempt_completion` 展示结果

- **"skip"**: 
  直接使用 `attempt_completion` 展示结果（不提交）

- **"next"**: 
  先执行 commit，然后循环回到步骤 1 开始下一个任务

**⚠️ 绝对禁止的行为：**
- ❌ 不得跳过 `ask_followup_question` 直接使用 `attempt_completion`
- ❌ 不得自动决定是否执行 git commit
- ❌ 不得在未询问用户的情况下结束任务

---

## Guardrails & Prohibited Actions

### ✅ 必须遵守的规则

- One task per cycle, atomic commits
- Spec is single source of truth
- 3-round test fix limit
- Match existing codebase style
- **MUST activate `.venv` before ANY `python`/`pytest` command** — no exceptions. If unsure whether venv is active, run `.\.venv\Scripts\Activate.ps1` again (idempotent)

### ❌ 绝对禁止的行为

1. **跳过 venv 激活**就运行 Python 命令
2. **跳过 sync_spec.py** 就读取 schedule 文件
3. **未完成自我审查**就运行测试
4. **测试未通过**就标记任务完成
5. **在步骤 5 不使用 ask_followup_question** 而直接使用 `attempt_completion` 结束
6. **自动执行 git commit** 而不询问用户
7. **跳过任何 CHECKPOINT** 直接进入下一步

### ✅ 正确的任务结束方式

**唯一正确的流程：**

```
步骤 5 → 使用 ask_followup_question 询问用户
        ↓
    用户选择 commit/skip/next
        ↓
    执行相应操作（commit/不commit/commit+继续）
        ↓
    使用 attempt_completion 展示最终结果
```

---

## Directory Structure

```
auto-coder/
├── SKILL.md              ← this file
├── .spec_hash            ← auto-generated hash
├── scripts/
│   └── sync_spec.py      ← splits DEV_SPEC.md into chapters
└── specs/                ← auto-generated chapter files
    ├── 01-overview.md
    ├── 02-features.md
    ├── 03-tech-stack.md
    ├── 04-testing.md
    ├── 05-architecture.md
    ├── 06-schedule.md
    └── 07-future.md
```

All paths are self-contained. This skill has no external dependencies on other skills.
