# ── VocalMind Final RAG — Ingestion Container ────────────────────────────────
# Qdrant ingestion; embeddings/parsing/reranking run on Ollama + in-process
# models (RAG_MODELS_HOST=local) or on the Kaggle GPU server (=kaggle).
# RAG_LOCAL_MODELS=true installs Docling + cross-encoder (PyTorch CPU, 5-10 min).

# Builder stage keeps toolchain isolated from runtime image.
# pinned: python:3.11-slim (2026-06-16)
FROM python:3.11-slim@sha256:a01e48f10f90ac3ee65ef6937b9d7c831a3570c81b98d39a547ff09fb359de7f AS builder

WORKDIR /app

# OS dependencies required by Docling / OpenCV build/runtime deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libgl1 \
    libglib2.0-0 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies into an isolated virtualenv for copy-to-runtime
COPY pyproject.toml .
ARG RAG_LOCAL_MODELS=false
ENV PIP_DEFAULT_TIMEOUT=300
RUN python -m venv /opt/venv \
    && if [ "$RAG_LOCAL_MODELS" = "true" ]; then target=".[local-models]"; else target="."; fi \
    && /opt/venv/bin/pip install --no-cache-dir --retries 10 "$target"


# Runtime stage excludes build tooling like gcc.
# pinned: python:3.11-slim (2026-06-16)
FROM python:3.11-slim@sha256:a01e48f10f90ac3ee65ef6937b9d7c831a3570c81b98d39a547ff09fb359de7f

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy only installed runtime deps from builder virtualenv.
COPY --from=builder /opt/venv /opt/venv

# Copy all application code
COPY config.py ingest.py query_engine.py reranker.py evaluator.py main.py __init__.py llm_circuit_breaker.py prompt_safety.py ./

# Directories used at runtime
RUN mkdir -p /app/storage/docs /app/logs /app/reports

ENV VIRTUAL_ENV="/opt/venv"
ENV PATH="/opt/venv/bin:${PATH}"

# Default: keep the ingestion worker alive and refresh on changes.
CMD ["/opt/venv/bin/python", "main.py", "--watch"]
