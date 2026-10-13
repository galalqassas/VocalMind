# ── Build stage ──────────────────────────────────────────────────────────────
# pinned: python:3.12-slim (2026-06-16)
FROM python:3.12-slim@sha256:c2d8472b831337ab296a8ce652e1ba786e9e3034fc445dc58b50a7f5251f0003 AS builder

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy dependency files first for caching
COPY pyproject.toml uv.lock ./

# Install dependencies (no ML frameworks: models run in the inference services / Kaggle)
RUN uv sync --no-dev

# ── Runtime stage ────────────────────────────────────────────────────────────
# pinned: python:3.12-slim (2026-06-16)
FROM python:3.12-slim@sha256:c2d8472b831337ab296a8ce652e1ba786e9e3034fc445dc58b50a7f5251f0003

# Install runtime system dependencies
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy virtual environment from builder
COPY --from=builder /app/.venv /app/.venv

# Copy application code
COPY app/ ./app/
COPY scripts/ ./scripts/

# Add venv to PATH
ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
