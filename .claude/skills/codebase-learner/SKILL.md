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

---

## ⚠️ 重要规则：学习进度同步

**每次学习会话结束后，必须将学习内容同步到文档！**

### 同步目标文件

```
.claude/skills/codebase-learner/records/learning-journey.md
```

### 必须同步的内容

1. **学习日期** - 记录当天日期
2. **学习阶段** - Phase 编号和主题
3. **学习内容** - 详细的学习笔记、流程图、代码解读
4. **关键收获** - 总结表格
5. **下一步建议** - 后续学习方向

### 同步格式模板

```markdown
## Phase X: 主题 (YYYY-MM-DD)

> 学习目标：...

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

---

## 学习总结（更新）

### 已完成阶段

| 阶段 | 内容 | 状态 |
|------|------|------|
| Phase 1-6 | 基础学习 | ✅ 已完成 |
| Phase X | 主题 | ✅ 已完成 (YYYY-MM-DD) |

### 下一步建议

1. ...
```

### 执行时机

- ✅ 每次学习会话结束时
- ✅ 用户明确表示"继续学习"新主题后
- ✅ 完成一个 Phase 后

### 注意事项

- 使用 Edit 工具追加内容，不要覆盖已有内容
- 如果文件有重复内容，先清理再追加
- 保持文档结构清晰，便于后续查阅
- 更新完成后，告知用户："学习记录已同步到 `learning-journey.md`"

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
