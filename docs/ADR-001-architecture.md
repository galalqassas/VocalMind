# ADR-001: Monolithic Backend + ML Microservices

**Status:** Accepted
**Date:** 2026-06-15

## Context

Each call goes through VAD, ASR + alignment + diarization, acoustic emotion, text emotion, LLM reasoning and scoring. The heavy model stages need different runtimes (torch/CUDA, pyannote, FunASR). The business layer (auth, RBAC, dashboards, review queue, notifications, Manager Assistant) is plain async FastAPI on Postgres.

## Decision

One FastAPI + SQLModel + Postgres backend, with every heavy model behind HTTP. By default the models run on the Kaggle GPU server (`services/kaggle/server.py`); the equivalent local containers are the compose profile `local-ml`. The backend itself installs no deep-learning framework.

| Component | How the backend uses it |
|---|---|
| Speech models: Kaggle `/full` (Silero VAD + Whisper + pyannote + emotion2vec), or `services/whisperx` (Silero VAD + ASR + align + pyannote) and `services/emotion` (emotion2vec) | Async HTTP, routed by `IS_LOCAL` (`backend/app/core/kaggle_client.py`) |
| Text emotion | HTTP `/predict_text` (Kaggle or `services/emotion`); fusion in-process in `backend/app/core/emotion_fusion.py` |
| Embeddings, PDF parsing, reranking | Kaggle `/embed`, `/parse`, `/rerank`, or Ollama + in-process Docling/cross-encoder, routed by `RAG_MODELS_HOST` |
| Speaker roles | In-process scikit-learn LR + TF-IDF (`backend/app/core/model.pkl`) |
| RAG query code (`services/rag`) | Imported in-process. Bind-mounted at `/app/rag`, loaded by `backend/app/api/routes/rag.py` and `llm_trigger/service.py`. |
| RAG ingestion | Separate container (`ingestion`) running `services/rag/main.py --watch` |
| Qdrant; Ollama (`local-ml` profile) | Infra containers |
| LLMs | External APIs: Ollama Cloud or Groq, selected by `LLM_PROVIDER` / `ASSISTANT_LLM_PROVIDER` |

## Rationale

- **Split by runtime, not domain.** Interactions, scores, policies, feedback and notifications share one lifecycle and one database. Splitting them would add cross-service joins without benefit.
- **Isolate GPU and model crashes.** A CUDA or torch failure in a model server fails one HTTP call and marks the job `failed`; it does not kill the API.
- **Keep the app stack small.** With models on Kaggle, the default compose stack needs no GPU and no model downloads.
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
| Transient LLM error (rate limit, timeout) | `_invoke_chain_with_retry` in `llm_trigger/chains.py`: 3 attempts with exponential backoff, then the `reasoning` stage fails (no fallback verdict) |
| Kaggle server or local model services down | The stage fails, downstream stages are marked `Not run`, no score is written, and the errors appear in the Session Inspector. Retry with **Reprocess**. |
| Qdrant empty or down | `llm_trigger/retrieval.py` falls back to manual org files under `storage/docs/` |
| Backend restart mid-job | On startup, `_enqueue_pending_interactions_backlog()` resets `processing` interactions to `pending` and re-enqueues every pending one |

## Schema management

- Fresh Postgres: `infra/db/` is mounted as `/docker-entrypoint-initdb.d`, so every `*.sql` there runs on first init: `01_schema.sql`, then SQL migrations `03`–`06`.
- At backend startup, `create_db_and_tables()` runs `SQLModel.metadata.create_all`.
- Existing databases: Alembic revisions in `backend/alembic/versions/`.
- A schema change must update the SQLModel model, `infra/db/01_schema.sql`, and add an Alembic revision.

## Consequences for new work

- New domain features go in the backend unless they bring a heavy ML dependency.
- New heavy model work becomes its own service under `services/`, with its own Dockerfile, called over HTTP.
