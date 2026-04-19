# =============================================================================
# Modular RAG MCP Server - Multi-stage Dockerfile
# =============================================================================
# Usage:
#   docker build -t modular-rag:latest .
#   docker run -p 8501:8501 modular-rag:latest                    # Dashboard
#   docker run modular-rag:latest python -m src.mcp_server.server  # MCP Server
# =============================================================================

# ---------------------------------------------------------------------------
# Stage 1: Build dependencies
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS builder

WORKDIR /build

# Install system dependencies for building Python packages
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc g++ && \
    rm -rf /var/lib/apt/lists/*

# Copy only dependency files first (layer caching)
COPY pyproject.toml README.md ./

# Install dependencies into a virtual env for clean copying
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir . && \
    pip install --no-cache-dir streamlit openai

# ---------------------------------------------------------------------------
# Stage 2: Runtime image
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS runtime

LABEL maintainer="Modular RAG Team"
LABEL description="Modular RAG MCP Server with Dashboard"

WORKDIR /app

# Copy virtual env from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Create non-root user
RUN groupadd -r appuser && useradd -r -g appuser -d /app appuser

# Create required directories
RUN mkdir -p /app/data/db/chroma /app/data/images /app/logs /app/cache && \
    chown -R appuser:appuser /app

# Copy application code
COPY --chown=appuser:appuser src/ ./src/
COPY --chown=appuser:appuser config/ ./config/
COPY --chown=appuser:appuser scripts/ ./scripts/
COPY --chown=appuser:appuser main.py ./
COPY --chown=appuser:appuser pyproject.toml ./

# Switch to non-root user
USER appuser

# Expose Dashboard port
EXPOSE 8501

# Health check for Dashboard mode
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health')" || exit 1

# Default: start Dashboard
CMD ["python", "-m", "streamlit", "run", "src/observability/dashboard/app.py", \
     "--server.port=8501", "--server.address=0.0.0.0", "--server.headless=true"]
