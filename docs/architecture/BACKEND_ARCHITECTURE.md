# Backend Architecture

FastAPI, async SQLModel/SQLAlchemy (asyncpg), Python 3.12. The pipeline stages are covered in [AUDIO_PROCESSING_PIPELINE.md](AUDIO_PROCESSING_PIPELINE.md); settings in [CONFIGURATION.md](../backend/CONFIGURATION.md); routes in [REST_API_REFERENCE.md](../api/REST_API_REFERENCE.md); tables in [DATABASE_SCHEMA.md](DATABASE_SCHEMA.md).

## Layout (`backend/app/`)

| Path | Role |
|---|---|
| `main.py` | App, lifespan, middleware (CORS, slowapi, security headers, request id), Prometheus `/metrics`, `/health` |
| `api/main.py` | Registers the 20 domain routers under `/api/v1` |
| `api/deps.py` | `get_db` / `SessionDep`, `get_current_user` / `CurrentUser`, `get_supabase` |
| `api/routes/` | Route handlers. Inference passthroughs (`vad/`, `transcription/`, `diarization/`, `emotion/`, `full/`) each pair a `router.py` with a `service.py`. |
| `core/config.py` | `Settings` + startup validation |
| `core/database.py` | Async engine (pool 15 + 20 overflow, statement cache off), `get_session`, `create_db_and_tables` |
| `core/security.py` | JWT and bcrypt |
| `core/interaction_processing.py` | Processing worker, speaker-role assignment, persistence, scoring hand-off |
| `core/kaggle_client.py`, `core/inference_contracts.py` | Local vs Kaggle inference clients; response normalization |
| `core/audio_resolver.py`, `core/audio_folder_watcher.py` | Audio lookup (local FS / Supabase Storage); `storage/audio/<org>/` auto-ingest |
| `core/emotion_fusion.py` | Acoustic + text emotion fusion |
| `core/knowledge_versioning.py`, `core/knowledge_seed.py` | Org knowledge snapshots / restore; KB seeding |
| `core/notification_service.py`, `core/feedback_export.py` | In-app notifications; feedback export |
| `core/llm_circuit_breaker.py`, `core/rate_limit.py`, `core/cache.py`, `core/request_context.py` | LLM breaker, slowapi limiter, dashboard TTL cache (300 s), request-id logging |
| `llm_trigger/` | `service.py` (trigger engine), `chains.py` (Ollama Cloud / Groq LangChain models), `prompts.py` + `prompt_constants.py`, `retrieval.py` (Qdrant), `scoring.py`, `schemas.py` |
| `models/` | SQLModel tables and enums |
| `schemas/assistant.py` | Assistant request/response models |

Outside `app/`:

- `backend/scripts/`: seeders (`seed_nexalink.py`, `seed_meridian.py`), `reset_local_db.py` and maintenance scripts. `scripts/manual/` holds ad-hoc probes that pytest does not collect.
- `backend/alembic/`: migrations.

## Startup (`lifespan` in `app/main.py`)

1. `validate_startup_settings`: fails fast on bad secrets or provider keys.
2. `create_db_and_tables()`: `SQLModel.metadata.create_all`, which creates missing tables only.
3. If `SEED_DEMO_DATA`: run the NexaLink and Meridian seeders.
4. `start_processing_worker()`: resets interactions stuck in `processing` to `pending` and enqueues every `pending` interaction.
5. `start_audio_folder_watcher()`: does nothing unless `AUDIO_FOLDER_WATCHER_ENABLED`; when enabled it scans every 15 s.
6. Pre-warms the dashboard cache in a background task.

On shutdown the watcher stops, then the worker.

## Request dependencies (`app/api/deps.py`)

- `get_db` yields one `AsyncSession` per request.
- `get_current_user` reads the `vocalmind_token` cookie (or the Bearer header), decodes the JWT, and loads an active `User`.
- `get_supabase` builds a Supabase client from `SUPABASE_URL` and `SUPABASE_SERVICE_KEY`.

## Processing worker (`core/interaction_processing.py`)

- **Queues:** a single in-process asyncio task with two `asyncio.Queue`s, normal and priority. The priority queue is always drained first; `POST /interactions/{id}/reprocess?priority=true` puts an interaction there. Interactions are processed one at a time.
- **Restarts:** the queue lives in memory, so it is lost on restart. The backlog is rebuilt from DB status at the next startup.
- **Uploads:** create the `Interaction` plus 6 `ProcessingJob` rows (`diarization`, `stt`, `emotion`, `reasoning`, `scoring`, `rag_eval`) and enqueue it. The folder watcher does the same.
- **Speaker roles:**
  - For multi-cluster diarization, a logistic-regression + TF-IDF model (`core/model.pkl`, `core/vectorizer.pkl`, both committed) is combined with hand-weighted phrase scores.
  - When diarization collapses to one cluster, segments are labelled individually.
  - If the `.pkl` files fail to load, only the phrase heuristics are used.
- **LLM trigger evaluation** runs under `LLM_TRIGGER_EVAL_TIMEOUT_SECONDS` (default 600, read with `os.getenv`).
