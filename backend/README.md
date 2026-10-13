# Backend

FastAPI API gateway and processing worker (Python 3.12, [uv](https://github.com/astral-sh/uv)).

## Run natively

```bash
cp .env.example .env          # set SECRET_KEY and OLLAMA_API_KEY (or GROQ_API_KEY)
uv sync
uv run uvicorn app.main:app --reload --port 8000   # same as `make be-dev`
```

The default `.env` expects Postgres on `localhost:5434` and Qdrant on `:6333`; start them with `make support-up`.

`.env.example` sets `IS_LOCAL=false` and `RAG_MODELS_HOST=kaggle`, so every model (speech, text emotion, embeddings) runs on the Kaggle GPU server at `KAGGLE_SERVER_URL` ([services/kaggle/README.md](../services/kaggle/README.md)) and nothing is downloaded locally. The backend installs no deep-learning frameworks; its only local model is the speaker-role classifier. To run models locally instead, `make support-up-local` (adds Ollama, VAD, Emotion, WhisperX), `make ollama-pull-embed`, set `IS_LOCAL=true` and `RAG_MODELS_HOST=local`, and re-ingest the docs. If a model or LLM is unreachable, processing fails that stage (no fallback); reprocess once it is back. Settings and how they are layered: [docs/backend/CONFIGURATION.md](../docs/backend/CONFIGURATION.md).

## Test and lint

```bash
uv run pytest tests/ -v       # make be-test
uv run ruff check .           # make be-lint
```

More detail in [docs/backend/TESTING.md](../docs/backend/TESTING.md).

## Layout

- `app/`: application code; module map in [docs/architecture/BACKEND_ARCHITECTURE.md](../docs/architecture/BACKEND_ARCHITECTURE.md)
- `tests/`: pytest suite (SQLite in-memory)
- `alembic/`: schema migrations; see [alembic/README.md](alembic/README.md)
- `scripts/`: seeders and maintenance; `scripts/manual/` holds ad-hoc probes that pytest does not collect

The speaker-role model files `app/core/model.pkl` and `app/core/vectorizer.pkl` are committed. `tools/download_mlflow_model.py` can pull model artifacts from the DagsHub MLflow server (needs `MLFLOW_TRACKING_PASSWORD`).
