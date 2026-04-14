# Scripts Directory

This directory contains executable scripts for the RAG system.

## Structure

```
scripts/
├── __init__.py
├── __main__.py           # Package entry point
├── ingest.py             # Production: Document ingestion
├── query.py              # Production: Query execution
├── evaluate.py           # Production: Evaluation
├── start_dashboard.py    # Production: Streamlit dashboard
├── test_mcp_connection.py# Production: MCP connection testing
├── dev/                 # Development utilities (not tracked in git)
│   ├── __init__.py
│   └── *.py            # Temporary debug scripts
└── README.md
```

## Production Scripts

Scripts in the root `scripts/` directory are maintained, documented, and version-controlled:

- **ingest.py**: Offline document ingestion CLI
- **query.py**: Query execution CLI
- **evaluate.py**: Evaluation suite runner
- **start_dashboard.py**: Streamlit dashboard launcher
- **test_mcp_connection.py**: MCP server connectivity testing

## Development Scripts

Temporary debugging scripts should be placed in `scripts/dev/` and **not committed to git**.

Add `scripts/dev/` to `.gitignore`:

```gitignore
scripts/dev/
```

## Running Scripts

Using `uv run` (recommended, keeps execution consistent with `uv.lock`):
```bash
uv run python -m scripts ingest --path ./docs/
uv run python -m scripts query --query "What is RAG?"
```

As package entry point:
```bash
python -m scripts ingest --path ./docs/
python -m scripts query --query "What is RAG?"
```

Direct execution (also works):
```bash
python scripts/ingest.py --path ./docs/
python scripts/query.py --query "What is RAG?"
```

## Best Practices

1. **Use logger, not print**: Import `from src.observability.logger import get_logger`
2. **Type hints**: Add type annotations to all functions
3. **Argparse**: Use `argparse` for CLI parameters
4. **Error handling**: Catch specific exceptions, provide helpful error messages
5. **Exit codes**: Return `0` for success, non-zero for errors
6. **Docstrings**: Google-style docstrings for public APIs
7. **Don't hardcode paths**: Use `Path` and relative paths
