# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a modular RAG (Retrieval-Augmented Generation) server that exposes knowledge retrieval capabilities through the Model Context Protocol (MCP). The project is designed with a pluggable architecture where every component (LLM, embedding, splitter, vector store, reranker, evaluator) can be swapped without code changes.

**Current Status**: Work in progress, expected completion March 2026. The `dev-from-clean-start` branch contains ongoing development with DEV_SPEC task tracking.

## Branch Strategy

- **`main`**: Single commit with latest complete code
- **`dev`**: Full commit history showing incremental development
- **`clean-start`**: Skeleton framework for learning from scratch
- **`dev-from-clean-start`**: Active development branch from clean-start, with DEV_SPEC task tracking

## Common Commands

### Setup
```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e .           # Editable install
pip install -e ".[dev]"    # With dev dependencies
```

### Testing
```bash
pytest tests/unit                    # Run unit tests only
pytest -m unit                       # Tests marked as unit
pytest -m integration                # Integration tests (requires external services)
pytest -m e2e                        # End-to-end pipeline tests
pytest --cov=src                     # With coverage report
pytest tests/unit/test_llm_factory.py -v   # Run single test file
pytest tests/unit/test_llm_factory.py::test_factory_creation -v  # Run single test
```

### Running the System
```bash
python main.py                       # Start MCP server (stdio transport)
python scripts/ingest.py --path <file_or_dir> [--collection <name>] [--force]  # Offline document ingestion
python scripts/query.py --query <text> [--top-k <n>] [--collection <name>]     # Standalone query testing
python scripts/evaluate.py           # Run evaluation suite
python scripts/start_dashboard.py   # Launch Streamlit dashboard
```

**Ingest Examples**:
```bash
python scripts/ingest.py --path ./asset/rag_test_doc.md --force
python scripts/ingest.py --path ./tests/fixtures/sample_documents/ --collection my_docs
```

**Query Examples**:
```bash
python scripts/query.py --query "北极星到底是什么？"
python scripts/query.py --query "How to configure LLM?" --top-k 10
```

### Configuration

All configuration is in `config/settings.yaml`. Change any provider by modifying the corresponding section:

| Setting | Options |
|---------|---------|
| `llm.provider` | glm, azure, openai, ollama, deepseek |
| `embedding.provider` | bge, openai, azure, ollama, glm |
| `splitter.strategy` | recursive, semantic, fixed |
| `rerank.backend` | none, cross_encoder, llm |
| `evaluation.backends` | ragas, custom |

No code changes needed - factories auto-load the new implementation on restart.

**Environment Variables**:
- Use `${VAR_NAME}` syntax in settings.yaml (e.g., `${GLM_API_KEY}`)
- Support default values: `${VAR_NAME:-default_value}`
- Auto-injection: `LLM_API_KEY` and `EMBEDDING_API_KEY` are automatically injected if corresponding fields are empty
- Copy `.env.example` to `.env` and fill in your API keys

## Architecture

### Pluggable Architecture Pattern

Every component follows the same pattern:

1. **Base Abstract Class** in `src/libs/<component>/base_<component>.py`
   - Defines interface with `@abstractmethod`
   - Includes metadata methods like `get_model_name()`, `get_backend_name()`

2. **Provider Implementations** in same directory
   - Example: `azure_llm.py`, `openai_llm.py`, `ollama_llm.py`

3. **Factory** in `<component>_factory.py`
   - Registry pattern: providers auto-register on import
   - `create()` method reads `settings.yaml` and instantiates the configured provider

4. **Configuration Section** in `config/settings.yaml` + corresponding dataclass in `src/core/settings.py`

**To switch providers**: Just edit `settings.yaml` and restart - zero code changes needed.

### Data Flow

**Ingestion Pipeline:**
```
PDF → Loader → Markdown → Splitter → Chunks → Transform →
  ├─ DenseEncoder → VectorUpserter → ChromaDB
  ├─ SparseEncoder → BM25Indexer → BM25 Index
  └─ ImageCaptioner → ImageStorage
```

**Query Pipeline:**
```
Query → QueryProcessor → HybridSearch
  ├─ DenseRetriever → ChromaDB → dense results
  └─ SparseRetriever → BM25 → sparse results
    → Fusion (RRF) → Reranker → ResponseBuilder → Final Response
```

### Tracing System

Two trace types (both JSONL to `logs/traces.jsonl`):

| Trace Type | Stages |
|------------|--------|
| Query (`trace_type: "query"`) | query_processing → dense → sparse → fusion → rerank |
| Ingestion (`trace_type: "ingestion"`) | load → split → transform → embed → upsert |

The Streamlit dashboard reads these traces and dynamically renders based on `method`/`provider` fields - no dashboard code changes needed when swapping components.

## Development Workflow

### Spec-Driven Development (Legacy — Transitional)

> **Status**: 本节描述项目早期的自研 SDD 模式,目前处于退役过渡期。**新 feature 走 Spec-Kit**(见下节 § Mandatory SDD Workflow),legacy DEV_SPEC.md 任务迁移完后本节会移除。

Originally this project used DEV_SPEC.md as the single source of truth:
- All features are defined with detailed technical specs in DEV_SPEC.md
- Tasks are tracked with progress status directly in DEV_SPEC.md
- The `auto-coder` skill automates this workflow

**新 feature 不要走这个流程** —— 直接看下一节。

### Mandatory SDD Workflow

Since 2026-04-23, this project uses GitHub Spec-Kit for feature development. See [docs/sdd-guide.md](docs/sdd-guide.md) for the full guide.

**Project Constitution**: 本项目硬约束在 [.specify/memory/constitution.md](.specify/memory/constitution.md)(2026-04-25 立宪 v1.0.0)。**冲突时以宪法为准**(见宪法 § Governance / Authority)。AI 在生成 plan 时必须执行 plan-template.md 的 Constitution Check 区段。

For any feature or non-trivial change, the AI MUST follow:

1. Check if `.specify/features/<name>/` exists for this task
2. If NO: run `speckit-specify` first → `speckit-plan` → `speckit-tasks`
3. Only AFTER `tasks.md` exists, run `speckit-implement` or write code directly
4. NEVER jump straight to Edit/Write for new features

**Exceptions (SDD not required)**: 见宪法 [Rule VIII 的例外清单](.specify/memory/constitution.md)(避免本文件与宪法漂移)。

**Transition period**: `auto-coder` skill and `speckit-implement` coexist. New features should prefer `speckit-implement`. `auto-coder` will be retired once all legacy DEV_SPEC tasks are migrated.

### Adding a New Provider

Example: Adding a new LLM provider "anthropic"

1. Create `src/libs/llm/anthropic_llm.py`:
```python
from .base_llm import BaseLLM

class AnthropicLLM(BaseLLM):
    def __init__(self, settings, **kwargs):
        # Initialize Anthropic client
        pass

    def generate(self, prompt: str, **kwargs) -> str:
        # Implement generation logic
        pass

    def get_model_name(self) -> str:
        return self.settings.llm.model
```

2. Register in `src/libs/llm/llm_factory.py`:
```python
def _register_builtin_providers() -> None:
    from .anthropic_llm import AnthropicLLM
    LLMFactory.register_provider("anthropic", AnthropicLLM)
```

3. Add config section in `config/settings.yaml`:
```yaml
llm:
  provider: anthropic
  model: claude-3-5-sonnet-20241022
  api_key: ${ANTHROPIC_API_KEY}
```

4. Update dataclass in `src/core/settings.py` if new fields needed

## Key Design Principles

1. **Provider-Agnostic**: Never hardcode provider names in business logic - always use abstract interfaces
2. **Configuration-Driven**: All behavior controlled via `settings.yaml`, not environment-specific code
3. **Fail-Fast Validation**: Settings validated at startup in `src/core/settings.py`
4. **Explicit Tracing**: TraceContext passed explicitly (not thread-local) for transparency
5. **Structured Logging**: Use `observability.logger.get_logger()` - logs to stderr to avoid MCP stdout pollution
6. **Type Safety**: Shared types in `src/core/types.py` (Document, Chunk, SearchResult, etc.)

## Code Conventions

- **Imports**: Use absolute imports from `src/` root (e.g., `from core.settings import load_settings`)
- **Type Hints**: All public functions should have type hints
- **Docstrings**: Use Google-style docstrings for public APIs
- **Error Handling**: Raise `ValueError` for validation errors, `RuntimeError` for operational errors
- **Settings Access**: Always use `settings = load_settings()` to get configuration; never read YAML directly

## MCP Server Details

The MCP server runs on stdio transport and exposes three tools:

| Tool | Description |
|------|-------------|
| `query_knowledge_hub` | Main RAG query endpoint (hybrid search + rerank + response generation with citations) |
| `list_collections` | List available document collections |
| `get_document_summary` | Get metadata for specific documents |

MCP clients (GitHub Copilot, Claude Desktop, etc.) connect via stdio and can call these tools to retrieve knowledge context.

**MCP Client Configuration**: The project-root `.mcp.json` file configures the MCP server connection for Claude Code. Paths are relative to the project root, so the file works unchanged if the project is moved.

> Windows 注意:`command` 指向 `.venv/Scripts/python.exe`。若在 Linux/macOS 使用,改为 `.venv/bin/python`。

## Streamlit Dashboard

Six-page management platform (`scripts/start_dashboard.py`):

1. **System Overview**: Current component configuration and data stats
2. **Data Browser**: View indexed documents, chunks, metadata, images
3. **Ingestion Manager**: Upload files, trigger ingestion, view progress, delete documents
4. **Query Traces**: Query history, latency waterfall, dense/sparse comparison, rerank diff
5. **Ingestion Traces**: Ingestion history, stage-by-stage breakdown
6. **Evaluation Panel**: Run evaluations, view metrics, historical trends

The dashboard is fully dynamic - component names displayed are read from trace logs, so it automatically adapts when you switch providers.

## Important Implementation Notes

- **Settings Loading**: `core.settings.load_settings()` loads from `config/settings.yaml` with env var overrides
- **Logger Usage**: Always import `from observability.logger import get_logger` and call `logger = get_logger(__name__)`
- **PDF Loading**: Currently only PDF and Markdown formats supported via `src/libs/loader/` (uses MarkItDown for PDF → Markdown conversion)
- **Vector Store**: ChromaDB is the only implemented backend currently
- **Image Handling**: Images extracted from PDFs are captioned using Vision LLM and stored separately. 自 feature-002 起，查询命中含图 chunk 时，`query_knowledge_hub` 工具会通过 `MultimodalAssembler` 同时返回文本与图片（MCP `ImageContent`，base64），两种模式（`use_llm=true/false`）策略一致。返图数量上限由 `query.max_images_per_response` 配置（默认 10）

## Evaluation System

Supports pluggable evaluators (Ragas, custom metrics). Evaluations run against golden test sets in `tests/fixtures/golden_test_set.json` (US1 占位) 或 `golden_test_set_{zh,en}.json` (US2 后真实金标)。

**8 项主聚合指标**(Feature-001 后默认):
- RAGAS 4 项:`ragas__context_recall` / `ragas__context_precision` / `ragas__faithfulness` / `ragas__answer_relevancy`
- Custom 4 项:`custom__hit_rate` / `custom__mrr` / `custom__recall` / `custom__ndcg`

**配置**:通过 `evaluation.backends` 启用 backend(`custom` 永久启用,`ragas` 视场景);Judge LLM、embedding、阈值、归档目录全部由 `config/settings.yaml` `evaluation.*` 控制(详见 [specs/001-rag-acceptance/contracts/settings.evaluation.schema.md](specs/001-rag-acceptance/contracts/settings.evaluation.schema.md))。

**Judge / Embedding 切换提示**(spec § Assumptions § Judge 切换与阈值校准):
- 不同 Judge LLM 对同一 (q, ctx, answer) 评分有 3-10% 系统性差异
- 切换 Judge(`evaluation.judge_llm.provider/model`)或 embedding(`evaluation.embedding.*`)后,**FR-013 默认阈值不再适用**;建议:
  1. 先在新 Judge 下用现有金标重跑评估、观察分数分布
  2. 据新分布在 `evaluation.acceptance_thresholds.*` 重新校准
- 每份评估报告自带 `acceptance_thresholds_snapshot` + `judge_llm_identifier` + `embedding_identifier`,跨 Judge 报告可追溯

**关键 CLI**:
- `scripts/evaluate.py --pretty --collection <name>` — 跑评估,自动 archive + delta vs baseline
- `scripts/synthesize_testset.py --collection <c> --lang {zh,en}` — RAGAS TestsetGenerator 合成候选(US2)
- `scripts/refine_testset.py --input <candidate>` — interactive y/e/d/s/q 精修
- `scripts/refine_testset.py --input <candidate> --auto-mode` — **异源 LLM 预筛 + borderline 路由**(Feature-003),只对存疑用例点人 + 收尾抽样自检
- `scripts/backfill_chunk_ids.py --input <golden> --collection <c>` — 语义匹配回填 expected_chunk_ids

### 金标精修自动化(Feature-003)

`--auto-mode` 把逐条 100% 人工确认改为「机器预筛 → 只看存疑 → 抽样自检」,单语种人工耗时目标 30-60 min → ≤ 15 min。**不加该参数时行为与之前完全一致**,不读配置也不调用任何 LLM。

**前置配置** —— `config/settings.yaml` 的 `evaluation.screening_llm`,**必须与 `judge_llm` 异源**(合成端用的就是 judge_llm):

```yaml
evaluation:
  judge_llm:
    model: minimax/minimax-m2.7      # 合成端
  screening_llm:
    provider: glm
    model: z-ai/glm-4.7              # 预筛端,与上面不同即可
    api_key: ${GLM_API_KEY}
```

> 同源判据是**完整标识串** `<provider>:<model>` 相等,不是 provider 相等。实测 judge 标识为 `glm:minimax/minimax-m2.7` —— provider 名义是 glm 但模型经 OpenAI 兼容端点路由到 minimax;只比 provider 会把真正异源的 `glm:glm-4.6` 误判为同源。

**退出码**(仅 `--auto-mode` 下可能出现,不影响默认路径):

| 码 | 含义 |
|---|---|
| 2 | 前置条件不满足:`screening_llm` 未配置 / 与合成端同源 / 无法确认异源(可加 `--allow-same-source` 豁免后者,但**不豁免已确认的同源**) |
| 3 | 预筛模型整体不可用(凭据、网络)。与「模型通但输出不合格」严格区分——后者会全部降级 borderline 交人工 |
| 130 | 中断。**文件仍会写出**并标 `v0.9-partial`,已完成决策不丢 |

**审计记录**:auto 模式产出的金标带 `_review_metadata` 字段,含各路径计数、两端模型标识、阈值快照、borderline 占比、抽样合规率(含 SC-006 的 auto-kept 子集拆分)与告警列表。默认交互模式**不写出**该字段。

**阈值需要校准**:`keep_threshold` / `drop_threshold` 默认 `0.80` 是初始猜测。不同模型的置信度标度不可互换,换预筛模型后必须重新校准 —— 与上文「换 Judge 后阈值失效」是同一回事。校准办法:跑一轮看 `_review_metadata.borderline_ratio`,远高于 20% 说明阈值太严,接近 0% 说明太松。

详见 [specs/003-testset-refine-automation/quickstart.md](specs/003-testset-refine-automation/quickstart.md)。

**Dashboard**:`python scripts/start_dashboard.py` → 评估面板 → "🎯 Feature-001 基线 + 回归" tab(标基线 / 看 delta / 8 项指标趋势)。

## Working with DEV_SPEC.md

> **过渡期说明**:DEV_SPEC.md 现仅作**高层技术设计参考**(类似 ADR);新 feature 的任务追踪在 `.specify/features/<name>/tasks.md`,**不在** DEV_SPEC.md。本节描述的是 legacy 流程,留作历史参考与 legacy 任务定位。

DEV_SPEC.md contains the complete technical specification organized as:
- Section 1-2: Project overview and design principles
- Section 3: Detailed technical design (RAG pipeline, pluggable architecture, tracing, evaluation)
- Section 4: Testing strategy
- Section 5: System architecture diagrams
- Section 6: **Project schedule with task tracking** - this is where task progress is marked

When implementing features, reference the corresponding section in DEV_SPEC.md for detailed requirements.

## Interaction Preferences

- **Language**: 用中文回答问题
- **Role**: 你是一个具备丰富 RAG 知识的专业高级开发工程师，用户是 RAG 开发经验尚浅的学习者
- **Code Comments**: 相关代码需要加上必要的中文注释，帮助理解 RAG 概念和实现细节
- **Testing**: 编写代码后，需要运行单元测试 (`pytest tests/unit -v`)，确保用例通过

## Active Feature (Spec-Kit managed — do not edit manually)

> 本节由 `speckit-plan` 自动维护,指向**当前在做的单个 active feature**。每次有新 feature 进入 implement 阶段时,Spec-Kit 会**覆写**这个块的内容(不累积、不拓展)。**请勿手工编辑** `<!-- SPECKIT START -->` 与 `<!-- SPECKIT END -->` 之间的内容。

<!-- SPECKIT START -->
**Active SDD Plan**: [specs/003-testset-refine-automation/plan.md](specs/003-testset-refine-automation/plan.md)

For additional context about technologies to be used, project structure,
shell commands, and other important information, read the current plan
above (Feature-003: 金标精修自动化(异源预筛 + borderline 路由)). Sibling
artifacts in the same directory:
[spec.md](specs/003-testset-refine-automation/spec.md),
[research.md](specs/003-testset-refine-automation/research.md),
[data-model.md](specs/003-testset-refine-automation/data-model.md),
[contracts/](specs/003-testset-refine-automation/contracts/),
[quickstart.md](specs/003-testset-refine-automation/quickstart.md).

> 注:本 feature 不单开 git 分支,沿用 `dev-from-clean-start`。speckit 脚本
> 需要 `003-*` 形式的分支名,故调用时用 `SPECIFY_FEATURE=003-testset-refine-automation`
> 旁路 `check_feature_branch` 校验(该变量是 spec-kit 官方支持的覆写点)。
<!-- SPECKIT END -->
