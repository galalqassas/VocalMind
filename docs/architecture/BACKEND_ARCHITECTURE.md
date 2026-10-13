# Backend Architecture

FastAPI, async SQLModel/SQLAlchemy (asyncpg), Python 3.12. The backend installs no deep-learning frameworks (no torch, transformers, datasets, pandas or mlflow); its only in-process model is the scikit-learn speaker-role classifier. Other models run on the Kaggle server or the `local-ml` containers ([SYSTEM_OVERVIEW.md](SYSTEM_OVERVIEW.md#where-models-run)). The pipeline stages are covered in [AUDIO_PROCESSING_PIPELINE.md](AUDIO_PROCESSING_PIPELINE.md); settings in [CONFIGURATION.md](../backend/CONFIGURATION.md); routes in [REST_API_REFERENCE.md](../api/REST_API_REFERENCE.md); tables in [DATABASE_SCHEMA.md](DATABASE_SCHEMA.md).

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
| `core/kaggle_client.py`, `core/inference_contracts.py` | Speech inference clients routed by `IS_LOCAL` (Kaggle server or local containers); response normalization |
| `core/audio_resolver.py`, `core/audio_folder_watcher.py` | Audio lookup (local FS / Supabase Storage); `storage/audio/<org>/` auto-ingest |
| `core/emotion_fusion.py` | Text emotion model call + acoustic/text fusion |
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
- **Speaker roles:** `assign_speaker_roles` uses only the logistic-regression + TF-IDF model (`core/model.pkl`, `core/vectorizer.pkl`, both committed). Stereo channel labels are kept; with ≥2 diarization clusters the cluster with the highest mean P(agent) is the agent; otherwise each segment is classified alone. If the `.pkl` files fail to load, the `diarization` stage fails.
- **Failures:** any model or LLM failure fails its `ProcessingJob` and the interaction, with no fallback scores; reprocess retries. See [AUDIO_PROCESSING_PIPELINE.md](AUDIO_PROCESSING_PIPELINE.md#failure-semantics).
- **LLM trigger evaluation** runs under `LLM_TRIGGER_EVAL_TIMEOUT_SECONDS` (default 600, read with `os.getenv`).
