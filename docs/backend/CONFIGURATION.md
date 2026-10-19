# Backend Configuration

The source of truth is `Settings` in `backend/app/core/config.py`. This page lists only the settings that change behaviour. For every field, read `config.py`; for templates, see `backend/.env.example` and the root `.env.example`.

## How values are resolved (later sources win)

1. **Default** in `config.py`.
2. **`backend/.env`**, copied from `backend/.env.example`. Pydantic reads `.env` relative to the working directory, so this only applies when the backend runs from `backend/`.
3. **Process environment.** It always beats `.env`. Under Docker Compose:
   - the container loads `env_file: ./.env` and then `./backend/.env` (`backend/.env` wins on duplicates);
   - the `environment:` block in `docker-compose.yml` wins over both;
   - `${VAR:-default}` inside `docker-compose.yml` is interpolated from the shell or the root `.env`, never from `backend/.env`;
   - compose sets no `DATABASE_URL`, so `backend/.env` must use `db:5432` (or Supabase) for the containerized backend. `localhost:5434` only works from the host.

Values that differ by layer:

| Setting | `config.py` | Compose / example files |
|---|---|---|
| `IS_LOCAL` | `True` | compose `${IS_LOCAL:-false}`; both `.env.example` files set `false` |
| `RAG_MODELS_HOST` | `local` | compose `${RAG_MODELS_HOST:-kaggle}` (backend and ingestion); both `.env.example` files set `kaggle` |
| `LLM_PROVIDER` | `groq` | compose `${LLM_PROVIDER:-ollama_cloud}` |
| `ASSISTANT_LLM_PROVIDER` | `auto` | compose `${ASSISTANT_LLM_PROVIDER:-ollama_cloud}` |
| `AUDIO_FOLDER_WATCHER_ENABLED` | `False` | `true` in `backend/.env.example` |
| `SOP_RETRIEVAL_TOP_K` | `4` | compose `${SOP_RETRIEVAL_TOP_K:-3}` |

Under compose, set `IS_LOCAL` and `RAG_MODELS_HOST` in the root `.env` (or the shell): the backend's `environment:` block overrides their `backend/.env` values. Put `KAGGLE_SERVER_URL` in the root `.env`: the backend reads it through `env_file` (`backend/.env` wins), while the `ingestion` container has no `env_file` and gets it only by interpolation from the root `.env` or shell.

A few variables are read with `os.getenv` instead of `Settings`, so pydantic never loads them from `backend/.env`. Under compose they arrive through `env_file`; natively you must export them in the shell: `EMOTION_MIN_SEGMENT_SECS` (default 1.0), `LLM_TRIGGER_EVAL_TIMEOUT_SECONDS` (600), `DB_POOL_SIZE` (15), `DB_MAX_OVERFLOW` (20), `SQLALCHEMY_ECHO`.

Startup check (`validate_startup_settings`): the backend refuses to start if `SECRET_KEY` is still the placeholder, if `LLM_PROVIDER=groq` has no `GROQ_API_KEY`, or if `LLM_PROVIDER=ollama_cloud` has no `OLLAMA_CLOUD_API_KEY`/`OLLAMA_API_KEY`.

## Core and auth

| Variable | Default | Notes |
|---|---|---|
| `SECRET_KEY` | placeholder (rejected) | JWT HS256 signing key; `openssl rand -hex 32` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | JWT and cookie lifetime |
| `FRONTEND_URL` | `http://localhost:3000` | Added to CORS origins |
| `GOOGLE_CLIENT_ID` | empty | Google sign-in (optional): audience for verifying Google ID tokens |

## Database and seeding

| Variable | Default | Notes |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://vocalmind:vocalmind_dev@localhost:5434/vocalmind` | Host port 5434 maps to container 5432. In production this is the Supabase pooler URI (statement cache is disabled in `database.py` for pgbouncer compatibility). |
| `ASSISTANT_DATABASE_URL` | same DB as user `vocalmind_readonly` | Used only to execute assistant SQL; see [SECURITY.md](SECURITY.md) |
| `SEED_DEMO_DATA` | `True` | Seeds NexaLink and Meridian on every boot. Set `false` for shared or production DBs. |
| `SEED_EVALUATION_SESSIONS` | `False` | Read by `backend/scripts/seed_nexalink.py` and `seed_meridian.py` |

## Inference routing

Where each model runs: [SYSTEM_OVERVIEW.md](../architecture/SYSTEM_OVERVIEW.md#where-models-run). Kaggle server API and setup: [services/kaggle/README.md](../../services/kaggle/README.md).

| Variable | Default | Notes |
|---|---|---|
| `IS_LOCAL` | `True` | `false`: speech and text emotion go to the Kaggle server (`backend/app/core/kaggle_client.py`, `emotion_fusion.py`). `true`: the `local-ml` containers `vad`/`emotion`/`whisperx`. |
| `RAG_MODELS_HOST` | `local` | `kaggle`: query embeddings via Kaggle `/embed` (`resolve_embedding_base_url`). `local`: Ollama (`OLLAMA_BASE_URL`) or Ollama Cloud. Re-ingest after switching. |
| `KAGGLE_SERVER_URL` (legacy name `KAGGLE_NGROK_URL`) | empty | ngrok URL of the Kaggle notebook. Required when `IS_LOCAL=false` or `RAG_MODELS_HOST=kaggle`. |
| `VAD_API_URL` / `EMOTION_API_URL` / `WHISPERX_API_URL` | `localhost:8002` / `:8001` / `:8003` | Used when `IS_LOCAL=true`; compose points them at the service names |

All Kaggle requests carry `ngrok-skip-browser-warning: true`. `POST /api/v1/internal/set-kaggle-url` (called by the notebook on start) swaps `KAGGLE_SERVER_URL` and forces `IS_LOCAL=false` at runtime, in memory only; it does not reach the `ingestion` container, which reads `KAGGLE_SERVER_URL` from its environment.

## Audio storage

| Variable | Default | Notes |
|---|---|---|
| `AUDIO_STORAGE_BACKEND` | `local` | `supabase` uploads new audio to Supabase Storage (requires the Supabase vars below) |
| `LOCAL_AUDIO_STORAGE_DIR` | `storage/uploads` | Upload destination when `local` |
| `EXTRA_AUDIO_ROOTS` | empty | Extra roots for local audio resolution (`;` or OS path separator) |
| `SUPABASE_URL` / `SUPABASE_SERVICE_KEY` / `SUPABASE_AUDIO_BUCKET` | empty / empty / `recordings` | The backend reads `SUPABASE_SERVICE_KEY` (not `..._ROLE_KEY`) |
| `AUDIO_FOLDER_WATCHER_ENABLED` | `False` | Auto-ingest from `storage/audio/<org_slug>/`; see [AUDIO_AUTO_INGEST.md](../operations/AUDIO_AUTO_INGEST.md) |

## LLM (trigger chains, RAG judge, assistant)

The supported providers are **`ollama_cloud`** (free Ollama Cloud models; the compose default) and **`groq`**.

| Variable | Default | Notes |
|---|---|---|
| `LLM_PROVIDER` | `groq` | `ollama_cloud` or `groq` |
| `OLLAMA_CLOUD_API_KEY` (alias `OLLAMA_API_KEY`) | empty | Required for `ollama_cloud` |
| `OLLAMA_CLOUD_BASE_URL` | `https://ollama.com/v1` | OpenAI-compatible endpoint |
| `OLLAMA_CLOUD_HEAVY_MODEL` | `kimi-k2.6:cloud` | Heavy stages: emotion_shift, process_adherence, text_to_sql |
| `OLLAMA_CLOUD_FAST_MODEL` | `ministral-3:8b` | Fast stages: nli_policy, rag_judge, fast_classification, rag_synthesis |
| `OLLAMA_MODEL_<STAGE>` | empty | Per-stage override, used only with `ollama_cloud` |
| `GROQ_API_KEY`, `LLM_MODEL` | empty, `llama-3.3-70b-versatile` | For `groq`; one shared model for all stages |
| `LLM_TEMPERATURE` / `LLM_MAX_TOKENS` / `LLM_REQUEST_TIMEOUT_SECONDS` | `0.0` / `1024` / `60` | |
| `ASSISTANT_LLM_PROVIDER` | `auto` | `ollama_cloud`, `groq`, `ollama` (local `ASSISTANT_OLLAMA_MODEL`, default `qwen2.5:7b`), or `auto` (Groq, then Ollama Cloud) |

`OLLAMA_MODEL_EMOTION_SHIFT` / `_PROCESS_ADHERENCE` / `_NLI_POLICY` also accept their legacy names `OLLAMA_EMOTION_SHIFT_MODEL` / `OLLAMA_PROCESS_ADHERENCE_MODEL` / `OLLAMA_NLI_MODEL`.

## RAG

| Variable | Default | Notes |
|---|---|---|
| `QDRANT_URL` | `http://localhost:6333` | |
| `QDRANT_COLLECTION_PARENTS` / `QDRANT_COLLECTION_SOP_PARENTS` | `vocalmind_parents` / `vocalmind_sop_parents` | The backend reads only these two collections |
| `OLLAMA_BASE_URL` / `EMBEDDING_MODEL` | `http://localhost:11434` / `snowflake-arctic-embed2` | Query embeddings when `RAG_MODELS_HOST=local` |
| `OLLAMA_CLOUD_EMBED_ENABLED` | `False` | Embed through Ollama Cloud instead |
| `SOP_RETRIEVAL_TOP_K` | `4` | |
| `RAG_SUPPORTED_THRESHOLD` / `RAG_NEUTRAL_THRESHOLD` | `0.82` / `0.55` | Used by `routes/rag.py` |
| `POLICY_DOCS_ROOT`, `SOP_DOCS_ROOT`, `KNOWLEDGE_DOCS_ROOT`, `SOP_PARSED_DOCS_ROOT` | `<cwd>/storage/docs` | Knowledge file roots |

## Service-only variables (not in backend `Settings`)

| Service | Variables (default) |
|---|---|
| whisperx (`services/whisperx/app.py`) | `HF_TOKEN`, `WHISPER_MODEL_SIZE` (`large-v2`; compose `tiny`, GPU overlay `large-v3`), `WHISPER_BATCH_SIZE` (8), `WHISPER_COMPUTE_TYPE` (`float16` on CUDA, `int8` on CPU), `STRICT_DIARIZATION` (false), `CHANNEL_DIARIZATION_ENABLED` (true), `CHANNEL_DIARIZATION_MAX_CORR` (0.92), `AGENT_CHANNEL`, `DIARIZATION_NUM_SPEAKERS` (2), `DIARIZATION_MIN_SPEAKERS` / `DIARIZATION_MAX_SPEAKERS` |
| emotion (`services/emotion/app.py`) | `EMOTION_MAX_AUDIO_SECONDS` (30) |
| ingestion (`services/rag/config.py`) | `RAG_MODELS_HOST` / `KAGGLE_SERVER_URL` (Settings default `local`), `QDRANT_COLLECTION_CHILDREN` (`vocalmind_children`), `EMBEDDING_DIMENSION` (1024), `DOCS_DIR` / `POLICY_DOCS_DIR` / `KNOWLEDGE_DOCS_DIR` / `PARSED_*_DIR`, `RERANK_ENABLED` / `RERANK_MODEL`, `HYDE_ENABLED`, plus the same `LLM_PROVIDER` / `OLLAMA_*` names as the backend |
