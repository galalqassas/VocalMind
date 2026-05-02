# ── Build stage ──────────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /app

# Set HF_HOME for caching models during build
ENV HF_HOME=/app/hf_cache

# Install system dependencies
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy dependency files first for caching
COPY pyproject.toml uv.lock ./

# Install dependencies (torch installed separately so uv.lock stays stable without a huge lock refresh)
RUN uv sync --no-dev --locked \
	&& uv pip install --python /app/.venv/bin/python pypdf \
	&& uv pip install --python /app/.venv/bin/python torch --index-url https://download.pytorch.org/whl/cpu

# ── Runtime stage ────────────────────────────────────────────────────────────
FROM python:3.12-slim

# Install runtime system dependencies
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Ensure we use the same HF_HOME in runtime
ENV HF_HOME=/app/hf_cache

# Copy virtual environment and model cache from builder
COPY --from=builder /app/.venv /app/.venv

# Copy application code
COPY app/ ./app/
COPY scripts/ ./scripts/

# Add venv to PATH
ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
