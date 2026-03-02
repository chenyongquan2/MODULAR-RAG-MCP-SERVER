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
python scripts/sync_all_skills.py
```

This syncs DEV_SPEC.md to all three skill directories (.claude, .cline, .github).

3. Read the schedule file:
- Read `.github/skills/auto-coder/specs/06-schedule.md` (or `.claude/skills/auto-coder/specs/06-schedule.md`)

**Task markers:**

| Marker | Status |
|--------|--------|
| `[ ]` / `⬜` | Not started |
| `[~]` / `🔶` / `(进行中)` | In progress |
| `[x]` / `✅` / `(已完成)` | Completed |

**✅ CHECKPOINT - 必须完成：**
- [ ] Venv 已激活（确认 python 路径指向 `.venv`）
- [ ] Spec 同步成功（sync_all_skills.py 运行无错误，显示 "SUCCESS"）
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

**📚 Understanding File Relationships**

本项目使用双文件系统管理任务进度：

1. **DEV_SPEC.md** (Source of Truth)
   - 📍 位置: 项目根目录
   - ✏️ 手动维护，包含完整项目规范 + 进度表
   - 🎯 这是唯一需要手动编辑的文件

2. **specs/06-schedule.md** (Auto-Generated)
   - 📍 位置: `.github/skills/auto-coder/specs/` (以及 `.claude/` 和 `.cline/`)
   - 🤖 由 `sync_all_skills.py` 从 DEV_SPEC.md 自动生成
   - 🚨 **绝对禁止手动编辑**此文件，每次 sync 会被覆盖

**正确工作流 (Correct Flow):**
```
DEV_SPEC.md (手动编辑)
    ↓
sync_all_skills.py --force (自动同步到三个目录)
    ↓
specs/06-schedule.md (自动更新 .github/.claude/.cline/)
    ↓
verify_sync.py (验证一致性)
```

**❌ 错误工作流 (Incorrect Flow):**
```
只编辑 specs/06-schedule.md  ← 禁止！
    ↓
下次运行 sync_all_skills.py
    ↓
你的修改被 DEV_SPEC.md 覆盖 (数据丢失!)
```

---

**🚨 AI AGENT 强制自查清单（步骤 5 执行前必读）**

在开始步骤 5 之前，AI 必须逐项确认以下检查清单，**所有项目必须为 NO 或 YES（按要求）**：

<details>
<summary><b>🔍 点击展开完整检查清单</b></summary>

**🚫 禁止行为检查（必须全部为 NO）：**

- [ ] 我是否**手动编辑了任何 `specs/06-schedule.md` 文件**？
      ```bash
      # 检查这些路径是否被你手动编辑：
      .github/skills/auto-coder/specs/06-schedule.md
      .claude/skills/auto-coder/specs/06-schedule.md
      .cline/skills/auto-coder/specs/06-schedule.md
      ```
      → 如果 **YES**，这是**严重错误**！
      → 立即 STOP，执行以下修复：
      ```bash
      # 1. 丢弃手动修改
      git restore .github/.claude/.cline/skills/auto-coder/specs/06-schedule.md

      # 2. 正确更新 DEV_SPEC.md（源文件）
      # 3. 重新运行 sync_all_skills.py
      ```

- [ ] 我是否**使用 `cp` / `copy` 命令手动复制了 schedule 文件**？
      → 如果 **YES**，这违反了自动同步原则！
      → 立即 STOP，丢弃手动复制，使用 `sync_all_skills.py`

- [ ] 我是否**跳过了 `sync_all_skills.py` 直接读取了 schedule**？
      → 如果 **YES**，数据可能是过期的！
      → 立即 STOP，先运行 `sync_all_skills.py`

**✅ 必需行为检查（必须全部为 YES）：**

- [ ] 我是否**已更新 DEV_SPEC.md 中的任务状态**？
      → 检查任务行是否已标记为 `[x]` 并填写完成日期
      → 如果 **NO**，立即 STOP，先更新 DEV_SPEC.md

- [ ] 我是否**已运行 `sync_all_skills.py`**？
      → 检查是否看到输出：
      ```
      OK .github/skills/auto-coder - synced 7 chapters
      OK .claude/skills/auto-coder - synced 7 chapters
      OK .cline/skills/auto-coder - synced 7 chapters
      ```
      → 如果 **NO**，立即 STOP，运行脚本

- [ ] 我是否**已运行 `verify_sync.py` 且看到 ✅**？
      → 检查是否看到输出：`✅ Sync verification passed`
      → 如果 **NO** 或看到 `❌`，立即 STOP，修复问题

**⚠️ 所有检查通过后，才能继续到步骤 5.1（更新 DEV_SPEC）**

</details>

---

**🚨 CRITICAL: 以下步骤 5.1-5.4 必须按顺序完成，不可跳过**

**执行步骤:**

**5.1. ⚠️ FIRST: Update `DEV_SPEC.md` (source of truth)**

   - Locate task in progress table (e.g., "#### 阶段 B：Libs 可插拔层")
   - Find the task row by ID (e.g., B6, B7.1)
   - Change status marker: `[ ]` → `[x]`
   - Fill completion date: `2026-02-24` (use current date)

   **WHY this step is critical:**
   - DEV_SPEC.md is the authoritative source
   - sync_all_skills.py reads FROM this file TO generate schedule
   - If you skip this, schedule will not be updated correctly

   **Example:**
   ```diff
   - | B6 | Evaluator 抽象接口与工厂 | [ ] | - |  |
   + | B6 | Evaluator 抽象接口与工厂 | [x] | 2026-02-24 |  |
   ```

**5.2. 🔄 Run sync to auto-update schedule file**

   ```bash
   python scripts/sync_all_skills.py --force
   ```

   **What this does:**
   - Reads DEV_SPEC.md as source
   - Regenerates ALL spec files in `specs/` directory for ALL three locations:
     - `.github/skills/auto-coder/specs/`
     - `.claude/skills/auto-coder/specs/`
     - `.cline/skills/auto-coder/specs/`
   - Overwrites `06-schedule.md` with updated progress from DEV_SPEC

   **Expected output:**
   ```
   Syncing DEV_SPEC.md to all skill directories...
   OK .github/skills/auto-coder - synced 7 chapters
   OK .claude/skills/auto-coder - synced 7 chapters
   OK .cline/skills/auto-coder - synced 7 chapters

   SUCCESS: All 3 location(s) synced successfully
   ```

   **🚨 If you see different output:**
   - Check for error messages
   - Verify DEV_SPEC.md format is correct
   - STOP and investigate before continuing

**5.3. ✅ VERIFY: Run automated consistency check**

   ```bash
   python .github/skills/auto-coder/scripts/verify_sync.py
   ```

   **What this does:**
   - Parses task status from DEV_SPEC.md
   - Parses task status from specs/06-schedule.md (in .github directory)
   - Compares every task status marker (`[ ]`, `[~]`, `[x]`)
   - Exits with code 0 if match, code 1 if mismatch

   **Expected output:**
   ```
   ✅ Sync verification passed - DEV_SPEC.md and schedule are consistent
   ```

   **If verification FAILS:**
   ```
   ❌ SYNC VERIFICATION FAILED
   Mismatches found:
   B6: DEV_SPEC=[x] vs schedule=[ ]
   ```

   **🚨 CRITICAL: If script exits with error (code 1):**
   - ❌ **STOP IMMEDIATELY** - Do NOT proceed to step 5.4
   - Check which file you forgot to update
   - Most common causes:
     1. Forgot to update DEV_SPEC.md
     2. Forgot to run sync_all_skills.py
     3. Manually edited schedule file (禁止行为！)
   - Fix the issue and re-run steps 5.1-5.3
   - Only proceed when verify_sync.py shows ✅

**🔍 VALIDATION CHECKLIST**

Before proceeding to step 5.4, verify ALL checkboxes:
- [ ] DEV_SPEC.md shows task as `[x]` with completion date
- [ ] `sync_all_skills.py --force` ran successfully (saw "SUCCESS" for all 3 locations)
- [ ] `verify_sync.py` reports "✅ Sync verification passed"
- [ ] **我没有手动编辑任何 specs/ 目录下的文件**

⚠️ If ANY checkbox is unchecked, STOP and fix it NOW.

---

**5.4. 🚨 MANDATORY: 使用 ask_followup_question 工具暂停并询问用户**

**✅ CHECKPOINT - 必须执行以下操作：**

**第一步：发送桌面通知提醒用户**

在调用 `ask_followup_question` 之前，先发送桌面通知提醒用户有任务需要确认：

```python
notify(
    title="OpenCode 任务完成",
    message="任务 [任务ID] 已完成，需要您的确认",
    priority="High"
)
```

**第二步：使用 ask_followup_question 工具暂停并询问用户**

使用 `ask_followup_question` 工具，格式如下：

```python
ask_followup_question(
    question="""
✅ [任务ID] 任务名称 — 已完成

📊 执行摘要：
   - 创建/修改文件：[列出所有文件]
   - 测试结果：X/X passed (Y skipped)

📝 建议提交信息（严格遵循Conventional Commits规范）：
   格式：<type>(<scope>): [<TaskID>] <description>
   
   type:        feat
   scope:       {auto_detected_scope}
   TaskID:      [任务ID]
   description: {brief_english_description}
   
   完整示例：feat({scope}): [任务ID] {description}
   
   ⚠️ 格式要求（见下方5.1节）：
   - TaskID必须用方括号 [B7.2]
   - 描述用英文，小写开头，祈使句
   - scope根据代码路径自动确定

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
  git commit -m "<type>(<scope>): [<TaskID>] <description>"
  ```
  然后使用 `attempt_completion` 展示结果

- **"skip"**:
  直接使用 `attempt_completion` 展示结果（不提交）

- **"next"**:
  先执行 commit，然后循环回到步骤 1 开始下一个任务

---

### 5.5 Common Mistakes & Corrections (AI 必读)

<details>
<summary><b>❌ 常见错误案例库 - 点击展开学习</b></summary>

#### 案例 1：手动编辑 schedule 文件（严重错误！）

**错误操作记录：**
```bash
# AI 错误地做了这些操作：
1. Edit .github/skills/auto-coder/specs/06-schedule.md  # ❌ 禁止！
2. Edit .claude/skills/auto-coder/specs/06-schedule.md  # ❌ 禁止！
3. git add .github/.claude/skills/auto-coder/specs/06-schedule.md
4. git commit -m "docs(progress): update B7.5"
```

**为什么这是错误的：**
- 违反了"DEV_SPEC.md 是唯一真相源"原则
- specs/06-schedule.md 是自动生成文件，不应手动编辑
- 下次运行 sync_all_skills.py 时，手动修改会被覆盖
- verify_sync.py 会检测到不一致并报错

**正确做法：**
```bash
# 1. 只编辑源文件（唯一正确的编辑点）
Edit DEV_SPEC.md
# 修改任务行：| B7.5 | ... | [ ] | - | → | B7.5 | ... | [x] | 2026-02-24 |

# 2. 运行同步脚本（自动更新三个目录）
python scripts/sync_all_skills.py --force
# 看到：SUCCESS: All 3 location(s) synced successfully

# 3. 验证一致性
python .github/skills/auto-coder/scripts/verify_sync.py
# 必须看到：✅ Sync verification passed

# 4. 提交时包含源文件和所有三个目录
git add DEV_SPEC.md .github/.claude/.cline/
git commit -m "docs(progress): update B7.5 completion status"
```

---

#### 案例 2：使用 `cp` 命令手动复制 schedule 文件（错误！）

**错误操作记录：**
```bash
# AI 错误地做了：
cp .github/skills/auto-coder/specs/06-schedule.md .claude/skills/auto-coder/specs/
cp .github/skills/auto-coder/specs/06-schedule.md .cline/skills/auto-coder/specs/
```

**为什么这是错误的：**
- 绕过了自动同步机制
- 可能导致三个目录内容不一致（如果源文件有差异）
- 无法通过 .spec_hash 追踪同步状态

**正确做法：**
```bash
# 使用自动同步脚本，而不是手动复制
python scripts/sync_all_skills.py --force
```

---

#### 案例 3：跳过 verify_sync.py 验证（高风险！）

**错误操作记录：**
```bash
# AI 做了这些步骤：
1. Edit DEV_SPEC.md  # ✅ 正确
2. Run sync_all_skills.py  # ✅ 正确
3. ❌ 跳过 verify_sync.py
4. 直接 ask_followup_question  # ❌ 不安全
```

**为什么这是错误的：**
- sync_all_skills.py 可能运行失败但没有被发现
- 手动编辑可能遗漏某些文件
- 没有最后一道安全检查

**正确做法：**
```bash
# 总是运行验证脚本，确保数据一致性
python .github/skills/auto-coder/scripts/verify_sync.py

# 只有看到 ✅ 才能继续
# 如果看到 ❌，必须先修复问题
```

---

#### 案例 4：verify_sync.py 报错后仍继续（严重违规！）

**错误操作记录：**
```bash
# 运行验证
python .github/skills/auto-coder/scripts/verify_sync.py
# 输出：❌ SYNC VERIFICATION FAILED
# B7.5: DEV_SPEC=[x] vs schedule=[ ]

# AI 错误地忽略错误，继续执行：
ask_followup_question(...)  # ❌ 禁止！必须先修复
```

**为什么这是严重违规：**
- 进度表不一致，会导致状态混乱
- 可能重复执行已完成的任务
- 违反了 CHECKPOINT 机制

**正确做法：**
```bash
# 看到 ❌ 立即 STOP

# 分析错误原因：
# "B7.5: DEV_SPEC=[x] vs schedule=[ ]"
# → DEV_SPEC 中是 [x]，但 schedule 中是 [ ]
# → 说明 sync_all_skills.py 没有正确运行

# 修复步骤：
1. 检查 DEV_SPEC.md 格式是否正确
2. 重新运行 sync_all_skills.py --force
3. 再次运行 verify_sync.py
4. 只有看到 ✅ 才能继续
```

---

#### 案例 5：在步骤 5 未运行任何同步脚本（完全违规！）

**错误操作记录：**
```bash
# AI 直接跳到 ask_followup_question，没有运行任何同步步骤
ask_followup_question(...)  # ❌ 严重违规！
```

**为什么这是完全违规：**
- 跳过了整个进度更新流程
- DEV_SPEC.md 和 schedule 完全不同步
- 无法追踪任务完成状态

**正确做法：**
```bash
# 必须按顺序执行步骤 5.1-5.4，不可跳过：
# 5.1: Edit DEV_SPEC.md
# 5.2: Run sync_all_skills.py --force
# 5.3: Run verify_sync.py (必须看到 ✅)
# 5.4: ask_followup_question
```

</details>

---

### 5.1 Commit Message Convention

**统一格式规范（Conventional Commits）：**

```
<type>(<scope>): [<TaskID>] <description>
```

#### Type 类型定义

| Type | 使用场景 | 示例 |
|------|---------|------|
| `feat` | 新功能实现 | `feat(llm): [B7.2] implement Ollama LLM provider` |
| `fix` | Bug修复 | `fix(reranker): [B5.1] handle empty query gracefully` |
| `docs` | 文档更新 | `docs(readme): [A1] update installation guide` |
| `test` | 测试相关（新增/修改测试） | `test(embedding): [B3.2] add batch processing tests` |
| `refactor` | 代码重构（无功能变化） | `refactor(splitter): [B2] simplify semantic chunking logic` |
| `perf` | 性能优化 | `perf(vector_store): [B4.1] optimize batch upsert` |
| `chore` | 构建/工具/依赖变更 | `chore(deps): [INFRA] upgrade pytest to 8.0` |

#### Scope 自动映射规则

根据任务涉及的代码路径自动确定scope：

| 代码路径 | Scope | 典型TaskID |
|---------|-------|-----------|
| `src/libs/llm/*` | `llm` | B7.x |
| `src/libs/embedding/*` | `embedding` | B3.x |
| `src/libs/reranker/*` | `reranker` | B5.x |
| `src/libs/vector_store/*` | `vector_store` | B4.x |
| `src/libs/splitter/*` | `splitter` | B2.x |
| `src/libs/evaluator/*` | `evaluator` | B6.x |
| `src/libs/loader/*` | `loader` | - |
| `src/ingestion/*` | `ingestion` | - |
| `src/core/query_engine/*` | `query` | - |
| `src/core/response/*` | `response` | - |
| `src/core/trace/*` | `trace` | - |
| `src/mcp_server/*` | `mcp` | - |
| `src/observability/*` | `observability` | - |
| `.github/skills/*`, `.claude/skills/*`, `.cline/skills/*` | `skills` | - |
| 多模块 | 使用主要模块或 `core` | - |

#### 强制规则

| 规则 | 正确 ✅ | 错误 ❌ |
|------|---------|---------|
| TaskID格式 | `[B7.2]` | `(B7.2)`, `B7.2`, `B7.2:` |
| TaskID位置 | `feat(llm): [B7.2] implement` | `feat(llm): implement (B7.2)`, `feat(B7.2): implement` |
| 描述语言 | 英文 | 中文 |
| 描述大小写 | 小写开头 `implement` | 大写开头 `Implement` |
| 描述语态 | 祈使句动词原形 `add`, `fix`, `update` | 过去式 `added`, 现在分词 `adding` |
| Scope必填 | `feat(llm): [B7.2]` | `feat: [B7.2]` |
| 格式顺序 | `type(scope): [TaskID] desc` | `type: [TaskID](scope) desc` |

#### 完整示例

```bash
# 功能实现
feat(llm): [B7.2] implement Ollama LLM provider
feat(embedding): [B3.1] add Azure OpenAI embedding support

# Bug修复
fix(reranker): [B5.1] handle empty query list gracefully
fix(vector_store): [B4.2] correct batch size calculation

# 文档更新
docs(readme): [A1] update installation instructions
docs(api): [B7] add LLM provider usage examples

# 测试
test(evaluator): [B6.1] add custom metric validation tests
test(integration): [E2E] add end-to-end RAG pipeline test

# 重构
refactor(splitter): [B2.3] extract chunk overlap logic
refactor(query): [C1] simplify fusion algorithm

# 性能优化
perf(embedding): [B3.2] optimize batch encoding with async
perf(vector_store): [B4.1] add connection pooling

# 工具/构建
chore(deps): [INFRA] upgrade pytest to 8.0
chore(ci): [INFRA] add pre-commit hooks
```

#### 自动检测Scope的逻辑

在步骤5询问用户时，应自动检测修改的文件路径并推荐scope：

```python
# 伪代码示例
modified_files = ["src/libs/llm/ollama_llm.py", "tests/unit/test_ollama_llm.py"]
scope = detect_scope_from_paths(modified_files)  # 返回 "llm"

# 如果涉及多个模块
modified_files = ["src/libs/llm/base.py", "src/libs/embedding/base.py"]
scope = detect_scope_from_paths(modified_files)  # 返回主要模块或 "core"
```

**⚠️ 绝对禁止的行为：**
- ❌ 不得跳过 `ask_followup_question` 直接使用 `attempt_completion`
- ❌ 不得自动决定是否执行 git commit
- ❌ 不得在未询问用户的情况下结束任务

---

### 5.2 Example: Updating Task B6

**Before (DEV_SPEC.md, line ~1978):**
```markdown
| B6 | Evaluator 抽象接口与工厂 | [ ] | - |  |
```

**After editing (DEV_SPEC.md, line ~1978):**
```markdown
| B6 | Evaluator 抽象接口与工厂 | [x] | 2026-02-22 |  |
```

**Commands to run:**
```bash
# Step 2: Sync
python .github/skills/auto-coder/scripts/sync_spec.py --force
# Output: synced 7 chapters

# Step 3: Verify
python .github/skills/auto-coder/scripts/verify_sync.py
# Output: ✅ Sync verification passed - DEV_SPEC.md and schedule are consistent
```

**Result in schedule file (auto-generated):**
```markdown
| B6 | Evaluator 抽象接口与工厂 | [x] | 2026-02-22 |  |
```

---

## Guardrails & Prohibited Actions

### ✅ 必须遵守的规则

- One task per cycle, atomic commits
- **DEV_SPEC.md is the single source of truth** — never edit schedule files directly
- 3-round test fix limit
- Match existing codebase style
- **MUST activate `.venv` before ANY `python`/`pytest` command** — no exceptions. If unsure whether venv is active, run `.\.venv\Scripts\Activate.ps1` again (idempotent)
- **MUST run sync_all_skills.py after updating DEV_SPEC.md** — do not skip or replace with manual copy
- **MUST run verify_sync.py before ask_followup_question** — exit(1) means STOP

### ❌ 绝对禁止的行为（Tier 1: 严重违规）

这些行为会导致数据丢失或进度混乱，**绝对禁止**：

| # | 禁止行为 | 后果 | 检测方式 |
|---|---------|------|----------|
| 1 | **手动编辑 specs/06-schedule.md**（任何目录） | 下次 sync 被覆盖 | verify_sync.py exit(1) |
| 2 | **使用 `cp` / `copy` 手动复制 schedule 文件** | 绕过同步机制，数据不一致 | .spec_hash 不匹配 |
| 3 | **verify_sync.py 返回 exit(1) 后仍继续** | 进度表混乱，重复任务 | 脚本强制 exit(1) |
| 4 | **跳过 verify_sync.py 验证** | 无法发现同步失败 | 无自动检测 |
| 5 | **只更新部分目录的 schedule 文件** | 三个目录不一致 | verify_sync.py exit(1) |

**🚨 如果发现自己做了上述任何行为，必须立即 STOP 并执行修复流程（见案例库）**

---

### ❌ 绝对禁止的行为（Tier 2: 流程违规）

这些行为违反流程规范，影响代码质量：

| # | 禁止行为 | 后果 | 修复方法 |
|---|---------|------|----------|
| 6 | 跳过 venv 激活运行 Python | 污染系统环境 | 运行前检查 `which python` |
| 7 | 跳过 sync_all_skills.py 读取 schedule | 读取过期数据 | 先运行 sync 再读取 |
| 8 | 未完成自我审查就运行测试 | 浪费测试轮次 | 先完成 CHECKPOINT |
| 9 | 测试未通过就标记任务完成 | 代码有 Bug | verify_sync 会发现 |
| 10 | 不使用 ask_followup_question 直接结束 | 用户失去控制权 | 必须使用 |
| 11 | 自动执行 git commit 不询问用户 | 用户无法审查 | 必须询问 |
| 12 | 跳过任何 CHECKPOINT | 流程不完整 | 逐项检查 |

---

### 🔍 AI Agent 执行前自检表（强制）

在执行每个步骤前，AI 必须在脑海中快速检查：

**步骤 1（Sync Spec）前：**
- [ ] 我是否已激活 venv？（检查 python 路径）
- [ ] 我是否准备好运行 sync_all_skills.py？

**步骤 5.2（Run sync）前：**
- [ ] 我是否已更新 DEV_SPEC.md？
- [ ] 我是否**没有**手动编辑任何 schedule 文件？
- [ ] 我是否准备好运行 sync_all_skills.py（不是手动复制）？

**步骤 5.3（Verify）前：**
- [ ] 我是否已运行 sync_all_skills.py？
- [ ] 我是否准备好检查 verify_sync.py 的返回码？

**步骤 5.4（ask_followup_question）前：**
- [ ] verify_sync.py 是否返回了 ✅？
- [ ] 如果是 ❌，我是否已 STOP 并修复？

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
