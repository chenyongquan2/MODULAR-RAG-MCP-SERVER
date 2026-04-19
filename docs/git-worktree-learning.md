# Git Worktree 学习笔记

> 以 Claude Code 的实际使用场景为例，理解 Git Worktree 的本质和用法。

---

## Worktree 是什么

**一句话：Worktree 是同一个 Git 仓库的另一个工作目录，让你同时在两个分支上工作。**

### 没有 Worktree 的情况

```
C:\workspace\MODULAR-RAG-MCP-SERVER\     ← 只有一个工作目录
  └── 当前在 main 分支

想切到其他分支？ → git checkout feature-x → 整个目录的文件都变了
想回到 main？    → git checkout main      → 文件又全变回来
```

问题：**同一时刻只能在一个分支上工作**。切分支时，未提交的改动会冲突或丢失。

### 有了 Worktree

```
C:\workspace\MODULAR-RAG-MCP-SERVER\                    ← main 分支（不受影响）
  └── .claude\worktrees\bold-mccarthy\                  ← claude/bold-mccarthy 分支（独立目录）
```

两个目录、两个分支、**同一个仓库**。互不干扰，可以同时操作。

---

## Worktree 的本质

Worktree 是同一个 Git 仓库的第二个（第三个、第四个...）工作目录。

关键点：**底层共享同一个 `.git` 数据库**，不是 clone 出来的副本。

```
C:\workspace\MODULAR-RAG-MCP-SERVER\          ← 主工作目录 (main 分支)
  ├── .git/                                   ← 唯一的 Git 数据库
  ├── src/
  └── ...

  └── .claude\worktrees\bold-mccarthy\        ← worktree 工作目录
      ├── .git  (一个文件，指回上面的 .git/)    ← 不是独立数据库，只是指针
      ├── src/
      └── ...
```

所以：
- 两个目录里的文件**互相独立**，改一边不影响另一边
- 但 commit 历史、分支列表、远程仓库配置**共享同一份**
- 在 worktree 里提交的代码，在主目录 `git log --all` 也能看到

类比：**Git 允许你把同一个仓库摊开到多张桌子上，每张桌子翻到不同的页面。**

---

## Worktree vs 分支

| | 分支 (Branch) | Worktree |
|--|--------------|----------|
| **是什么** | 一条提交记录的链 | 一个额外的工作目录 |
| **存在形式** | 指针（几个字节） | 完整的文件目录（占磁盘空间） |
| **解决的问题** | 代码的版本管理 | 同时在多个分支上工作 |
| **数量** | 可以有无数个 | 每个分支最多一个 |
| **类比** | 书的不同章节草稿 | 多张桌子，每张桌子摊开不同章节 |

分支是**逻辑概念**，worktree 是**物理目录**。Worktree 必须关联一个分支（或一个 commit），但分支不一定需要 worktree。

---

## Claude Code 中的 Worktree

### Claude Code 自动做了什么

你使用 Claude Code 时并没有手动创建 worktree 和分支，这些是 Claude Code 在会话开始时**自动完成**的。

等价于执行了这两条命令：

```bash
# 1. 创建分支 + worktree（一条命令同时完成）
git worktree add .claude/worktrees/bold-mccarthy -b claude/bold-mccarthy

# 2. 进入 worktree 目录工作
cd .claude/worktrees/bold-mccarthy
```

其中 `-b claude/bold-mccarthy` 是"创建新分支并关联到这个 worktree"的意思。

### 为什么 Claude Code 要用 Worktree

```
你在主目录可能有未提交的工作
  │
  ├── 如果直接在 main 上改 → 你的工作和 Claude 的改动混在一起
  │
  └── 用 worktree → Claude 在隔离目录改，你的主目录完全不受影响
                     满意后合并，不满意直接删掉
```

核心目的是**隔离**——Claude 的所有改动都在独立分支的独立目录里，不影响用户的主工作目录。

### 会话结束时的合并流程

如果你对改动满意，合并等价于：

```bash
# 3. 回到主目录
cd C:\workspace\MODULAR-RAG-MCP-SERVER

# 4. 合并分支
git merge claude/bold-mccarthy

# 5. 清理 worktree 和分支
git worktree remove .claude/worktrees/bold-mccarthy
git branch -d claude/bold-mccarthy
```

### 关于随机命名

`bold-mccarthy` 这个名字是 Claude Code **随机生成**的。格式是 `形容词-名字`，比如：

- `bold-mccarthy`
- `quiet-einstein`
- `swift-turing`

类似 Docker 给容器起的随机名（`hungry_panda`、`elegant_fermat`）。

**这个名字没有业务含义，本质就是一个人类友好的随机 ID。** 之所以用词组而不是 UUID，是因为：

```
# UUID —— 给机器看
.claude/worktrees/a3f7b2c1-9d4e-4812-bf1a-8c3d5e6f7890

# 随机词组 —— 给人看
.claude/worktrees/bold-mccarthy
```

两者都唯一，但词组更容易辨认、口头交流时更方便。

更好的做法是起有意义的名字（如 `k8s-deployment`），但 Claude Code 自动创建时不知道接下来要做什么，所以只能随机取名。

---

## Claude Code 中何时该用 Worktree

### 需要 Worktree 的场景

| 场景 | 原因 |
|------|------|
| 做一个较大的新功能（如加 K8s 部署） | 隔离改动，不满意可以整个丢掉 |
| 同时在多个功能上并行工作 | 每个任务一个 worktree，互不干扰 |
| 想尝试多种方案对比 | 每个方案一个 worktree，最后选最好的合并 |
| 不确定改动是否正确，想保留后悔药 | 主目录完全不受影响，随时可以放弃 |

### 不需要 Worktree 的场景

| 场景 | 原因 |
|------|------|
| 修个小 bug、改几行代码 | 直接改就行，没必要隔离 |
| 单个顺序任务 | 常规会话足够 |
| 只是问问题、读代码、不改文件 | 没有改动就不需要隔离 |
| 磁盘空间紧张 | 每个 worktree 会复制一份完整的项目文件 |

**一句话判断：改动大、想要后悔药 → 用 worktree。改动小、确定要改 → 不用。**

### 如何开启 Worktree

#### 方式一：启动时指定（推荐）

```bash
# 自动生成随机名字
claude --worktree
claude -w

# 指定有意义的名字（推荐，方便辨认）
claude --worktree k8s-deployment
claude -w fix-auth-bug
```

#### 方式二：会话中途开启

直接对 Claude 说：

```
start a worktree
work in a worktree
```

Claude 会自动创建并切换进去。

#### 方式三：配合 tmux 多窗口并行

```bash
claude -w feature-a --tmux
claude -w feature-b --tmux
```

#### 关于 tmux

**tmux 是一个终端多窗口管理器。** 它让你在一个终端窗口里分出多个面板，同时看到多个程序的输出：

```
没有 tmux：
┌──────────────────────────┐
│ 只能看一个终端             │
│ 想看另一个？切换窗口        │
└──────────────────────────┘

有 tmux：
┌────────────┬─────────────┐
│ claude -w   │ claude -w   │
│ feature-a   │ feature-b   │
│ (左边干活)   │ (右边干活)   │
└────────────┴─────────────┘
```

在 Claude Code 里加 `--tmux` 就是让多个 worktree 会话**并排显示在同一个终端里**，方便同时观察。不加也完全能用，只是需要在多个终端窗口之间手动切换。

### 配套配置

#### `.worktreeinclude` — 自动复制 gitignored 文件

Worktree 是全新的目录，默认不包含 `.env` 等被 gitignore 的文件。在项目根目录创建 `.worktreeinclude` 可以让 worktree 自动复制这些文件：

```text
.env
.env.local
config/secrets.json
```

#### 清理

会话结束时 Claude 会提示保留或删除 worktree：
- **没有改动** — 自动清理
- **有改动** — 提示你选择保留（合并后再删）或删除（放弃改动）

手动清理：

```bash
git worktree list          # 查看所有 worktree
git worktree remove <路径>  # 删除指定 worktree
git worktree prune         # 清理残留引用
```

---

## .gitignore 与 Worktree 的关系

### 问题：`.claude/` 在主仓库的 `.gitignore` 里，为何 worktree 内部的 `.claude/` 还是会被 `git add` 收录？

**根本原因：主仓库的 `.gitignore` 和 worktree 内部的 `.gitignore` 是两个独立的视角。**

```
C:\workspace\MODULAR-RAG-MCP-SERVER\           ← 主仓库工作目录
  ├── .gitignore  (写了 .claude/)              ← 忽略的是这个目录下的 .claude/
  ├── .claude/
  │   ├── skills/                              ← 被忽略 ✓
  │   └── worktrees/
  │       └── bold-mccarthy/                   ← Git 把这里当作独立工作目录
  │           ├── .gitignore                   ← 这个才管 bold-mccarthy/ 内部的文件
  │           ├── .claude/                     ← 需要 bold-mccarthy 自己的 .gitignore 来忽略
  │           └── src/
```

- 主仓库的 `.gitignore` 写 `.claude/` → 忽略主仓库下的 `.claude/` 文件夹
- Worktree 内部的 `.gitignore` 写 `.claude/` → 忽略 worktree 内自己生成的 `.claude/` 文件夹

两者互相独立，各管各的工作目录。

### 为什么 worktree 物理上在 `.claude/worktrees/` 里，却不会被主仓库的 `.gitignore` 忽略？

因为 **Git 对 worktree 的寻址是通过 `.git` 文件里的指针，不是通过文件系统路径**。

Worktree 里有一个 `.git` 文件（不是目录），内容是指回主仓库 `.git/` 的指针。Git 通过这个指针认出它是一个独立的工作目录，不会把它当成主仓库的子文件夹内容来处理。所以主仓库 `.gitignore` 里的规则对 worktree 内部的文件没有作用。

### 修复：在 worktree 使用的 `.gitignore` 中补上 `.claude/`

本项目的 `.gitignore` 原本**没有** `.claude/` 这一条，导致 `git add .` 会误收录 `.claude/skills/` 等 Claude Code 运行时生成的文件。

已在 `.gitignore` 末尾追加：

```gitignore
# Claude Code
.claude/
```

验证（无输出 = 排除成功）：

```bash
git add --dry-run . | grep ".claude"
# 无输出，说明 .claude/ 已被正确排除
```

### 经验总结

- 每个 worktree 有自己独立的 `.gitignore` 视角
- 主仓库和 worktree 共享同一个 `.gitignore` 文件（因为共享同一个代码库），但各自只忽略**自己工作目录**下匹配的文件
- Claude Code 会在当前工作目录下自动生成 `.claude/` 目录，因此项目的 `.gitignore` 中应该始终包含 `.claude/` 这一条

---

## 常用 Git Worktree 命令速查

```bash
# 创建 worktree（新建分支并关联）
git worktree add ../my-feature -b feature-branch

# 创建 worktree（使用已有分支）
git worktree add ../my-feature existing-branch

# 查看所有 worktree
git worktree list

# 删除 worktree（用完后清理）
git worktree remove ../my-feature

# 删除后清理残留引用
git worktree prune
```
