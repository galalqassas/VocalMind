# ADR-001: Monolithic Backend + ML Microservices

**Status:** Accepted
**Date:** 2026-06-15

## Context

Each call goes through VAD, ASR + alignment + diarization, acoustic emotion, text emotion, LLM reasoning and scoring. The heavy model stages need different runtimes (torch/CUDA, pyannote, FunASR). The business layer (auth, RBAC, dashboards, review queue, notifications, Manager Assistant) is plain async FastAPI on Postgres.

## Decision

One FastAPI + SQLModel + Postgres backend, with the GPU-heavy stages split out as HTTP services. Docker Compose (`docker-compose.yml`) runs all of them.

| Component | How the backend uses it |
|---|---|
| `services/vad` (Silero), `services/whisperx` (ASR + align + PyAnnote), `services/emotion` (FunASR emotion2vec, acoustic only) | Async HTTP. Routing is chosen by `IS_LOCAL` (compose containers, or the Kaggle server via `backend/app/core/kaggle_client.py`). |
| Text emotion + fusion | In-process: `backend/app/core/emotion_fusion.py` |
| RAG query code (`services/rag`) | Imported in-process. Bind-mounted at `/app/rag`, loaded by `backend/app/api/routes/rag.py` and `llm_trigger/service.py`. |
| RAG ingestion | Separate container (`ingestion`) running `services/rag/main.py --watch` |
| Qdrant, Ollama (embeddings) | Infra containers |
| LLMs | External APIs: Ollama Cloud, Groq or Gemini, selected by `LLM_PROVIDER` / `ASSISTANT_LLM_PROVIDER` |

## Rationale

- **Split by runtime, not domain.** Interactions, scores, policies, feedback and notifications share one lifecycle and one database. Splitting them would add cross-service joins without benefit.
- **Isolate GPU and model crashes.** A CUDA or torch failure in WhisperX fails one HTTP call and marks the job `failed`; it does not kill the API.
- **Scale independently.** Model services can scale without scaling the API, and vice versa.

## Trade-offs accepted

| Trade-off | Consequence |
|---|---|
| Processing worker and audio folder watcher run in-process (`interaction_processing.py`, `audio_folder_watcher.py`) | Only one backend replica can run. The proposed fix is [ADR-002](ADR-002-job-queue.md). |
| One Postgres for everything | Simple transactions and FKs. No per-service data ownership. |
| No circuit breaker on model-service calls | Model services rely on HTTP timeouts. `llm_circuit_breaker.py` guards only the Manager Assistant's LLM providers (state at `GET /health/circuit-breakers`). |

## Failure handling (current)

| Failure | Handling |
|---|---|
| Transient LLM error (rate limit, timeout) | `_invoke_chain_with_retry` in `llm_trigger/chains.py`: 3 attempts with exponential backoff, then the deterministic fallback verdict |
| WhisperX / VAD / emotion down | The stage fails, and `processing_jobs` errors appear in the Session Inspector. Retry with **Reprocess**. |
| Qdrant empty or down | `llm_trigger/retrieval.py` falls back to manual org files under `storage/docs/` |
| Backend restart mid-job | On startup, `_enqueue_pending_interactions_backlog()` resets `processing` interactions to `pending` and re-enqueues every pending one |

## Schema management

- Fresh Postgres: `infra/db/` is mounted as `/docker-entrypoint-initdb.d`, so every `*.sql` there runs on first init: `01_schema.sql`, the legacy `02_seed.sql`, SQL migrations `03`–`06`, and `seed_benchmark_data.sql`.
- At backend startup, `create_db_and_tables()` runs `SQLModel.metadata.create_all`.
- Existing databases: Alembic revisions in `backend/alembic/versions/`.
- A schema change must update the SQLModel model, `infra/db/01_schema.sql`, and add an Alembic revision.

## Consequences for new work

- New domain features go in the backend unless they bring a heavy ML dependency.
- New heavy model work becomes its own service under `services/`, with its own Dockerfile, called over HTTP.
