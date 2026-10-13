# Deployment

Two environments:

- **Local:** the full Docker Compose stack, or the backend run natively against compose infrastructure.
- **Production:** only the backend is deployed by this repo. It runs on an Azure VM, uses Supabase Postgres and Supabase Storage, and is deployed by GitHub Actions.

Settings and their precedence: [CONFIGURATION.md](../backend/CONFIGURATION.md). Tests and CI: [TESTING.md](../backend/TESTING.md).

## Local

| Command | What it starts |
|---|---|
| `make build` then `make up` | All 9 compose services, CPU (`build-retry` exists for Windows Docker flakiness) |
| `make up-gpu` | Same, plus the `docker-compose.gpu.yml` overlay for whisperx/emotion |
| `make support-up` (`support-up-gpu`) | `db ollama qdrant vad emotion whisperx` only; run the backend and frontend natively (`make be-dev`, `make fe-dev`) |
| `make ollama-pull-embed` | Pulls `snowflake-arctic-embed2` into the compose Ollama (needed once per volume) |

Host ports:

| Service | Port |
|---|---|
| frontend | 3000 |
| backend | 8000 (`/docs` for OpenAPI) |
| emotion | 8001 → 8000 |
| vad | 8002 |
| whisperx | 8003 → 8000 |
| qdrant | 6333 / 6334 |
| ollama | 11434 |
| Postgres | **5434 on the host → 5432 in the container** (`db:5432` from other containers) |

Native dev without the speech containers: set `IS_LOCAL=false` with a running Kaggle notebook (`KAGGLE_SERVER_URL`; see `infra/fixtures/kaggle/README.md`).

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
- `up backend` also starts its `depends_on` services (`db`, `ollama`) but not `vad`/`emotion`/`whisperx`/`qdrant`.
- Compose hardcodes `IS_LOCAL=true` and in-network service URLs. Speech inference on the VM therefore needs those containers running, or a `POST /api/v1/internal/set-kaggle-url` after every restart (that switch is in memory only).

**VM prerequisites** (kept in the untracked `/opt/vocalmind/.env` and `/opt/vocalmind/backend/.env`):

- `DATABASE_URL`: the Supabase pooler URI.
- `ASSISTANT_DATABASE_URL`: a read-only role.
- `SECRET_KEY`: non-placeholder.
- `SEED_DEMO_DATA=false`.
- LLM keys (`OLLAMA_API_KEY`, or `GROQ_API_KEY` with `LLM_PROVIDER=groq`).
- `HF_TOKEN`.

**Rollback:** the workflow always checks out `main`, so revert the commit on `main` and let CI redeploy it. A manual dispatch only redeploys the current head.

**Frontend:** `frontend/vercel.json` (SPA rewrite) exists, but no workflow in this repo deploys the frontend. A hosted build must set `VITE_API_URL` to the backend's public origin. If unset it falls back to `http://localhost:8000`; an empty string means same-origin (`frontend/src/app/services/api.ts`).

## Production database (Supabase Postgres)

- `DATABASE_URL` is the Supabase **connection-pooler** URI: `postgresql+asyncpg://postgres.<ref>:<password>@<pooler-host>:6543/postgres`. `backend/app/core/database.py` disables asyncpg statement caches, which pgbouncer pooling requires.
- `SUPABASE_DB_URL` is used only by `backend/scripts/verify_supabase_schema.py`, which lists the remote tables and the `users`/`policy_compliance` columns.

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
3. Bring the schema up to date with Alembic (`stamp` the revision that matches the DB, check with `verify_supabase_schema.py`, then `upgrade head`).
4. Boot once with `SEED_DEMO_DATA=true`, then set it to `false`.

**Do not** run `make seed` with production credentials. It runs `infra/scripts/seed/seed_database.py`, a legacy seeder that writes fake data straight to the Supabase project named in `backend/.env`.

## Runtime checks

- `GET /health`: DB connectivity (503 when unreachable).
- `GET /health/circuit-breakers`: LLM breaker state.
- `GET /metrics`: Prometheus.

All three are unauthenticated. Audio drop-folder ingestion is optional and off by default in `config.py`; see [AUDIO_AUTO_INGEST.md](AUDIO_AUTO_INGEST.md).
