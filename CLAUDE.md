# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a modular RAG (Retrieval-Augmented Generation) server that exposes knowledge retrieval capabilities through the Model Context Protocol (MCP). The project is designed with a pluggable architecture where every component (LLM, embedding, splitter, vector store, reranker, evaluator) can be swapped without code changes.

**Current Status**: Work in progress, expected completion March 2026. The `dev-from-cean-start` branch contains ongoing development with DEV_SPEC task tracking.

## Branch Strategy

- **`main`**: Single commit with latest complete code
- **`dev`**: Full commit history showing incremental development
- **`clean-start`**: Skeleton framework for learning from scratch

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
pytest -v --tb=short                 # Verbose with short tracebacks
```

### Running the System
```bash
python main.py                       # Start MCP server (stdio transport)
python scripts/ingest.py             # Offline document ingestion
python scripts/query.py              # Standalone query testing
python scripts/evaluate.py           # Run evaluation suite
python scripts/start_dashboard.py   # Launch Streamlit dashboard
```

### Configuration
All configuration is in `config/settings.yaml`. Change any provider by modifying the corresponding section:
- `llm.provider` - azure | openai | ollama | deepseek
- `embedding.provider` - openai | azure | ollama
- `splitter.strategy` - recursive | semantic | fixed
- `rerank.backend` - none | cross_encoder | llm
- `evaluation.backends` - ragas | custom

No code changes needed - factories auto-load the new implementation on restart.

## Architecture

### Directory Structure
```
src/
├── core/                  # Core business logic
│   ├── query_engine/     # Hybrid search (dense + sparse + fusion + rerank)
│   ├── response/         # Response generation, citations, multimodal assembly
│   ├── trace/            # Tracing infrastructure
│   ├── settings.py       # Configuration dataclasses & YAML loading
│   └── types.py          # Shared type definitions (Document, Chunk, etc.)
├── ingestion/            # Data ingestion pipeline
│   ├── chunking/         # Document splitting
│   ├── transform/        # Image captioning, metadata enrichment, chunk refining
│   ├── embedding/        # Dense + sparse encoding
│   ├── storage/          # Vector DB upserter, BM25 indexer, image storage
│   └── document_manager.py
├── libs/                 # Pluggable provider implementations (40 files)
│   ├── llm/             # BaseLLM + Azure/OpenAI/Ollama/DeepSeek implementations
│   ├── embedding/       # BaseEmbedding + providers
│   ├── splitter/        # BaseSplitter + strategies
│   ├── vector_store/    # BaseVectorStore + ChromaDB
│   ├── reranker/        # BaseReranker + CrossEncoder/LLM/None
│   ├── evaluator/       # BaseEvaluator + Ragas/Custom
│   └── loader/          # BaseLoader + PDF
├── mcp_server/          # MCP protocol implementation
│   ├── server.py        # MCP server (stdio transport)
│   ├── protocol_handler.py
│   └── tools/           # query_knowledge_hub, list_collections, get_document_summary
└── observability/
    ├── logger.py        # Structured logging (stderr, avoids stdout pollution)
    ├── dashboard/       # 6-page Streamlit management platform
    └── evaluation/      # Evaluation framework

config/
├── settings.yaml        # Main configuration (provider selection, models, API keys)
└── prompts/            # LLM prompt templates

scripts/                # Entry point scripts
data/                   # Runtime data (db/, documents/, images/)
cache/                  # Processing cache
logs/                   # Trace logs (JSONL)
tests/
├── unit/              # Fast, no external deps
├── integration/       # Requires external services
├── e2e/              # Full pipeline tests
└── fixtures/         # sample_documents/, golden_test_set.json
```

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

1. **Query Trace** (`trace_type: "query"`)
   - Stages: query_processing → dense → sparse → fusion → rerank
   - Captures: latency, scores, provider/method names, candidate counts

2. **Ingestion Trace** (`trace_type: "ingestion"`)
   - Stages: load → split → transform → embed → upsert
   - Captures: chunk counts, batch sizes, provider/method names, latency

The Streamlit dashboard reads these traces and dynamically renders based on `method`/`provider` fields - no dashboard code changes needed when swapping components.

## Development Workflow

### Spec-Driven Development

This project uses DEV_SPEC.md as the single source of truth:
- All features are defined with detailed technical specs in DEV_SPEC.md
- Tasks are tracked with progress status directly in DEV_SPEC.md
- To understand what needs to be built, read the relevant section in DEV_SPEC.md
- The `auto-coder` skill (in `.claude/skills/auto-coder/`) automates this workflow

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

### Testing Guidelines

- **Unit tests** (`tests/unit/`): Test isolated logic, mock external dependencies
- **Integration tests** (`tests/integration/`): Test real provider interactions (requires API keys)
- **E2E tests** (`tests/e2e/`): Test full pipeline (ingestion → query → evaluation)
- **Fixtures**: Reusable test data in `tests/fixtures/`

Use markers to control test execution:
```python
@pytest.mark.unit
def test_factory_creation(): ...

@pytest.mark.integration
def test_openai_embedding(): ...
```

## Key Design Principles

1. **Provider-Agnostic**: Never hardcode provider names in business logic - always use abstract interfaces
2. **Configuration-Driven**: All behavior controlled via `settings.yaml`, not environment-specific code
3. **Fail-Fast Validation**: Settings validated at startup in `src/core/settings.py`
4. **Explicit Tracing**: TraceContext passed explicitly (not thread-local) for transparency
5. **Structured Logging**: Use `observability.logger.get_logger()` - logs to stderr to avoid MCP stdout pollution
6. **Type Safety**: Shared types in `src/core/types.py` (Document, Chunk, SearchResult, etc.)

## MCP Server Details

The MCP server runs on stdio transport and exposes three tools:

- `query_knowledge_hub`: Main RAG query endpoint
- `list_collections`: List available document collections
- `get_document_summary`: Get metadata for specific documents

MCP clients (GitHub Copilot, Claude Desktop, etc.) connect via stdio and can call these tools to retrieve knowledge context.

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

- **Settings Loading**: `core.settings.load_settings()` loads from `config/settings.yaml` with env var overrides (e.g., `${OPENAI_API_KEY}`)
- **Logger Usage**: Always import `from observability.logger import get_logger` and call `logger = get_logger(__name__)`
- **PDF Loading**: Currently only PDF format supported via `src/libs/loader/pdf_loader.py` (uses MarkItDown for PDF → Markdown conversion)
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

- 用中文回答问题