---
name: codebase-learner
description: "Guide users through learning and understanding the current codebase. Provides structured learning paths, architecture explanations, and hands-on exercises. Use when user says 'learn codebase', '学习代码', 'understand project', '代码入门', or wants to explore the codebase systematically."
---

# Codebase Learner

## Overview

Guide users through a structured learning journey to understand the current codebase. This skill provides progressive learning paths, architecture explanations, and hands-on exercises tailored to the user's experience level.

## Trigger

| User Says | Behavior |
|-----------|----------|
| "learn codebase" / "学习代码" | Start full learning journey |
| "explain architecture" / "解释架构" | Architecture deep-dive |
| "show me around" / "带我看看" | Guided codebase tour |
| "how does X work" / "X是怎么工作的" | Specific module explanation |
| "codebase overview" / "代码概览" | High-level summary |
| "继续学习" / "continue learning" | Resume from last progress |
| "学习进度" / "learning progress" | Show current progress |
| "整理学习记录" / "compress learning notes" | **Compress and reorganize learning notes** |

---

## ⚠️ 核心规则：学习进度强制同步

**这是一条不可妥协的规则：每次学习会话结束后，必须将学习内容同步到记录文件！**

### 同步目标文件

```
.claude/skills/codebase-learner/records/learning-journey.md
```

### 强制执行流程

```
学习会话开始
    │
    ▼
┌─────────────────────────────────────────────────────────────────┐
│ Step 1: 读取学习进度                                              │
│                                                                  │
│  必须执行: Read learning-journey.md 的「学习进度追踪」部分         │
│  确认当前进度状态                                                 │
└─────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────────┐
│ Step 2: 执行学习内容                                              │
│                                                                  │
│  按照 Phase 顺序进行学习                                          │
│  根据用户水平调整深度                                              │
└─────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────────┐
│ Step 3: 同步学习记录 ⚠️ 强制执行                                  │
│                                                                  │
│  在回复用户之前，必须执行:                                         │
│  - 使用 Edit工具追加学习内容到 learning-journey.md                 │
│  - 更新「学习进度追踪」部分的状态                                   │
│  - 告知用户: "✅ 学习记录已同步"                                   │
└─────────────────────────────────────────────────────────────────┘
    │
    ▼
学习会话结束
```

### 必须同步的内容

每次学习会话必须记录以下内容：

```markdown
## Phase X: 主题 (YYYY-MM-DD)

> 学习目标：...
> 学习时长：约 X 分钟
> 学习者水平：[初学者/中级/高级]

### X.1 子主题

#### 执行流程图
...

#### 关键代码解读
...

#### 使用示例
...

### X.2 关键收获

| 内容 | 关键收获 |
|------|----------|
| ... | ... |

### X.3 思考题（可选）

1. ...
2. ...
```

### 学习进度追踪格式

在 `learning-journey.md` 文件头部维护进度表：

```markdown
# 学习进度追踪

| Phase | 主题 | 状态 | 完成日期 | 学习时长 |
|-------|------|------|----------|----------|
| 1 | 项目概览 | ✅ 已完成 | 2026-03-12 | 30min |
| 2 | 核心概念 | ✅ 已完成 | 2026-03-12 | 45min |
| ... | ... | 🔲 待学习 | - | - |

**当前进度**: Phase X
**下次学习建议**: Phase X+1: [主题]
```

### 执行时机清单

| 时机 | 必须执行的操作 |
|------|---------------|
| 学习会话开始 | 读取当前进度，确认学习内容 |
| 完成一个 Phase 后 | 追加学习内容，更新进度表 |
| 用户说"继续学习" | 读取进度，从上次位置继续 |
| 会话结束前 | 确保同步完成，告知用户 |

### 注意事项

- ⚠️ **绝不跳过同步步骤** - 即使内容简短也要记录
- 使用 Edit 工具追加内容，不要覆盖已有内容
- 如果文件有重复内容，先清理再追加
- 保持文档结构清晰，便于后续查阅
- 每次同步后必须告知用户："✅ 学习记录已同步到 `learning-journey.md`"

---

## 🗜️ 学习记录整理压缩功能

当用户说"整理学习记录"、"压缩学习笔记"、"整理笔记"时，执行此功能。

### 问题背景

随着学习展开，`learning-journey.md` 会出现以下问题：
1. **重复内容** - 多次学习同一主题导致重复
2. **冗余信息** - 过于详细的流程图、代码示例占用大量空间
3. **过期内容** - 随着代码更新，某些学习内容可能过时
4. **结构混乱** - 多个"学习总结"章节分散，难以把握全局

### 执行流程

```
用户请求: "整理学习记录"
    │
    ▼
┌─────────────────────────────────────────────────────────────────┐
│ Step 1: 读取并分析现有内容                                          │
│                                                                  │
│  • 读取 learning-journey.md 全部内容                               │
│  • 识别所有 Phase 章节                                             │
│  • 统计重复的"学习总结"章节                                         │
│  • 标记可能过时的内容                                               │
└─────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────────┐
│ Step 2: 执行压缩整理                                               │
│                                                                  │
│  合并规则:                                                         │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ 1. 同一主题的多个学习记录 → 合并为一个精炼版本                │   │
│  │ 2. 重复的"学习总结" → 只保留最新的总览表                     │   │
│  │ 3. 详细流程图 → 保留核心结构，移除重复细节                    │   │
│  │ 4. 代码示例 → 只保留最具代表性的，移除重复的                  │   │
│  │ 5. 过期内容 → 标记 [已过期] 或移除                           │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────────┐
│ Step 3: 重新组织文档结构                                            │
│                                                                  │
│  新的文档结构:                                                      │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ # 学习记录                                                       │
│  │                                                                │   │
│  │ ## 📊 学习进度追踪（表格，放在最前面）                             │   │
│  │                                                                │   │
│  │ ## 📚 核心知识索引（快速查阅）                                     │   │
│  │   - 按主题分组的关键概念速查表                                     │   │
│  │                                                                │   │
│  │ ## 📝 详细学习笔记                                               │   │
│  │   - Phase 1: 项目概览（精炼版）                                   │   │
│  │   - Phase 2: 核心概念（精炼版）                                   │   │
│  │   - ...                                                         │   │
│  │                                                                │   │
│  │ ## 🎯 学习总结与下一步                                            │   │
│  │   - 总体收获                                                     │   │
│  │   - 下一步建议                                                   │   │
│  │                                                                │   │
│  │ ## 📎 参考资源                                                   │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────────┐
│ Step 4: 写入新文件并告知用户                                         │
│                                                                  │
│  • 使用 Write 工具覆盖原文件                                        │
│  • 报告压缩结果:                                                    │
│    - 原始行数 → 压缩后行数                                           │
│    - 合并的重复章节数量                                              │
│    - 保留的核心知识点数量                                            │
└─────────────────────────────────────────────────────────────────┘
```

### 压缩规则详解

#### 保留的内容（不压缩）

| 类型 | 说明 | 原因 |
|------|------|------|
| 学习进度追踪表 | Phase 状态表格 | 核心进度信息 |
| 关键概念解释 | 首次出现的概念说明 | 学习必需 |
| 核心架构图 | 系统整体架构图 | 理解必需 |
| 关键代码解读 | 第一次出现的代码示例 | 学习必需 |
| 思考题/练习题 | 有助于巩固知识 | 互动必需 |
| 关键收获表格 | 每个Phase的核心收获 | 总结必需 |

#### 压缩的内容（精简）

| 类型 | 压缩方式 | 示例 |
|------|---------|------|
| 重复的流程图 | 合并为一个，移除重复部分 | 多个"查询流程"图合并 |
| 重复的代码示例 | 只保留最完整的版本 | 同一代码出现多次 |
| 详细步骤说明 | 精简为核心步骤 | 10步→5步核心 |
| 冗余的解释 | 保留首次解释 | 同一概念多次解释 |
| 过期的学习总结 | 合并为最新版本 | 多个"学习总结"章节 |

#### 移除的内容（删除）

| 类型 | 说明 |
|------|------|
| 完全重复的章节 | 逐字重复的内容 |
| 已过时的信息 | 代码已删除/重构的部分 |
| 空洞的占位符 | 未填写的模板内容 |
| 多余的分割线 | 只保留必要的分割线 |

### 新文档结构模板

```markdown
# Codebase 学习记录

---

## 📊 学习进度追踪

> **学习者**: [水平]
> **学习目标**: [目标]
> **首次学习**: YYYY-MM-DD

| Phase | 主题 | 状态 | 完成日期 | 学习时长 |
|-------|------|------|----------|----------|
| ... | ... | ... | ... | ... |

**当前进度**: Phase X
**下次学习建议**: Phase X+1

---

## 📚 核心知识索引

### 架构概念
| 概念 | 说明 | 相关文件 |
|------|------|----------|
| 可插拔架构 | 所有组件可通过配置切换 | `src/libs/*/` |
| 工厂模式 | 根据配置创建组件实例 | `*_factory.py` |
| ... | ... | ... |

### 数据流
| 流程 | 阶段 | 关键组件 |
|------|------|----------|
| 导入流程 | Load→Split→Embed→Store | PdfLoader, Chunker, Encoder |
| 查询流程 | Dense+Sparse→RRF→Rerank→LLM | HybridSearch, ResponseBuilder |
| ... | ... | ... |

### MCP 工具
| 工具 | 用途 | 关键类 |
|------|------|--------|
| query_knowledge_hub | 查询知识库 | HybridSearch, ResponseBuilder |
| ... | ... | ... |

---

## 📝 详细学习笔记

### Phase 1: 项目概览

> 学习目标: 理解项目定位和核心功能

**项目简介**: 这是一个模块化 RAG 系统的 MCP Server...

**核心功能**:
- 文档导入: PDF/Markdown → 向量库
- 知识检索: 混合检索 + 重排序
- MCP 服务: 提供标准化工具接口

**关键收获**:
| 内容 | 关键收获 |
|------|----------|
| 项目定位 | RAG + MCP 的组合应用 |

---

### Phase 2: 核心概念

...

---

## 🎯 学习总结

### 总体收获

1. **架构理解**: 可插拔设计使得组件切换零代码改动
2. **核心流程**: 导入和查询两大主流程清晰分离
3. **MCP 协议**: stdio 传输 + JSON-RPC 2.0 格式

### 下一步建议

1. Phase 7: 深入混合检索实现
2. Phase 8: 响应生成系统
3. 动手实践: 添加新的 MCP 工具

---

## 📎 参考资源

- **术语表**: `references/glossary.md`
- **快速参考**: `references/cheatsheet.md`
- **架构决策**: `references/architecture-decisions.md`
- **项目说明**: `CLAUDE.md`
```

### 执行示例

**用户**: 整理学习记录

**AI 执行**:
1. 读取 `learning-journey.md`（假设 5000 行）
2. 分析发现：
   - 5 个重复的"学习总结"章节
   - 3 个重复的"查询流程"流程图
   - 10 个重复的代码示例
3. 执行压缩整理
4. 使用 Write 工具写入新文件（压缩后 2000 行）

**AI 回复**:
```
✅ 学习记录整理完成！

📊 压缩报告:
- 原始行数: 5000 行
- 压缩后行数: 2000 行
- 压缩率: 60%

📝 整理内容:
- 合并了 5 个重复的"学习总结"章节
- 精简了 3 个重复的流程图
- 保留了所有核心知识点和关键代码示例
- 新增了「核心知识索引」便于快速查阅

📁 文件位置: .claude/skills/codebase-learner/records/learning-journey.md
```

---

## Learning Paths

### Path Selection

First, assess the user's experience level:

```
1. Beginner (初学者)
   - New to Python or RAG systems
   - Needs detailed explanations and step-by-step guidance

2. Intermediate (中级)
   - Familiar with Python, new to this architecture
   - Wants to understand design patterns and conventions

3. Advanced (高级)
   - Experienced developer
   - Wants to understand specific implementation details
```

Use `ask_followup_question` to determine the user's level and interests.

---

## Phase 1: Project Overview (项目概览)

### 1.1 High-Level Introduction

**Goal**: Understand what this project does and why it exists.

**Actions**:
1. Read `CLAUDE.md` for project overview
2. Read `README.md` if exists
3. Summarize in user-friendly language:
   - What problem does this solve?
   - What are the main features?
   - Who is the target user?

**Output Format**:
```markdown
## 项目简介

**这是什么？**
[1-2 sentence description]

**核心功能**
- 功能1: 简短说明
- 功能2: 简短说明
- ...

**技术栈**
- 语言: Python 3.x
- 框架: [list]
- 存储: [list]
```

### 1.2 Directory Structure Walkthrough

**Goal**: Understand the codebase organization.

**Actions**:
1. Run `find . -type f -name "*.py" | head -50` to get file list
2. Map directories to responsibilities
3. Create a visual tree with explanations

**Output Format**:
```markdown
## 目录结构

\`\`\`
src/
├── core/           # 核心业务逻辑
│   ├── query_engine/   # 查询引擎
│   └── response/       # 响应生成
├── libs/           # 可插拔组件库
│   ├── llm/           # LLM 提供者
│   └── embedding/     # 嵌入模型
└── mcp_server/     # MCP 协议实现
\`\`\`

**关键入口点**:
- `main.py` - MCP 服务器启动
- `scripts/ingest.py` - 文档导入
- `scripts/query.py` - 查询测试
```

---

## Phase 2: Architecture Deep-Dive (架构深入)

### 2.1 Design Patterns

**Goal**: Understand the architectural patterns used.

**Key Patterns to Explain**:

1. **Factory Pattern (工厂模式)**
   - Location: `src/libs/*/xxx_factory.py`
   - Purpose: Create providers without hardcoding
   - Example: `LLMFactory.create()` returns configured LLM

2. **Strategy Pattern (策略模式)**
   - Location: `src/libs/*/base_xxx.py`
   - Purpose: Swap implementations at runtime
   - Example: Different embedding providers

3. **Pipeline Pattern (管道模式)**
   - Location: `src/ingestion/pipeline.py`
   - Purpose: Chain processing stages
   - Example: Load → Split → Embed → Store

**Output Format**:
```markdown
## 设计模式

### 工厂模式
**位置**: `src/libs/llm/llm_factory.py`

**作用**: 根据配置动态创建 LLM 实例

**代码示例**:
\`\`\`python
# 不需要知道具体实现类
llm = LLMFactory.create(settings)
# 自动返回 GLMLLM, OpenAILLM, 或其他配置的实现
\`\`\`

**好处**:
- 切换提供者只需改配置，无需改代码
- 新增提供者只需实现接口并注册
```

### 2.2 Data Flow

**Goal**: Understand how data moves through the system.

**Two Main Flows**:

1. **Ingestion Flow (导入流程)**
```
PDF → Loader → Markdown → Splitter → Chunks
  → Transform → Embed → Store (Vector + BM25)
```

2. **Query Flow (查询流程)**
```
Query → Dense Search → Sparse Search → Fusion
  → Rerank → Response Generation
```

**Actions**:
1. Read key pipeline files
2. Trace data transformations
3. Create flow diagrams

---

## Phase 3: Module Exploration (模块探索)

### 3.1 Core Modules

**Goal**: Deep-dive into each major module.

**Modules to Cover** (in order):

| Module | Priority | Description |
|--------|----------|-------------|
| `core/settings.py` | High | Configuration system |
| `core/types.py` | High | Shared data types |
| `libs/llm/` | High | LLM abstraction |
| `libs/embedding/` | High | Embedding abstraction |
| `ingestion/pipeline.py` | Medium | Ingestion orchestration |
| `core/query_engine/` | Medium | Query processing |
| `mcp_server/` | Medium | MCP protocol |

**For Each Module**:

1. **Read the base class first**
   - Understand the interface contract
   - See what methods must be implemented

2. **Read one implementation**
   - See how the interface is realized
   - Understand the pattern

3. **Read the factory**
   - See how instances are created
   - Understand registration

### 3.2 Hands-on Exercise

**Goal**: Practice by doing.

**Exercise Ideas**:

1. **Add a new LLM provider**
   - Create a mock LLM for testing
   - Register it in the factory
   - Test with a simple query

2. **Trace a query**
   - Add logging to see each stage
   - Run a query and observe the flow

3. **Modify a prompt template**
   - Find prompt templates in `config/prompts/`
   - Modify and test the effect

---

## Phase 4: Configuration System (配置系统)

### 4.1 Settings Architecture

**Goal**: Understand how configuration works.

**Key Files**:
- `config/settings.yaml` - Main configuration
- `src/core/settings.py` - Settings dataclasses

**Explain**:
1. YAML structure
2. Environment variable substitution (`${VAR_NAME}`)
3. Dataclass validation
4. How to add new settings

### 4.2 Provider Switching Demo

**Goal**: Show the power of configuration-driven design.

**Demo**:
```markdown
## 切换 LLM 提供者

**当前配置** (GLM):
\`\`\`yaml
llm:
  provider: glm
  model: glm-4
  api_key: ${GLM_API_KEY}
\`\`\`

**切换到 OpenAI**:
\`\`\`yaml
llm:
  provider: openai
  model: gpt-4
  api_key: ${OPENAI_API_KEY}
\`\`\`

**无需修改任何代码！** 重启服务即可生效。
```

---

## Phase 5: Testing Strategy (测试策略)

### 5.1 Test Organization

**Goal**: Understand how tests are structured.

**Test Types**:
- `tests/unit/` - Fast, isolated tests
- `tests/integration/` - Real API calls
- `tests/e2e/` - Full pipeline tests

### 5.2 Running Tests

```bash
# Unit tests only
pytest tests/unit -v

# With coverage
pytest --cov=src tests/unit

# Specific test
pytest tests/unit/test_llm_factory.py -v
```

### 5.3 Writing Tests

**Show example test structure**:
```python
@pytest.mark.unit
def test_llm_factory_creates_glm():
    """Test that LLMFactory creates GLM provider correctly."""
    settings = load_settings()
    llm = LLMFactory.create(settings)
    assert isinstance(llm, GLMLLM)
    assert llm.get_model_name() == settings.llm.model
```

---

## Phase 6: Common Tasks (常见任务)

### 6.1 Task Reference

**Goal**: Provide quick reference for common operations.

| Task | Command/Location |
|------|-----------------|
| Start MCP server | `python main.py` |
| Ingest documents | `python scripts/ingest.py --path <file>` |
| Query knowledge | `python scripts/query.py --query "question"` |
| Run tests | `pytest tests/unit -v` |
| View logs | `cat logs/traces.jsonl` |
| Open dashboard | `python scripts/start_dashboard.py` |

### 6.2 Troubleshooting Guide

**Common Issues**:

1. **Import errors**
   - Check venv is activated
   - Run `pip install -e .`

2. **API key errors**
   - Set environment variables
   - Check `settings.yaml` uses `${VAR_NAME}` syntax

3. **Vector store errors**
   - Check ChromaDB is running
   - Verify data directory exists

---

## Phase 7-9: 深入模块学习

### Phase 7: 混合检索系统 (Hybrid Search)

**Goal**: 深入理解混合检索的工作原理。

**关键文件**:
- `src/core/retrieval/hybrid_search.py` - 混合检索入口
- `src/core/retrieval/dense_retriever.py` - 稠密检索实现
- `src/core/retrieval/sparse_retriever.py` - 稀疏检索实现
- `src/core/retrieval/fusion.py` - RRF 融合算法

**学习重点**:
1. Dense 检索如何计算语义相似度
2. Sparse 检索如何使用 BM25 算法
3. RRF 如何融合两种结果
4. Reranker 如何提升排序质量

### Phase 8: 响应生成系统 (Response Builder)

**Goal**: 理解如何用 LLM 生成带引用的答案。

**关键文件**:
- `src/core/response/builder.py` - 响应构建器
- `config/prompts/` - 提示词模板

**学习重点**:
1. 如何构建上下文窗口
2. 如何注入检索结果
3. 如何添加引用来源
4. 如何处理超长上下文

### Phase 9: 向量存储系统 (Vector Store)

**Goal**: 理解 ChromaDB 的使用方式。

**关键文件**:
- `src/libs/vector_store/base_vector_store.py` - 抽象接口
- `src/libs/vector_store/chroma_store.py` - ChromaDB 实现

**学习重点**:
1. 如何存储向量和元数据
2. 如何进行相似度搜索
3. 如何使用过滤器
4. 如何管理集合

---

## Phase 10-12: MCP Server 深入

详见 SKILL.md 中的 Phase 10-12 章节，涵盖：
- MCP Server 架构概览
- 三个工具的详细说明
- 工具协作关系

---

## Phase 13+: 高级主题

### Phase 13: 追踪系统 (Tracing)

**Goal**: 理解如何追踪和调试系统。

**关键文件**:
- `src/core/trace/` - 追踪相关代码
- `logs/traces.jsonl` - 追踪日志

### Phase 14: 评估系统 (Evaluation)

**Goal**: 理解如何评估 RAG 系统质量。

**关键文件**:
- `src/evaluation/` - 评估相关代码
- `tests/fixtures/golden_test_set.json` - 测试数据集

### Phase 15: Streamlit Dashboard

**Goal**: 理解管理面板的实现。

**关键文件**:
- `scripts/start_dashboard.py` - Dashboard 入口
- `src/observability/dashboard/` - Dashboard 组件

---

## Interactive Learning Session

### Session Flow

1. **Assessment** (2 min)
   - Ask about experience level
   - Ask about learning goals
   - Ask about time available

2. **Customized Path** (varies)
   - Select appropriate modules
   - Adjust depth based on level
   - Include hands-on exercises

3. **Q&A** (ongoing)
   - Answer specific questions
   - Provide code examples
   - Suggest further reading

### Example Session

```markdown
**User**: 我想学习这个代码库，我是 Python 中级开发者

**AI**:
欢迎！让我为你定制学习路径。

**你的背景**:
- Python 中级
- 熟悉基本设计模式

**推荐学习路径**:

1. **快速入门** (15 min)
   - 项目概览
   - 目录结构
   - 运行第一个查询

2. **架构深入** (30 min)
   - 工厂模式详解
   - 数据流分析
   - 配置系统

3. **动手实践** (30 min)
   - 添加一个新的 Embedding 提供者
   - 编写单元测试

**我们从哪里开始？**
```

---

## Resources

### references/

| File | Purpose |
|------|---------|
| `glossary.md` | Technical terms and definitions |
| `cheatsheet.md` | Quick reference for common operations |
| `architecture-decisions.md` | Key architectural decisions explained |

### learning-journey.md

学习记录文档，记录用户的学习旅程：
- 学习时间、水平、目标
- 各阶段学习内容
- 关键收获和下一步建议

**使用方式**：
```bash
# 查看学习记录
cat .claude/skills/codebase-learner/records/learning-journey.md
```

---

## Tips for Effective Learning

1. **Read code in this order**:
   - Base classes → Implementations → Factories → Usage

2. **Trace execution**:
   - Start from entry points (`main.py`, scripts)
   - Follow function calls
   - Use logging to see flow

3. **Experiment**:
   - Make small changes
   - Run tests frequently
   - Don't fear breaking things (use git!)

4. **Ask questions**:
   - "Why is it designed this way?"
   - "What if I change this?"
   - "How does X connect to Y?"
