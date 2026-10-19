# Deployment

Two environments:

- **Local:** the full Docker Compose stack, or the backend run natively against compose infrastructure.
- **Production:** only the backend is deployed by this repo. It runs on an Azure VM, uses Supabase Postgres and Supabase Storage, and is deployed by GitHub Actions.

Settings and their precedence: [CONFIGURATION.md](../backend/CONFIGURATION.md). Tests and CI: [TESTING.md](../backend/TESTING.md).

## Local

Models run on the Kaggle GPU server by default; start its notebook first ([services/kaggle/README.md](../../services/kaggle/README.md)) and set `KAGGLE_SERVER_URL` in the root `.env` (or let the notebook register itself through `BACKEND_URL`).

| Command | What it starts |
|---|---|
| `make build` then `make up` | Default stack: `db`, `backend`, `frontend`, `qdrant`, `ingestion` (`IS_LOCAL=false`, `RAG_MODELS_HOST=kaggle`). `build-retry` exists for Windows Docker flakiness. |
| `make up-local` | Default stack plus profile `local-ml` (`ollama`, `vad`, `emotion`, `whisperx`) on CPU, with `IS_LOCAL=true RAG_MODELS_HOST=local RAG_LOCAL_MODELS=true` |
| `make up-gpu` | Same as `up-local` plus the `docker-compose.gpu.yml` overlay for whisperx/emotion |
| `make support-up` | `db qdrant` only; run the backend and frontend natively (`make be-dev`, `make fe-dev`) with models on Kaggle |
| `make support-up-local` (`support-up-gpu`) | `db ollama qdrant vad emotion whisperx`; for native dev with local models (`IS_LOCAL=true`, `RAG_MODELS_HOST=local`) |
| `make ollama-pull-embed` | Pulls `snowflake-arctic-embed2` into the compose Ollama (needed once per volume, local models only) |
| `make down` / `make logs` | Include the `local-ml` profile |

Local models in the `ingestion` container need the image built with `RAG_LOCAL_MODELS=true` (Docling + cross-encoder). `make up-local` sets the variable but does not pass `--build`; rebuild once with `RAG_LOCAL_MODELS=true docker compose build ingestion`. After switching `RAG_MODELS_HOST`, re-ingest (`cd services/rag && uv run python main.py --ingest --force`) because the two hosts use different embedding models.

Host ports:

| Service | Port |
|---|---|
| frontend | 3000 |
| backend | 8000 (`/docs` for OpenAPI) |
| qdrant | 6333 / 6334 |
| Postgres | **5434 on the host → 5432 in the container** (`db:5432` from other containers) |
| emotion (`local-ml`) | 8001 → 8000 |
| vad (`local-ml`) | 8002 |
| whisperx (`local-ml`) | 8003 → 8000 |
| ollama (`local-ml`) | 11434 |

## Production backend deploy (`.github/workflows/deploy-backend.yml`)

**Trigger:**

- A `workflow_run` of **"Backend CI"** (`.github/workflows/backend.yml`) on `main` that concludes `success`, or a manual `workflow_dispatch`.
- Backend CI only runs for pushes that touch `backend/**` or its own workflow file. So every merge to `main` that changes the backend and passes ruff + pytest + the quality benchmarks is deployed automatically.
- The concurrency group `deploy-backend` cancels a deploy that is still running.

**Steps** (`appleboy/ssh-action` with password auth; secrets `AZURE_VM_HOST`, `AZURE_VM_USER`, `AZURE_VM_PASSWORD`):

1. `cd /opt/vocalmind && git fetch origin main && git checkout main && git reset --hard <CI head SHA>`. This discards any edits to tracked files on the VM; the untracked `.env` files survive.
2. An inline Python script rewrites these keys in `backend/.env` from GitHub secrets and keeps every other line:
   - `AUDIO_STORAGE_BACKEND=supabase`
   - `SUPABASE_URL`
   - `SUPABASE_SERVICE_KEY`
   - `SUPABASE_AUDIO_BUCKET` (default `recordings`)
3. `docker compose up -d --build backend`.

**What the workflow does not do:**

- It never runs Alembic, the `infra/db` SQL files, or a frontend deploy.
- `up backend` also starts its `depends_on` service (`db`) but not `qdrant` or `ingestion`.
- Compose defaults to `IS_LOCAL=false` and `RAG_MODELS_HOST=kaggle`, so inference needs a running Kaggle notebook and `KAGGLE_SERVER_URL` in the VM's root `.env` (or the notebook's `BACKEND_URL` registration, which is in memory only and lost on every backend restart).

**VM prerequisites** (kept in the untracked `/opt/vocalmind/.env` and `/opt/vocalmind/backend/.env`):

- `DATABASE_URL`: the Supabase pooler URI.
- `ASSISTANT_DATABASE_URL`: a read-only role.
- `SECRET_KEY`: non-placeholder.
- `SEED_DEMO_DATA=false`.
- LLM keys (`OLLAMA_API_KEY`, or `GROQ_API_KEY` with `LLM_PROVIDER=groq`).
- `KAGGLE_SERVER_URL` (root `.env`).

**Rollback:** the workflow always checks out `main`, so revert the commit on `main` and let CI redeploy it. A manual dispatch only redeploys the current head.

**Frontend:** `frontend/vercel.json` (SPA rewrite) exists, but no workflow in this repo deploys the frontend. A hosted build must set `VITE_API_URL` to the backend's public origin. If unset it falls back to `http://localhost:8000`; an empty string means same-origin (`frontend/src/app/services/api.ts`).

## Production database (Supabase Postgres)

- `DATABASE_URL` is the Supabase **connection-pooler** URI: `postgresql+asyncpg://postgres.<ref>:<password>@<pooler-host>:6543/postgres`. `backend/app/core/database.py` disables asyncpg statement caches, which pgbouncer pooling requires.

### Bootstrapping a new Supabase database

Read the "Schema sources" section of [DATABASE_SCHEMA.md](../architecture/DATABASE_SCHEMA.md) first: `01_schema.sql` lags the models.

1. Apply `infra/db/01_schema.sql`, either through psql or with `DATABASE_URL` exported and `make migrate` (which also sends `NOTIFY pgrst`). Apply `infra/db/05_interactions_org_audio_unique.sql` as well; `03` and `06` are already folded into `01`.
2. Apply `infra/db/04_assistant_readonly_role.sql`, change the role's dev password, and point `ASSISTANT_DATABASE_URL` at it.
3. Before the backend's first boot, from `backend/`: `uv run alembic stamp 0002_notif_and_dispute` and then `uv run alembic upgrade head`.
   - Stamp `0002` because `01_schema.sql` already contains the 0002 objects, and 0002's `create_table("notifications")` is not guarded.
   - Run it before the first boot, because `create_all` at startup would create `assistant_sessions` and `knowledge_versions` and break the later migrations.
4. Boot once with `SEED_DEMO_DATA=true` to create NexaLink and Meridian (`backend/scripts/seed_nexalink.py`, `seed_meridian.py`), then set it to `false` and redeploy.

### Existing Supabase database with legacy demo orgs

1. Back it up (Supabase dashboard → Database → Backups).
2. Run `tools/sync_remote_supabase.sql` in the Supabase SQL editor. It deletes the NileTech and CairoConnect organizations (by id or slug) and every row that cascades from them. The schema is left untouched, and the script is idempotent.
3. Bring the schema up to date with Alembic (`stamp` the revision that matches the DB, then `upgrade head`).
4. Boot once with `SEED_DEMO_DATA=true`, then set it to `false`.

## Runtime checks

- `GET /health`: DB connectivity (503 when unreachable).
- `GET /health/circuit-breakers`: LLM breaker state.
- `GET /metrics`: Prometheus.

All three are unauthenticated. Audio drop-folder ingestion is optional and off by default in `config.py`; see [AUDIO_AUTO_INGEST.md](AUDIO_AUTO_INGEST.md).
