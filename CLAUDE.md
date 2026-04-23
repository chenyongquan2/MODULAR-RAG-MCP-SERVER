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

### Spec-Driven Development

This project uses DEV_SPEC.md as the single source of truth:
- All features are defined with detailed technical specs in DEV_SPEC.md
- Tasks are tracked with progress status directly in DEV_SPEC.md
- To understand what needs to be built, read the relevant section in DEV_SPEC.md
- The `auto-coder` skill automates this workflow

### Mandatory SDD Workflow

Since 2026-04-23, this project uses GitHub Spec-Kit for feature development. See [docs/sdd-guide.md](docs/sdd-guide.md) for the full guide.

For any feature or non-trivial change, the AI MUST follow:

1. Check if `.specify/features/<name>/` exists for this task
2. If NO: run `speckit-specify` first → `speckit-plan` → `speckit-tasks`
3. Only AFTER `tasks.md` exists, run `speckit-implement` or write code directly
4. NEVER jump straight to Edit/Write for new features

**Exceptions (SDD not required)**:
- Single-file typo/comment fixes
- Dependency version bumps
- One-off exploratory scripts (under `scripts/dev/`)
- Bug fixes with clear root cause (< 10 lines)
- Documentation-only changes (e.g., `DEV_SPEC.md`, `docs/`)

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

**MCP Client Configuration**: The `.claude/mcp.json` file configures the MCP server connection for Claude Code. Update paths in this file if the project is moved to a different location.

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
- **Image Handling**: Images extracted from PDFs are captioned using Vision LLM and stored separately

## Evaluation System

Supports pluggable evaluators (Ragas, custom metrics). Evaluations run against golden test sets in `tests/fixtures/golden_test_set.json`.

Metrics include:
- Context relevance (retrieval quality)
- Answer faithfulness (generation quality)
- Hit rate (recall)
- Custom business metrics

Configure via `evaluation.backends` in settings.yaml.

## Working with DEV_SPEC.md

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
<!-- SPECKIT START -->
For additional context about technologies to be used, project structure,
shell commands, and other important information, read the current plan
<!-- SPECKIT END -->
