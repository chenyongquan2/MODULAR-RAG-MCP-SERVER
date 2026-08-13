# Spec-Driven Development (SDD) 学习与使用指南

> # ⚠️ 已废弃(2026-08-12)
>
> **本文写的是 GitHub Spec-Kit,该工具已在 2026-08-12 从本项目退役。**
> 现行 SDD 流程是 **OpenSpec** —— 见 [CLAUDE.md § Mandatory SDD Workflow](../CLAUDE.md)
> 与 [openspec/config.yaml](../openspec/config.yaml)。
>
> 退役原因:每个 feature 产出 8–12 个文件、1150–2100 行规格文档,其中
> `research.md` / `data-model.md` / `checklists/` 写完后再没被引用过;且改方向
> 意味着重跑整条 `specify → plan → tasks` 链。OpenSpec 用 delta 规格
> (`ADDED`/`MODIFIED`/`REMOVED`)+ 无相位门解决这两点。
>
> **本文保留的价值**:§ 5「踩过的坑」与 § 2「核心概念」讲的是 SDD 方法论本身,
> 与具体工具无关,仍值得读。其余章节(命令、模板、SPECKIT 块管理)已失效。
>
> 历史资产位置:`specs/001-005/`、`.specify/`(含宪法 v1.0.0 原文)、
> `.specify/archived-skills/`(8 个停用的 `speckit-*` skill)。

> **文档性质**：本项目引入 GitHub Spec-Kit 的完整记录 + 日常使用手册（历史文档）。
> **面向读者**：想了解本项目 SDD 演进史、或学习 SDD 方法论的开发者。
> **关联文档**：[CLAUDE.md](../CLAUDE.md)、[DEV_SPEC.md](../DEV_SPEC.md)、[docs/rag-acceptance-plan.md](rag-acceptance-plan.md)、[docs/ragas-guide.md](ragas-guide.md)

---

## 目录

- [1. 为什么引入 SDD](#1-为什么引入-sdd)
- [2. 核心概念](#2-核心概念)
- [3. 本项目的 SDD 现状](#3-本项目的-sdd-现状)
- [4. 引入 SDD 的完整步骤（回溯）](#4-引入-sdd-的完整步骤回溯)
- [5. 踩过的坑与原因](#5-踩过的坑与原因必读)
- [6. 日常使用流程](#6-日常使用流程)
  - [6.3 Constitution 生成与编写最佳实践](#63-constitution-生成与编写最佳实践)
  - [6.4 Constitution 立宪时机最佳实践](#64-constitution-立宪时机最佳实践)
  - [6.5 CLAUDE.md 中的 SPECKIT 块自动管理](#65-claudemd-中的-speckit-块自动管理)
- [7. 让 AI 遵守 SDD 的约束机制](#7-让-ai-遵守-sdd-的约束机制)
- [8. 与既有工作的衔接](#8-与既有工作的衔接)
- [9. 新成员 onboarding](#9-新成员-onboarding)
- [10. FAQ](#10-faq)
- [11. 参考资料](#11-参考资料)
- [12. 修订历史](#12-修订历史)

---

## 1. 为什么引入 SDD

### 1.1 项目原本的开发模式

本项目在引入 Spec-Kit 之前已经有一套**自研的轻量级 SDD**：

- **[DEV_SPEC.md](../DEV_SPEC.md)** 作为"单一真相源"（single source of truth），所有 feature 的需求 + 技术设计 + 任务清单都在这里
- **`auto-coder` skill**（见 `.claude/skills/auto-coder/`）自动化"读 DEV_SPEC.md → 识别下一个任务 → 实现 → 测试"的流程

这套模式**能跑**，但有几个局限：

1. **工件粒度单一**：需求、计划、任务全挤在一个 Markdown 文件里，难扩展
2. **无一致性校验**：需求和任务脱节靠人工巡检，容易漏
3. **无版本化约束**：没有"项目宪法"（Constitution）显式约束 AI 的技术决策
4. **单 agent 绑定**：auto-coder 只能在 Claude Code 里跑，其他 AI agent 看不懂
5. **多 feature 并行困难**：一个 DEV_SPEC.md 无法同时管多个 feature

### 1.2 SDD 解决什么问题

**Spec-Driven Development（规约驱动开发）** 把"规约"从**静态文档**升级为**可执行产物**：

- 规约本身就是 AI 的"输入合同"，AI 按规约生成代码
- 四个工件各司其职，粒度分明
- 跨工件一致性有工具校验
- 多 agent 兼容（Claude Code / Cursor / Copilot / Gemini 等）

### 1.3 本项目的升级路径

```
自研 DEV_SPEC.md + auto-coder
         ↓
引入 Spec-Kit（本文档涉及）
         ↓
并存过渡期（DEV_SPEC 作高层技术设计，Spec-Kit 管具体 feature）
         ↓
Spec-Kit 退役（2026-08-12），改用 OpenSpec
```

> **2026-08-13 更正**：本图原先最后一格写的是「（未来）auto-coder 退役，完全由 `speckit-implement` 接管」。**这个预测没有实现，且方向相反** —— 退役的是 Spec-Kit 本身（2026-08-12），`auto-coder` skill 反而保留了下来，用于处理尚未迁移的 legacy 任务。现行流程是 OpenSpec 的 `/opsx:propose → /opsx:apply → /opsx:archive`。

---

## 2. 核心概念

### 2.1 SDD 的核心哲学

| 传统开发 | SDD |
|---|---|
| 人读文档 → 人写代码 | AI 读规约 → AI 生成代码 |
| 文档是参考 | 规约是"合同"，会被自动校验 |
| 一次性过关 | 多步渐进（specify → plan → tasks → implement） |
| 单人认知 | 跨 AI agent 共享 |

### 2.2 四大工件

SDD 的所有工作产物归为四个层级：

| 工件 | 文件 | 回答的问题 | 生成命令（Skill） |
|---|---|---|---|
| **Constitution** | `.specify/memory/constitution.md` | **怎么做**——项目宪法、架构原则、硬约束 | `speckit-constitution` |
| **Spec** | `.specify/features/<name>/spec.md` | **做什么**——用户故事、成功标准、边界用例 | `speckit-specify` |
| **Plan** | `.specify/features/<name>/plan.md` | **用什么**——技术栈、架构、里程碑 | `speckit-plan` |
| **Tasks** | `.specify/features/<name>/tasks.md` | **分几步**——可独立执行的 TODO 列表 | `speckit-tasks` |

**执行顺序**：每个新 feature 依次走 specify → plan → tasks → implement。Constitution 是项目级的，只需写一次，后续按需更新。

> **立宪时机**：Constitution 应该在什么时候首次创建？什么时候修订？这是 SDD 实践中最容易踩坑的问题（立得太晚 → 下游 plan/tasks 无法做 Constitution Check；立得太早 → 写出空话且后续频繁 MAJOR 修宪）。本项目（brownfield + 原则已成熟）建议**立刻立宪、在第一个 feature 之前**；greenfield 项目则建议"first spec 之后、first plan 之前"。**详细分析见 [§6.4 Constitution 立宪时机最佳实践](#64-constitution-立宪时机最佳实践)**。

### 2.3 Spec-Kit 是什么

- **GitHub 官方出品**的 SDD 工具链：https://github.com/github/spec-kit
- 包含 `specify` CLI + 一组可被 AI agent 调用的 skill/command
- 支持多 AI agent（Claude Code / Cursor / Copilot / Gemini 等）
- 当前本项目装的版本：**0.7.6.dev0**（记录在 [.specify/init-options.json](../.specify/init-options.json)）

---

## 3. 本项目的 SDD 现状

### 3.1 目录结构

本项目引入 Spec-Kit 后新增的目录：

```
MODULAR-RAG-MCP-SERVER/
├── .specify/                      # ✅ SDD 工作目录（入库）
│   ├── memory/
│   │   └── constitution.md        # 项目宪法（当前是空模板，待填充）
│   ├── templates/                 # 四大工件的模板
│   │   ├── constitution-template.md
│   │   ├── spec-template.md
│   │   ├── plan-template.md
│   │   ├── tasks-template.md
│   │   └── checklist-template.md
│   ├── scripts/bash/              # SDD 工作流使用的 bash 脚本
│   ├── extensions/git/            # git 扩展（创建 feature 分支等）
│   ├── workflows/                 # 工作流注册表
│   ├── integrations/              # agent 集成清单
│   ├── extensions.yml             # 可用扩展声明
│   ├── integration.json           # 当前 agent 选择（claude）
│   └── init-options.json          # 本次初始化的配置快照
│
├── .claude/skills/speckit-*       # ❌ 个人级 skill（被 .gitignore 整体忽略）
│   ├── speckit-constitution/      # 主流程 5 个
│   ├── speckit-specify/
│   ├── speckit-plan/
│   ├── speckit-tasks/
│   ├── speckit-implement/
│   ├── speckit-clarify/           # 增强 3 个
│   ├── speckit-analyze/
│   └── speckit-checklist/
│
└── CLAUDE.md                      # 末尾追加 4 行 <!-- SPECKIT START/END -->
```

### 3.2 已安装的 8 个核心 skill

经过精简（从 Spec-Kit 默认的 14 个减到 8 个），当前保留：

**主流程 5 个**（每个 feature 都用）：
- `speckit-constitution` — 生成/更新项目宪法
- `speckit-specify` — 从自然语言生成 feature 规约
- `speckit-plan` — 生成实施计划
- `speckit-tasks` — 拆解为任务列表
- `speckit-implement` — 执行任务（取代 auto-coder）

**增强 3 个**（按需调用）：
- `speckit-clarify` — 在 plan 前问关键问题澄清需求
- `speckit-analyze` — 跨工件一致性校验
- `speckit-checklist` — 生成质量检查清单

**已删除 6 个**（保留也无妨，但对本项目冗余）：
- `speckit-git-*`（5 个）— git 流程辅助，本项目已有成熟 git 习惯
- `speckit-taskstoissues` — 把 tasks.md 转 GitHub issues，本项目未用

### 3.3 `.gitignore` 策略（已选定方案 1）

**策略**：`.claude/` 整个目录被 [.gitignore:74](.gitignore:74) 忽略，不改动。

**后果**：
- `.specify/` 入 git（团队共享的 SDD 框架）
- `.claude/skills/speckit-*` 不入 git（每台机器各自 `specify init` 即可）
- 新成员 clone 后本地运行一次 `specify init --here --ai claude --force` 补齐 skill

**为什么选这个**：
- `.claude/` 里可能含个人 mcp 配置、设置、凭证（ignore 的本意）
- `specify init` 是幂等操作，团队成员各自跑一次很简单
- 改 `.gitignore` 是破坏性操作，风险大

---

## 4. 引入 SDD 的完整步骤（回溯）

**参考**：这一节记录本项目 2026-04-23 引入 Spec-Kit 的完整步骤，给后续项目参考。

### 4.1 前置环境

- `uv` 工具链（用于安装 specify-cli）：`uv --version` ≥ 0.11
- Python ≥ 3.11（本项目 Python 3.12.1）
- Git
- Bash shell（Windows 下推荐 Git Bash）

### 4.2 步骤 1：安装 specify-cli

```bash
# 持久化安装（推荐）
uv tool install specify-cli --from git+https://github.com/github/spec-kit.git

# 安装位置：~/.local/bin/specify（可能不在 PATH 里）
# 验证：
specify --version           # 或用完整路径 ~/.local/bin/specify --version
specify check               # 查看支持哪些 AI agent
```

**⚠️ Windows 注意**：安装完成后可能提示 `~/.local/bin` 不在 PATH，可用完整路径 `~/.local/bin/specify.exe` 代替，或运行 `uv tool update-shell` 加到 PATH。

### 4.3 步骤 2：初始化项目

```bash
cd your-project/
specify init --here --ai claude --force --script sh
```

各参数含义：
- `--here`：在当前目录初始化（不新建子目录）
- `--ai claude`：为 Claude Code 生成 skill（可选值：cursor / copilot / codex / cursor / 等）
- `--force`：非空目录跳过确认
- `--script sh`：生成 bash 脚本（Windows+Git Bash 用户推荐；纯 Windows 用 `ps`）

### 4.4 步骤 3：了解实际产生了什么

运行后**不止**创建 `.specify/`，还会往以下位置写文件：

| 位置 | 内容 | 入 git？ |
|---|---|---|
| `.specify/` | SDD 工作目录（35 个文件，~232K） | ✅ 是 |
| `.claude/skills/speckit-*` | 14 个 skill（主流程 + 增强 + git helper） | ❌ 被 `.gitignore` 忽略 |
| `.cursor/skills/speckit-git-*` | 5 个 git helper（**默认副作用**，即使你没选 Cursor） | ⚠️ **建议删** |
| `CLAUDE.md` | 末尾追加 4 行 `<!-- SPECKIT START/END -->` 标记块 | ✅ 已存在，一起改 |

**⚠️ 意外副作用**：即使 `--ai claude`，Spec-Kit 仍会往 `.cursor/skills/` 装 git helper（把 git-* 当作跨 IDE 通用能力）。本项目不用 Cursor 就删掉。

### 4.5 步骤 4：清理冗余

```bash
# 删 .claude/skills 里用不到的 6 个
rm -rf .claude/skills/speckit-git-commit \
       .claude/skills/speckit-git-feature \
       .claude/skills/speckit-git-initialize \
       .claude/skills/speckit-git-remote \
       .claude/skills/speckit-git-validate \
       .claude/skills/speckit-taskstoissues

# 删 .cursor/ 副作用（5 个）
rm -rf .cursor/skills/speckit-git-commit \
       .cursor/skills/speckit-git-feature \
       .cursor/skills/speckit-git-initialize \
       .cursor/skills/speckit-git-remote \
       .cursor/skills/speckit-git-validate
```

清理后 `.claude/skills/speckit-*` 保留 8 个，`.cursor/skills/` 恢复原状。

### 4.6 步骤 5：入库 `.specify/`（可选，按需 commit）

```bash
git add .specify/ CLAUDE.md
git diff --cached --stat          # 确认暂存内容
git commit -m "chore(sdd): introduce Spec-Kit for brownfield SDD workflow"
```

本项目选择**保留 `.gitignore` 不改**，`.claude/skills/` 不进 git（见 §3.3）。

**⚠️ CLAUDE.md 换行符陷阱**：Spec-Kit 追加的 4 行可能用 LF 换行，和原文 CRLF 不一致，会让 `git diff` 看起来像整个文件被重写。解决：
```bash
git checkout -- CLAUDE.md          # 还原
printf '<!-- SPECKIT START -->\r\n...\r\n<!-- SPECKIT END -->\r\n' >> CLAUDE.md
# 保证追加行也是 CRLF 结尾，diff 就只显示 +4 行
```

---

## 5. 踩过的坑与原因（必读）

这一节是本项目引入过程中实际遇到的坑，记录在此避免重复踩。

### 坑 1：Spec-Kit 默认装得多（14 个 skill）

**现象**：运行 `specify init` 后 `.claude/skills/` 下突然出现 14 个 `speckit-*` 目录。

**原因**：Spec-Kit 把主流程 + 增强 + git helper + taskstoissues 全装了，"全家桶"默认。

**结论**：主流程只需要 5 个，增强 3 个按需，其他都可删。精简到 8 个。

### 坑 2：Spec-Kit 会往 `.cursor/skills/` 写东西（即使你选的是 Claude）

**现象**：`--ai claude` 却发现 `.cursor/skills/speckit-git-*` 多出 5 个文件夹。

**原因**：Spec-Kit 把 git helper 视为"跨 IDE 通用能力"，默认装到多个 agent 目录。

**结论**：如果你不用 Cursor，手动 `rm -rf .cursor/skills/speckit-*` 清理。

### 坑 3：`.claude/` 被 `.gitignore` 忽略，skill 不随 git 传播

**现象**：commit 时 `git status` 看不到 `.claude/skills/speckit-*`（虽然磁盘上存在）。

**原因**：[.gitignore:74](.gitignore:74) `.claude/` 把整个目录忽略了。

**选择**：
- **方案 A（选的）**：保持现状，每人 clone 后自己跑 `specify init`
- **方案 B**：精细化 `.gitignore`，解除 `.claude/skills/speckit-*` 的忽略
- **方案 C**：skill 装到 `~/.claude/skills/` 用户全局级（Spec-Kit 不原生支持，需手工搬）

### 坑 4：CLAUDE.md 换行符 CRLF→LF

**现象**：`specify init` 追加了 4 行到 CLAUDE.md，但 `git diff` 显示整个文件（258 行）都被改了。

**原因**：原文件是 CRLF，Spec-Kit 追加时用 LF，git 把换行符差异算成全文重写。

**解决**：见 §4.6 的 `printf '...\r\n' >> CLAUDE.md` 技巧。

### 坑 5：新版 Spec-Kit 用 Skill 而非 Slash Command

**现象**：老教程里的 `/speckit.specify`（带点）在 Claude Code 里找不到。

**原因**：Spec-Kit 0.7+ 改用 Claude Code 的 Skill 机制，不再是 slash command。现在调用方式是：

```
Skill(skill="speckit-specify")
```

或在 Claude Code 里直接让 AI"跑 speckit-specify"。`.claude/commands/` 目录仍然是空的，**不要去找斜杠命令**。

### 坑 6：一条命令的副作用超出预期，执行前要详查

**现象**：`specify init --here --ai claude --force` 一条命令改了 4 个位置（.specify/、.claude/skills/、.cursor/skills/、CLAUDE.md 末尾）。

**教训**：运行 CLI 工具的初始化命令前，要求执行者（AI 或人）先用 `--help` 和文档确认**全部写入点**，声明副作用范围，再执行。

---

## 6. 日常使用流程

### 6.1 新增一个 feature 的完整流程

**以"RAG 质量验收"为例**（见 [docs/rag-acceptance-plan.md](rag-acceptance-plan.md)）：

```
Step 1. speckit-constitution（仅首次）
        └─ 生成 .specify/memory/constitution.md（项目宪法）

Step 2. speckit-specify
        输入："我要做一次 RAG 质量验收，自合成数据集，评估中英双语..."
        输出：.specify/features/001-rag-acceptance/spec.md

Step 3.（可选）speckit-clarify
        └─ AI 针对 spec 提 ≤5 个关键问题，把你的回答编码回 spec.md

Step 4. speckit-plan
        └─ 输出 .specify/features/001-rag-acceptance/plan.md

Step 5. speckit-tasks
        └─ 输出 .specify/features/001-rag-acceptance/tasks.md

Step 6.（可选）speckit-analyze
        └─ 跨 spec/plan/tasks 做一致性校验，产出不一致清单

Step 7.（可选）speckit-checklist
        └─ 产出质量检查清单（需求完整性、可测试性）

Step 8. speckit-implement
        └─ AI 按 tasks.md 逐条执行，写代码、跑测试、更新进度
```

**核心 5 步**：constitution（一次） → specify → plan → tasks → implement。

### 6.2 修改已有 feature

- 直接编辑对应 `.specify/features/<name>/*.md`
- 或重新调用对应 skill（如 `speckit-specify` 会更新已有 spec.md）
- 改动完后跑一次 `speckit-analyze` 检查一致性

### 6.3 Constitution 生成与编写最佳实践

#### 6.3.1 文件位置与初始来源

- **路径**：`.specify/memory/constitution.md`（`specify init` 时复制自 `.specify/templates/constitution-template.md`）
- **模板特点**：含大量 `[PROJECT_NAME]` / `[PRINCIPLE_X_NAME]` 占位符，需要"立宪"动作把它们替换成项目实际原则
- **首次写入**：由 `speckit-constitution` skill 交互式问答驱动，**也可以**先在对话里手工起草后由 AI 落盘（本项目 v1.0.0 走的就是后者）

#### 6.3.2 模板的"硬锚点"（改了会破坏工具识别）

不是所有 section 都可以中文化。检查 `.specify/templates/constitution-template.md` 可知：

| 标题 | 性质 | 是否可改中文 |
|---|---|---|
| `## Core Principles` | **固定** | ❌ 必须保留英文 |
| `### [PRINCIPLE_X_NAME]` | 占位符 | ✅ 可中文 |
| `## [SECTION_2_NAME]` | 占位符 | ✅ 可中文 |
| `## [SECTION_3_NAME]` | 占位符 | ✅ 可中文 |
| `## Governance` | **固定** | ❌ 必须保留英文 |
| `**Version**: ... \| **Ratified**: ... \| **Last Amended**: ...` | 固定 footer | ❌ 必须保留英文 |
| `NON-NEGOTIABLE` 标记 | Spec-Kit 全生态语义 | ❌ 必须保留英文 |

**判别准则**：模板里**没有**用 `[PLACEHOLDER]` 标的就是硬锚点。Spec-Kit 工具按这些固定标题做 anchor，改了风险最大。

#### 6.3.3 每条原则的"4 要素结构"

模板只给了 `[PRINCIPLE_X_NAME]` + `[PRINCIPLE_X_DESCRIPTION]` 两个占位符，但这远远不够。最佳实践是每条原则展开为 **4 个要素**：

```markdown
### N、原则名

简短的祈使句陈述规则（**必须** / **禁止**）。

**立法理由**：为什么这条是必要的（WHY）。**这是最关键的元素** —— 让 AI 在 plan/code 阶段碰到边界情形时能自己判断，而不只是机械执行。

**执行约束**：
- 在哪个文件/目录强制
- code review 检查项
- 测试如何验证
```

**为什么 Rationale 比 Rule 更重要**：Rule 告诉 AI "做什么"，Rationale 告诉 AI "为什么这样做" —— 后者让它能在新场景下推广，而不是死板套规则。

#### 6.3.4 写宪法的 9 条最佳实践（review checklist）

这是本项目立宪时实际套用的清单，可以拿来 review 任何宪法草稿：

**结构层**

1. **结构对齐 Spec-Kit 官方模板** —— 不发明新结构，工具识别才有保障
2. **每条原则 = 4 要素**（见 §6.3.3）

**内容层**

3. **可测试性强制** —— 每条原则必须能写出 checklist 或 lint 规则验证。无法验证的（如"我们重视质量"）不入宪，放进 styleguide
4. **NON-NEGOTIABLE 标记区分** —— SDD 纪律 + 涉及正确性（非偏好）的约束加此标记；架构原则一般不加，允许 plan 在 "Complexity Tracking" 登记例外
5. **Traceability 锚点** —— 每条原则尽量引用真实文件路径（对 brownfield 项目，这能避免"空话宪法"）

**治理层**

6. **版本号语义**：
   - **MAJOR**：删除原则、反转原则、对现有 plan/tasks 不兼容
   - **MINOR**：新增原则、对现有原则的实质性扩展
   - **PATCH**：措辞澄清、补充示例、非语义性修订
7. **明确例外路径** —— plan.md 的 "Complexity Tracking" 是唯一合法偏离机制，未登记 = 违宪

**反模式**

8. **不写**：空话（"重视测试"）、战术细节（"缩进 4 空格" → lint 的事）、无 Rationale 的条款（变 cargo cult）、>10 条原则（无法执行）
9. **数量控制**：5-7 条核心原则是健康区间，加 2-3 条 SDD 纪律，总数控制在 10 条以内

#### 6.3.5 决策清单：什么入宪、什么不入

立宪过程频繁遇到的"该不该入宪"问题，可用这张表判断：

| 类别 | 入宪？ | 归属 |
|---|---|---|
| 架构约束（provider 抽象、配置驱动等） | ✅ 入宪 | constitution.md |
| 不可妥协的协议正确性（如 MCP stdio 不能 print） | ✅ 入宪（NON-NEGOTIABLE） | constitution.md |
| SDD 工作流纪律（spec-first、plan-before-tasks） | ✅ 入宪（NON-NEGOTIABLE） | constitution.md |
| 测试**原则**（必须配套测试） | ✅ 入宪 | constitution.md |
| 测试**阈值**（覆盖率 ≥ 80%） | ❌ 不入宪 | CI / pyproject.toml |
| AI 沟通偏好（中文回答） | ❌ 不入宪 | CLAUDE.md `Interaction Preferences` |
| 代码注释语言 | ❌ 不入宪 | CLAUDE.md `Code Conventions` |
| 文档风格（Google docstring） | ❌ 不入宪 | CLAUDE.md / styleguide |
| 命名约定（小驼峰 / 蛇形） | ❌ 不入宪 | lint config |

**元原则**：

> Constitution = "什么让这套软件**架构正确且可维护**"
> NOT = "团队怎么协作" / "AI 怎么沟通" / "新人 onboarding 怎么舒服"

#### 6.3.6 修宪与日常维护

- **修宪机制**：必须通过 `speckit-constitution` skill 执行，**禁止**直接 Edit `.specify/memory/constitution.md`（绕过 skill = 绕过一致性校验）
- **修宪后必做**：
  1. 同步 `.specify/templates/plan-template.md` 的 Constitution Check 区段
  2. Review 进行中的 feature plan 是否仍合规
  3. Commit message 用 `feat(sdd): ratify ...` 或 `chore(sdd): amend constitution to vX.Y.Z`
- **不要做**：
  - 频繁修宪（权威性会被稀释）
  - 在 PR 里顺手改宪法（应该是独立 PR）
  - 给某个 feature 的特殊需求改宪法（应该走 plan.md 的 Complexity Tracking）

#### 6.3.7 本项目立宪过程速查（2026-04-25）

回溯本项目 v1.0.0 的立宪流程，作为后续项目的参考：

```
1. 评估时机                                  ← §6.4
   - Brownfield + 原则成熟 → 立刻立宪

2. 起草内容（对话里完成，先不落盘）
   - 数量：7 条架构 + 3 条 SDD 纪律 = 10 条
   - 来源：CLAUDE.md "Key Design Principles" + SDD 纪律
   - 标 NON-NEGOTIABLE：5（stdout 协议）、7（测试）、8/9/10（SDD 纪律）

3. 决策清单（见 §6.3.5）
   - 入宪：架构原则 + 测试原则
   - 不入宪：中文偏好、覆盖率数字、注释风格

4. 中英混合方案（见 §6.3.2）
   - 保留英文：Core Principles / Governance / footer / NON-NEGOTIABLE
   - 中文化：原则名 + 立法理由 + 执行约束

5. 落盘 → 同步 plan-template.md → review 在产 feature
6. 单独 commit：feat(sdd): ratify project constitution v1.0.0
```

### 6.4 Constitution 立宪时机最佳实践

宪法是 SDD 的"最高法"，约束所有下游产物。**写得早 → 价值最大；改得勤 → 反而有害**。所以"何时立宪"是核心问题。

#### 6.4.1 三类时机

**时机 A：首次创建（Ratification）—— 项目"立宪时刻"**

两种主流观点：

| 观点 | 时机 | 适用场景 |
|---|---|---|
| **保守派**（Spec-Kit 官方默认） | 第一个 spec 完成后、第一个 plan 之前 | Greenfield + 团队/项目方向未明 |
| **激进派**（本项目推荐） | 引入 SDD 时**立刻**立宪，在第一个 feature 之前 | Brownfield + 项目原则已成熟 |

**关键判别准则：项目原则是否已经成熟？**

- ✅ **已成熟**（本项目情形）：CLAUDE.md 里已有 "Provider-Agnostic / Configuration-Driven / Fail-Fast / Explicit Tracing / Structured Logging / Type Safety" 等久经验证的原则。立宪只是**形式化**已有共识，不是发明新规。立宪越早越好。
- ❌ **未成熟**（典型 greenfield）：团队对项目方向还不清晰，提前立宪容易写出空话（如"我们重视质量""测试很重要"），后续修宪成本高（MAJOR 版本号要 +1）。

**时机 B：修订（Amendment）—— 有限场景**

宪法应该稳定，只在以下情况修订：

| 触发场景 | 例子 | 版本号 |
|---|---|---|
| 新增原则 | 引入"所有外部 API 必须有 mock 层" | MINOR +1 |
| 澄清现有原则 | "Test-First" 补充"集成测试可后置" | PATCH +1 |
| 废弃/反转原则 | 从"单体优先"改"微服务优先" | MAJOR +1 |
| 重大架构决策固化 | 选定某种技术栈作为强制约束 | MINOR +1 |

**反模式**（不要做）：
- 为单 feature 特殊需求修宪 → 改用 plan.md 的 "Complexity Tracking" 记录例外
- 重构代码风格 → 那是 lint 规则的事，不是宪法
- 文档措辞润色 → 直接 Edit，不必走 `speckit-constitution`

**时机 C：周期性回顾（Review）—— 防止僵化**

每 3-6 个月或每个大版本前，跑一次 `speckit-constitution`，即使不改内容也走一遍流程问自己：
- 现在还有原则被持续违反吗？（如果是 → 强化执行 / 承认现实并修宪）
- 有没有"事实上的原则"还没入宪？（团队都在做但没写下来的实践）
- 模板同步还对得上吗？（plan-template.md 的 Constitution Check 区段）

#### 6.4.2 为什么 Greenfield 推荐"first spec 之后"立宪？

这是 Spec-Kit 官方暗含的默认建议，理由：

1. **抽象原则需要具体场景做参照**。没写过任何 feature 时，"我们重视类型安全"这种话太空；具体到"所有公开函数必须类型注解、测试覆盖率 ≥ 80%"才有约束力。
2. **避免过早承诺**。新项目方向常变，过早立宪 → 第一个 feature 就发现某条原则不合理 → 立刻 MAJOR 修宪 → 团队对宪法权威性产生质疑。
3. **第一个 spec 暴露隐藏假设**。写 spec 时会被迫回答"这个组件谁负责？跨服务怎么调？"——这些答案才是宪法的真正素材。

#### 6.4.3 为什么 Brownfield（本项目）推荐"立刻立宪"？

1. **原则已经存在**，只是没形式化。CLAUDE.md 里 "Key Design Principles" 6 条都是经过 100+ commits 验证的共识，不是空话。
2. **新 feature 才是受益者**。Feature-002 已经在做 plan 了，如果宪法还是空模板，plan 模板里的 "Constitution Check" 形同虚设。先立宪 → Feature-002 的 plan 真实接受合规检查 → 价值最大化。
3. **修宪风险低**。已被实战验证的原则不太会被立刻推翻，所以 MAJOR 版本号 +1 的概率不高。
4. **避开了 greenfield 的"空话"风险**。立法者不是凭空想象，而是把已有的、活跃的代码实践编入宪法。

#### 6.4.4 通用判别表

| 项目类型 | 立宪时机 | 核心理由 |
|---|---|---|
| **Brownfield**（原则已成熟） | 引入 SDD 当天，first feature 之前 | 形式化已有共识 |
| **Greenfield**（团队/方向未明） | First spec 之后、first plan 之前 | 避免空话和过早承诺 |
| **Greenfield**（团队成熟 + 领域清晰） | 立刻立宪 | 同 brownfield 逻辑 |

#### 6.4.5 本项目当前（2026-04-25）的具体行动建议

1. **立刻跑** `speckit-constitution`
   - 内容来源：CLAUDE.md 的 "Key Design Principles" 章节（6 条）
   - 同时加入 SDD 自身约束（见 §7.3 的 NON-NEGOTIABLE 条款）
2. **跑完后**：回头快速 review [specs/002-multimodal-query-response/plan.md](../specs/002-multimodal-query-response/plan.md)，确认是否符合新立宪法；违反就在 plan 的 "Complexity Tracking" 登记例外
3. **下次再修**：等出现"这事我们项目其实有共识但没写下来"的瞬间——那就是修宪信号
4. **不要**：每周/每月强制修宪，那会让 SDD 流程变成形式主义

#### 6.4.6 一句话心法

**立法者不是凭空想象，而是把已经"活着"的实践写下来。**

- **有活实践** → 立刻立宪（本项目情形）
- **没活实践** → 等第一个 feature 长出来再立
- **共通**：修宪靠"信号驱动"，不靠日历驱动

### 6.5 CLAUDE.md 中的 SPECKIT 块自动管理

#### 6.5.1 这个块是什么

每个用 Spec-Kit 的项目，CLAUDE.md 里都会有一段：

```markdown
<!-- SPECKIT START -->
**Active SDD Plan**: [specs/<feature-name>/plan.md](...)

For additional context about technologies to be used, project structure,
shell commands, and other important information, read the current plan
above (Feature-XXX: ...). Sibling artifacts in the same directory:
[spec.md](...), [research.md](...), [data-model.md](...),
[contracts/](...), [quickstart.md](...).
<!-- SPECKIT END -->
```

**作用**：Spec-Kit 把它叫 **Active Context Bundle** —— 给 AI 一个**单点入口**，指向当前在做的 feature 的全部 Phase 0/1 产物。

#### 6.5.2 为何里面要列那么多文档？

每个文档承担不同角色，**不是冗余**：

| 文档 | 回答 | AI 用它做什么 |
|---|---|---|
| `spec.md` | **WHAT** —— 需求与边界 | 不做超出 spec 的事 |
| `plan.md` | **HOW** —— 技术方案 + Constitution Check | 主入口，引用其他文件 |
| `research.md` | **WHY** —— 关键决策与拒绝的方案 | 避免推翻已 settled 的决策 |
| `data-model.md` | 实体/类型设计 | 知道有没有新类型要建 |
| `contracts/` | 接口/工具 I/O 契约 | 落代码时按契约对齐 |
| `quickstart.md` | 端到端验证脚本 | 实施完跑这个验收 |

#### 6.5.3 不会膨胀（关键问题答疑）

**新加 feature 时这个块会不会累积？—— 不会。**

证据在 [.claude/skills/speckit-plan/SKILL.md](../.claude/skills/speckit-plan/SKILL.md)：

> **3. Agent context update**:
>    - **Update** the plan reference **between** the `<!-- SPECKIT START -->` and `<!-- SPECKIT END -->` markers in CLAUDE.md to point to the plan file created in step 1

关键动词是 **"Update ... between the markers"** —— 替换两个标记之间的全部内容，不 append。

**行为推演**（假设下周做 Feature-003）：

1. `speckit-specify` 创建 spec（不动 CLAUDE.md）
2. `speckit-plan` 创建 plan，**然后第 3 步覆写** CLAUDE.md 的 SPECKIT 块，指向 Feature-003

CLAUDE.md 的 SPECKIT 块永远只引用 1 个 feature，大小恒定。

#### 6.5.4 设计假设：一次只 implement 一个 feature

Spec-Kit 的核心假设是 **"一次一个 feature"**（类比 git 分支策略 —— 每个 feature 一个分支，implement 期间在该分支上）。所以：

- **同一 branch**：SPECKIT 块永远是当前 active 的那个 feature
- **跨 branch**：不同分支的 CLAUDE.md 各自维护自己的 SPECKIT 块
- **多 feature 并行 = 多分支并行**，各分支独立

#### 6.5.5 边界情形：git merge 冲突

唯一会让 SPECKIT 块"看起来累积"的场景：**手工 git merge 时产生冲突，把两个分支的 SPECKIT 块都保留**。

**处理建议**：

- 合并时如果 SPECKIT 块冲突，**只保留目标分支的版本**（target branch 才是真正的"当前在做"）
- 或者合并完后立即跑一次 `speckit-plan` 让它重新写一次

#### 6.5.6 给人的规矩：不要手工编辑

CLAUDE.md 里的 SPECKIT 块应被视为"**机器管理区**"：

- ❌ 不要手工增删 plan/spec 引用
- ❌ 不要修改 markers `<!-- SPECKIT START -->` / `<!-- SPECKIT END -->`（改了 speckit-plan 找不到）
- ❌ 不要在 markers 之间写自己的笔记
- ✅ 让 `speckit-plan` 来管，每次启动新 feature 自动更新

本项目在 [CLAUDE.md](../CLAUDE.md) 里把这个块单独放在 `## Active Feature (Spec-Kit managed — do not edit manually)` 小节下，明确标识其"机器管理"性质，避免与 § Interaction Preferences 等人类编辑区混淆。

---

## 7. 让 AI 遵守 SDD 的约束机制

**核心问题**：AI（包括 Claude Code）默认行为是"用户提需求，立刻写代码"，**不会主动走 SDD 流程**。没有主动约束，SDD 会变成"装了但没用"的摆设。

解决办法：按成本/效果分四层，从轻到重。

### 7.1 四层约束机制对比

| 层级 | 手段 | 覆盖率 | 配置成本 | 适用阶段 |
|---|---|---|---|---|
| **L1** | CLAUDE.md 写"强制 SDD"规则 | ~60% | 5 分钟 | **起步期**（必做） |
| **L2** | constitution.md 写 NON-NEGOTIABLE 纪律 | ~85% | 顺带宪法完成 | **稳定期**（宪法填充时一起做） |
| **L3** | 会话触发语习惯 | ~90% | 你的自律 | **长期**（永远保持） |
| **L4** | Claude Code hooks 强制拦截 | ~99% | 1-2 天 | **协作/产品化**（选择性上） |

### 7.2 L1：CLAUDE.md 写硬规则（起步必做）

在 [CLAUDE.md](../CLAUDE.md) 的 `## Development Workflow` 章节追加：

```markdown
### Mandatory SDD Workflow

For any feature or non-trivial change, the AI MUST follow:
1. Check if .specify/features/<name>/ exists for this task
2. If NO: run speckit-specify first, then speckit-plan, then speckit-tasks
3. Only AFTER tasks.md exists, run speckit-implement or write code directly
4. NEVER jump straight to Edit/Write for new features

Exceptions (SDD not required):
- Single-file typo/comment fixes
- Dependency version bumps
- One-off exploratory scripts
- Bug fixes with clear root cause (< 10 lines)
- 修改 DEV_SPEC.md 或 docs/ 下文档
```

**效果**：AI 每次会话会读 CLAUDE.md，多数情况会遵守；对"紧急小改"仍可能绕过。

### 7.3 L2：constitution.md 写 NON-NEGOTIABLE 条款（宪法填充时一起做）

`.specify/memory/constitution.md` 是 AI 看得更重的"项目宪法"。填充时把 SDD 纪律作为硬约束写入：

```markdown
## Development Discipline (NON-NEGOTIABLE)

### I. Spec-First Rule
All feature work must have a written spec.md before any code change.
Rationale: Prevents scope creep and makes AI decisions traceable.

### II. Plan-Before-Tasks Rule
tasks.md can only be generated from an existing plan.md.
Rationale: Tasks without plan are tactical noise.

### III. Traceability Rule
Every code change must reference a task ID in commit message (e.g., "refs T-003").
Rationale: Links git history to SDD artifacts, enables audit trail.
```

**效果**：`NON-NEGOTIABLE` 标签让 AI 主动拒绝违反的请求，强约束。

### 7.4 L3：会话触发语习惯（靠你自律）

**你的措辞决定 AI 的路径**：

| 你的原话 | AI 默认反应 |
|---|---|
| "加一个 XX feature" | ❌ 可能直接开始写代码 |
| "快速改一下 XX" | ❌ 基本不会走 SDD |
| "**走 SDD 流程**加一个 XX feature" | ✅ 主动调用 speckit-specify |
| "按 **tasks.md** 执行 T-003" | ✅ 先查 tasks.md |
| "按 **constitution** 第 X 条约束处理" | ✅ 主动查宪法 |

**核心心法**：每次提需求时多加一句"按 SDD"或"按宪法"，AI 就会切换到 SDD 路径。

### 7.5 L4：Claude Code hooks（本项目不推荐现在做）

在 [`.claude/settings.json`](../.claude/settings.json) 加 `PreToolUse` hook，拦截**未经 SDD 的 Edit/Write**：

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [{
          "type": "command",
          "command": "bash .specify/scripts/bash/check-sdd-compliance.sh $CLAUDE_TOOL_FILE"
        }]
      }
    ]
  }
}
```

`check-sdd-compliance.sh` 的逻辑：
1. 接收被改动的文件路径
2. 如果是 `src/` 下文件，检查当前分支是否有对应的 `.specify/features/*/tasks.md`
3. 没有则 exit 1，阻止写入

**效果**：最强，AI 绕不过。
**代价**：配置 + 维护成本高，hook 失效难察觉，可能打断正常工作流。

### 7.6 本项目的最佳实践推荐

**结论：L1 + L2 + L3，不做 L4。**

| 阶段 | 动作 | 时机 |
|---|---|---|
| **现在** | L1：加 CLAUDE.md Mandatory SDD 段落 | 10 分钟 |
| **1-2 周后**（跑通第一个 feature） | L3：养成触发语习惯 | 日常自律 |
| **1-2 个月后**（填充 constitution.md 时） | L2：写 NON-NEGOTIABLE 条款 | 顺手做 |
| **不做** | L4 | —— |

**不做 L4 的理由**：
1. 本项目是**单人学习项目**，没有"多人绕过规则"的风险
2. 学习阶段需要灵活性，hook 会打断探索流程
3. hook 失效难调试（某次 Claude Code 升级后可能静默失效），学习成本太高
4. L1+L2+L3 覆盖 90% 场景已足够

### 7.7 什么时候**必须**升级到 L4

满足**任一**条件时考虑 L4：

- 项目**开始协作**（≥ 2 人规律贡献）
- 项目**产品化**（部署到生产环境、对外发布）
- 发现 AI **频繁绕过 SDD**（如 5 个 feature 有 3 个没走 spec）
- **合规/审计**要求（如 GDPR、SOC2）

### 7.8 反模式警告：SDD 不是越严越好

**错误做法**：把所有改动都强制走 SDD。

后果：
- 改个拼写要写 spec → 团队放弃 SDD
- AI 为了合规硬凑 spec → 内容质量下降
- 探索性实验被阻塞 → 创新受限

**正确姿势**：
- **新 feature、架构级改动** → 严格走 SDD
- **小 bug 修复、一行改动、一次性脚本** → 直接改
- 在 CLAUDE.md 的 `Exceptions` 段落明确列出例外规则

---

## 8. 与既有工作的衔接

### 7.1 DEV_SPEC.md 的去向

**过渡期策略**（推荐）：
- `DEV_SPEC.md` 降级为**高层技术设计文档**（类似 ADR—架构决策记录）
- 新 feature 走 Spec-Kit（`.specify/features/*/`）
- DEV_SPEC.md 里的"任务进度"章节逐步迁移到各 feature 的 tasks.md

**不推荐**：
- 立刻废弃 DEV_SPEC.md → 信息断层
- 把 DEV_SPEC.md 拆成 N 个 feature 的 Spec-Kit 文件 → 工作量巨大且高风险

### 7.2 auto-coder skill 的退役路径

`auto-coder` 和 `speckit-implement` 职责重叠：

| 对比 | auto-coder | speckit-implement |
|---|---|---|
| 输入 | DEV_SPEC.md | tasks.md |
| 兼容性 | 仅 Claude Code | 多 agent |
| 结构化 | 低（手写 Markdown） | 高（模板驱动） |

**退役建议**：
1. 先**并存**：新 feature 用 speckit-implement，老 feature 继续用 auto-coder
2. 当所有 DEV_SPEC 任务完成或迁移后，从 `.claude/skills/` 删除 auto-coder
3. 更新 CLAUDE.md "Spec-Driven Development" 章节，说明改用 Spec-Kit

### 7.3 第一个试水 feature（推荐）

**RAG 质量验收**（[docs/rag-acceptance-plan.md](rag-acceptance-plan.md)）是最好的试水对象：

- 已有详细的手写方案 → 有对照基准
- 范围聚焦（1 周工作量）→ 不会失控
- 产出明确（数据集 + 评估报告）→ 容易验证 SDD 流程是否真的帮上忙

**建议做法**：
```
1. 跑 speckit-constitution 生成项目宪法
2. 把 docs/rag-acceptance-plan.md 的内容喂给 speckit-specify，让它转成标准 spec.md
3. 对比人工方案 vs SDD spec：哪个结构更清晰？信息有没有丢？
4. 走完 plan → tasks → implement
5. 实际跑一遍评估，对比人工做一遍的时间和质量
```

---

## 9. 新成员 onboarding

如果你是新加入项目的开发者（或新会话的 AI），按以下步骤快速上手：

```bash
# 1. Clone 项目
git clone <repo>
cd modular-rag-mcp-server

# 2. 本地装 Spec-Kit（一次性）
uv tool install specify-cli --from git+https://github.com/github/spec-kit.git

# 3. 补齐本地 .claude/skills/speckit-*（因为被 gitignore 没跟 git 同步）
specify init --here --ai claude --force --script sh

# 4. 清理冗余（同 §4.5）
rm -rf .claude/skills/speckit-git-* .claude/skills/speckit-taskstoissues
rm -rf .cursor/skills/speckit-git-*

# 5. 读文档
cat CLAUDE.md                       # 项目整体约定
cat docs/sdd-guide.md               # 本文档
cat .specify/memory/constitution.md # 项目宪法（SDD 核心）
ls .specify/features/               # 看已有的 feature

# 6. 验证
specify check                       # 确认 CLI 可用
```

---

## 10. FAQ

### Q1：Spec-Kit 和传统代码生成工具（Copilot）有啥区别？

Copilot 是**函数级**代码补全（看你写了什么，建议下一行），Spec-Kit 是**项目级**规约驱动（先写需求/计划/任务，再让 AI 整体生成并校验）。两者不冲突，可叠加使用。

### Q2：为什么 constitution 很重要？

constitution.md 是 AI 后续所有决策的"上位法"。没有宪法，AI 每次写代码都可能在架构风格、错误处理、命名规范上"随机选择"；有了宪法，AI 会在 plan 和 implement 阶段主动检查是否符合原则。

### Q3：Spec-Kit 能保证代码质量吗？

**不能直接保证**，但它能保证：
1. 需求不丢（spec.md 里列了的需求，tasks.md 里一定有对应任务）
2. 决策可追溯（plan.md 记录了"为什么选这个技术栈"）
3. 一致性可校验（speckit-analyze 会发现 spec/plan/tasks 之间的矛盾）

质量仍依赖：代码 review、测试、人工把关。

### Q4：如果我不想用 SDD，只想让 AI 写代码呢？

完全可以跳过 SDD，直接让 AI 改代码。SDD 适合的场景：
- **复杂 feature**（需求多、边界多）
- **多人协作**（需要留文档给别人看）
- **长周期项目**（半年以上，需要追溯历史决策）

**小 bug 修复、一次性脚本、探索性实验**都不需要 SDD。

### Q5：Spec-Kit CLI 升级后怎么办？

```bash
# 升级 CLI
uv tool install specify-cli --from git+https://github.com/github/spec-kit.git --force

# 重新初始化（会 merge 到现有 .specify/）
specify init --here --ai claude --force --script sh

# 检查 .specify/ 的 git diff，看模板是否变了
git diff .specify/

# 如果模板有破坏性变更，参考 Spec-Kit 的 CHANGELOG 迁移
```

### Q6：如何回滚 SDD 引入？

```bash
# 1. 删除 Spec-Kit 产物
rm -rf .specify/ .claude/skills/speckit-* .cursor/skills/speckit-*

# 2. 还原 CLAUDE.md（如果已 commit 则用 git revert）
# 手动删除 <!-- SPECKIT START --> 到 <!-- SPECKIT END --> 之间的行

# 3. 卸载 CLI（可选）
uv tool uninstall specify-cli
```

### Q7：DEV_SPEC.md 和 constitution.md 内容会冲突吗？

会有重合（都谈项目原则），但**角色不同**：
- **DEV_SPEC.md**：项目总体技术设计（架构图、数据流、模块划分）——给人看
- **constitution.md**：项目宪法（硬约束、命名规范、禁用模式）——给 AI 看

可并存。DEV_SPEC.md 更具体（"用 ChromaDB 作为向量存储"），constitution.md 更抽象（"每个组件必须有 base 抽象类 + factory"）。

### Q8：Claude Code 找不到 speckit-* skill？

三种可能：
1. 没装：跑 `ls .claude/skills/speckit-*` 确认
2. 装了但未重启 Claude Code：重启会话让它重新加载 skill 列表
3. 路径错误：确认 skill 目录里有 `SKILL.md` 文件

---

## 11. 参考资料

### 官方
- [GitHub Spec-Kit 仓库](https://github.com/github/spec-kit)
- [Spec-Kit 文档首页](https://github.com/github/spec-kit#readme)

### 本项目相关
- [CLAUDE.md](../CLAUDE.md) — 项目整体约定
- [DEV_SPEC.md](../DEV_SPEC.md) — 项目技术设计
- [docs/rag-acceptance-plan.md](rag-acceptance-plan.md) — RAG 验收方案（SDD 第一个候选 feature）
- [docs/ragas-guide.md](ragas-guide.md) — RAGAS 评估指南
- [.specify/memory/constitution.md](../.specify/memory/constitution.md) — 项目宪法（待填充）

### 理论
- 关键字搜索："Spec-Driven Development"、"executable specifications"、"AI-native development"

---

## 12. 修订历史

| 日期 | 版本 | 变更 |
|---|---|---|
| 2026-04-23 | v1.0 | 初版：引入 Spec-Kit 0.7.6.dev0，记录完整过程 + 踩过的坑 + 日常用法 |
| 2026-04-23 | v1.1 | 新增 §7 章节：让 AI 遵守 SDD 的四层约束机制 + 本项目最佳实践推荐（L1+L2+L3） |
| 2026-04-25 | v1.2 | 新增 §6.4：Constitution 立宪时机最佳实践（Greenfield vs Brownfield 判别准则、修订/回顾时机、本项目当前行动建议） |
| 2026-04-25 | v1.3 | §2.2 追加立宪时机提示块 + 指向 §6.4 的锚链接，提升可发现性 |
| 2026-04-25 | v1.4 | 大幅扩写 §6.3 为"Constitution 生成与编写最佳实践"（4 要素结构、9 条 review checklist、入宪决策表、修宪流程、本项目立宪过程速查）；新增 §6.5"SPECKIT 块自动管理"（基于 speckit-plan SKILL.md 证据，论证不会膨胀） |
