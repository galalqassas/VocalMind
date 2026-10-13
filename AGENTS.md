# VocalMind — Agent Guide

Call-center QA platform: **upload call audio → transcribe + diarize → emotion → LLM compliance reasoning → scores → manager/agent dashboards.** Multi-tenant: every `Organization` has manager and agent `User`s, and all data is org-scoped.

## Rules

1. Keep code concise and match the surrounding style.
2. Make minimal changes, but update every affected component, including the docs in this file.
3. Verify before finishing by running the relevant tests, lint and type checks (see [Commands](#commands)).
4. **Merging to `main` deploys the backend to production** (see [Production](#production)). Work on a branch.

## Architecture

```
frontend :3000 (Vite proxy /api) ─▶ backend :8000 (FastAPI) ─▶ Postgres (host :5434 → :5432)
                                        │
            IS_LOCAL=true ──────────────┼──────────── IS_LOCAL=false
   whisperx :8003 · emotion :8001 · (vad :8002)      Kaggle GPU notebook via ngrok
                                        │             (backend/app/core/kaggle_client.py)
                                        ├─▶ Qdrant :6333 ◀─ ingestion (services/rag, watches storage/docs)
                                        ├─▶ Ollama :11434 (embeddings: snowflake-arctic-embed2)
                                        └─▶ LLM: Ollama Cloud (default) or Groq
```

`docker-compose.yml` defines 9 services: db, backend, frontend, ollama, qdrant, ingestion, vad, emotion and whisperx. VAD is only reachable through `/api/v1/vad/*`; the processing pipeline doesn't call it. There are two overlays:
- `docker-compose.gpu.yml`: GPU for whisperx/emotion.
- `docker-compose.native.yml`: frontend-only container proxying to a backend running on the host.

## Processing pipeline (the core flow)

1. Audio arrives through one of three paths:
   - `POST /api/v1/interactions` (upload)
   - `POST /api/v1/interactions/from-storage`
   - the folder watcher (`storage/audio/<org_slug>/CALL_<NN>_<agent>_<scenario>.wav`)
2. That creates an `Interaction` (status `pending`) and 6 `ProcessingJob`s: diarization → stt → emotion → reasoning → scoring → rag_eval.
3. The worker in `backend/app/core/interaction_processing.py` runs everything else:
   1. Fetches audio (local disk or Supabase Storage, `AUDIO_STORAGE_BACKEND`).
   2. Runs inference through `full_client` (`api/routes/full/service.py`). With `IS_LOCAL=false` this is the Kaggle `/full` endpoint. Locally it is:
      - WhisperX `/transcribe` (ASR + pyannote, or a channel split for stereo);
      - one **clip-level** emotion2vec call (the first 30 s).
      - The VAD service is **not** used by this pipeline.
   3. Normalizes the response (`inference_contracts.py`). Locally, per-segment emotion comes from the keyword text heuristic (`build_deterministic_emotion_analysis`); the clip label is used only when the text gives none.
   4. Assigns speaker roles: **hand-weighted phrase scores plus an LR+TF-IDF model** (`model.pkl`, `vectorizer.pkl`), where the LR adds at most 3 points. Single-cluster diarization falls back to per-segment labeling.
   5. Persists Transcript → Utterances → EmotionEvents.
   6. Evaluates LLM triggers (`backend/app/llm_trigger/service.py`, ~3.4k lines):
      - Rolling 8-turn windows, stride 4.
      - Three LangChain chains: emotion shift, process adherence (SOP steps), and NLI policy check.
      - SOP/policy evidence comes from org files in `storage/docs/` and Qdrant (order is in the [trigger guide](docs/llm_trigger/LLM_TRIGGER_FEATURE_GUIDE.md)).
      - The result is cached in `interaction_llm_trigger_cache`.
   7. Writes policy violations (`policy_violation_mapping.py`) and scores (`llm_trigger/scoring.py`, `core/score_utils.py`).

**Emotion fusion** (`emotion_fusion.fuse_emotion_signals`): acoustic ×0.55 + text ×0.45, +0.08 when they agree, −0.12 when they disagree. It is computed on read (the emotion-comparison endpoint and the emotion-shift trigger) and is not persisted.
4. `GET /api/v1/interactions/{id}` serves the result. Reprocess with `POST .../{id}/reprocess?priority=true`.

**Explainability:** every trigger verdict carries `TriggerAttribution` + `ClaimProvenance`, linking transcript spans to the retrieved policy/SOP chunk (`llm_trigger/schemas.py`).

**Manager assistant** (`api/routes/assistant.py`): natural language → SQL → read-only execution (`ASSISTANT_DATABASE_URL` read-only role) → answer. With `ASSISTANT_LLM_PROVIDER=auto` it tries Gemini → Groq → Ollama Cloud; compose sets `ollama_cloud`.

**RAG** (`services/rag/`): Docling → parent/child chunks → Ollama embeddings → Qdrant. It writes three collections:

| Collection | Contents | Used for |
|---|---|---|
| `vocalmind_parents` | Policy sections | NLI/compliance |
| `vocalmind_children` | 400-char policy chunks (80 overlap) | Q&A |
| `vocalmind_sop_parents` | SOP + KB sections | Process adherence |

Point IDs are content hashes, so re-ingesting is idempotent.

## Repo map

| Path | What |
|---|---|
| `backend/app/main.py` | Lifespan, in order: validate settings → `create_all` → seed demo orgs → start worker → start audio watcher |
| `backend/app/api/main.py` | Router registry. Prefixes: auth, emotion, interactions, dashboard, knowledge, agents, assistant, users, llm-trigger, rag, diarization, transcription, vad, full, internal, notifications, reviews, feedback, policy-compliance |
| `backend/app/api/deps.py` | DI: DB session, current user |
| `backend/app/core/` | Config, pipeline worker, fusion, audio resolver/watcher, Kaggle client, knowledge versioning, rate limit, circuit breaker |
| `backend/app/llm_trigger/` | Trigger engine: `service.py`, `chains.py`, `prompts.py`, `prompt_constants.py` (incl. `INJECTION_GUARD`), `retrieval.py`, `schemas.py`, `scoring.py` |
| `backend/app/models/` | SQLModel tables + enums |
| `backend/alembic/versions/` | 5 migrations |
| `backend/scripts/` | `seed_nexalink.py`, `seed_meridian.py` (run at startup), `reset_local_db.py`, misc ops |
| `backend/tests/` | 38 pytest files (SQLite in-memory) |
| `frontend/src/app/` | React 18 SPA: `routes.tsx`, `services/api.ts`, `contexts/`, `components/{manager,agent,layouts,ui}` |
| `services/{vad,whisperx,emotion}/app.py` | Inference microservices |
| `services/rag/` | Ingestion + query engine + evaluators + RAGAS |
| `infra/db/` | SQL mounted into Postgres initdb: `01_schema.sql`, `03`–`06` incremental (`04` = assistant read-only role), legacy seeds `02_seed.sql` (NileTech) + `seed_benchmark_data.sql` |
| `infra/scripts/` | `eval/` (quality gates), `seed/`, `migrate.py`, `e2e_local_audio.py`, `ingest_audio_folder.py`, `build_session_export.py` |
| `infra/benchmarks/` | Gold labels (`expected/`), `fixtures/`, `schema/thresholds.json` |
| `storage/` | Bind-mounted `audio/<org>/`, `docs/<org>/` (RAG sources), `uploads/` |
| `tools/` | Pipeline-vs-ground-truth eval harness, `sync_remote_supabase.sql` |
| `research/` | Notebooks only; not used at runtime |

## Commands

```bash
cp .env.example .env && cp backend/.env.example backend/.env   # fill OLLAMA_API_KEY, HF_TOKEN, SECRET_KEY
make up                 # full stack (CPU); make up-gpu for NVIDIA
make ollama-pull-embed  # once, pulls the embedding model
make support-up         # infra + inference containers only, then: make be-dev / make fe-dev
make be-test be-lint    # pytest / ruff
make fe-lint            # tsc --noEmit;  cd frontend && pnpm run test  (vitest, 13 files)
make fe-test            # Cypress (14 specs) against build + preview, never the dev server
make rag-test rag-lint
make quality-eval-all   # component quality gates vs infra/benchmarks/expected (fails on regression)
make llm-trigger-test
```

Demo data: when `SEED_DEMO_DATA=true`, startup seeds **NexaLink** (`manager@nexalink.com`) and **Meridian** (`manager@meridian.com`), each with 5 agents (`agent.<name>@<org>.com`). The password is `password123`. UI: http://localhost:3000 · API docs: http://localhost:8000/docs

## Configuration

Source of truth: `backend/app/core/config.py`. Values are layered, and the later one wins: **config.py default → `backend/.env` → `docker-compose.yml` `environment:`**. Details are in [docs/backend/CONFIGURATION.md](docs/backend/CONFIGURATION.md).

- `IS_LOCAL`: `true` uses the Docker inference services; `false` uses the Kaggle notebook (`KAGGLE_SERVER_URL`). On startup the notebook calls `POST /internal/set-kaggle-url` (no auth, by design), which sets the URL and flips `IS_LOCAL=false` in memory.
  - `backend/.env.example` uses `false`, which is recommended for native dev because it avoids downloading the models.
  - Compose hardcodes `true`.
- `LLM_PROVIDER`: `ollama_cloud` (compose default; heavy `kimi-k2.6:cloud`, fast `ministral-3:8b`) or `groq`. Gemini code exists but is unused.
- `TEXT_EMOTION_PROVIDER`: `hf_transformers` (compose) or `rule_based` (config.py default, keyword-based).
- `AUDIO_STORAGE_BACKEND`: `local` or `supabase` (production). `AUDIO_FOLDER_WATCHER_ENABLED` defaults to false in config.py and true in `.env.example`.

## Production

`.github/workflows/deploy-backend.yml` runs after **Backend CI passes on `main`**. It SSHes to an Azure VM (`/opt/vocalmind`), `git reset --hard`s to the commit, sets `AUDIO_STORAGE_BACKEND=supabase` + `SUPABASE_*` in `backend/.env`, and runs `docker compose up -d --build backend`.
- The DB is Supabase Postgres via `DATABASE_URL`.
- Set `SEED_DEMO_DATA=false` there.
- Bootstrap steps: [docs/operations/DEPLOYMENT.md](docs/operations/DEPLOYMENT.md).

CI (`.github/workflows/`):
- `ci.yml`: Gitleaks.
- `backend.yml`: ruff → pytest → quality evals.
- `frontend.yml`: tsc → build → Cypress.
- `rag_ci.yml`: ruff → pytest.
- `quality-benchmarks.yml`: runs when benchmarks change, or manually.
- `deploy-backend.yml`: the deploy described above.

## Gotchas

- **Never remove `INJECTION_GUARD`**: it is appended to every trigger prompt (`llm_trigger/prompts.py`) and treats transcript/user text as untrusted.
- **Assistant SQL must stay read-only**: `_validate_sql_structure` in `assistant.py`, plus the read-only DB role.
- **Fusion weights (0.55/0.45) are tuned.** Re-run `make quality-eval-emotion` if you change them.
- **Schema has three sources that drift**:
  - `infra/db/01_schema.sql` (initdb and `make migrate`, which is *not* Alembic) lacks `assistant_sessions` and `knowledge_versions`, and columns such as `users.avatar_url`.
  - Startup `create_all` adds missing *tables* but never *columns*.
  - Alembic is not run by compose and isn't in the backend image.
  - Add every schema change to all three.
- **`make seed` is a legacy Supabase seeder** (`SUPABASE_SERVICE_KEY`) and writes to whatever Supabase it points at. Local demo data comes from startup seeding instead.
- **Tests use SQLite.** JSONB and Postgres-only indexes are not exercised.
- **Dashboard cache TTL is 5 min**, so data looks stale right after reprocessing.
- **Emotion service truncates audio** to 30 s mono 16 kHz (`EMOTION_MAX_AUDIO_SECONDS`).
- **Postgres from the host is `localhost:5434`**; inside compose it is `db:5432`. `backend/.env` overrides the root `.env` in the backend container, so its `DATABASE_URL` must use `db:5432` (or Supabase) when the backend runs in Docker.
- **For ngrok/public demos, tunnel port 3000** (the frontend proxies `/api`), not 8000.
- **Offline UI demo:** `VITE_USE_OFFLINE_DEMO=true` serves bundled NexaLink data (`frontend/src/app/data/`), with no backend needed.
- **Committed artifacts:** `backend/uv.lock`, `model.pkl` and `vectorizer.pkl` are committed. Run `uv sync` after pulling.
- **On Windows**, use `make build-retry` or `start-gpu.ps1`.

## Known issues (tracked cleanup)

- **Security:**
  - Public routes:
    - inference passthroughs (`/full/*`, including `analyze-local`, which reads server file paths);
    - `/vad/*` and `/transcription/*`;
    - the single-stage `/llm-trigger/*` routes;
    - `/metrics` and `/health/circuit-breakers`.
  - Knowledge CRUD only requires login, not the manager role.
  - The auth rate limit described in `core/rate_limit.py` is never applied.

- `RESOLUTION_GRAPHS` is defined in both `llm_trigger/service.py` and `prompt_constants.py`. The prompt's step catalog lacks `account_signers`, `aml_review`, `retention` and `wire_transfer`.
- **"Dual-emotion fusion" is mostly text vs. text in local mode.** Per-utterance labels come from keywords, and the acoustic model only gives one label per clip.
- Keyword heuristics override or outweigh models:
  - Speaker-role phrase weights outweigh the LR model.
  - `_is_resolved_heuristic` overrides the LLM's `is_resolved`.
  - The topic is chosen by keyword score, defaulting to `billing_issue`.
- Dead code: `core/feedback_export.py`, `deps.get_supabase`, `_detect_topic`/`_detect_cross_modal_dissonance` (tests only), about 30 unused `components/ui/*`.
- The offline-demo dataset (`processedSessionExport.ts`, 27k lines) is statically imported, so it is always bundled. Its generator `infra/scripts/build_session_export.py` imports a missing module (`diag_5call_probe`).
- `infra/scripts/eval/extract_pipeline_predictions.py` calls `/api/interactions` (missing `/v1`).

## Conventions

- **Python** (backend 3.12, services 3.11): Ruff, uv, async FastAPI, SQLModel, Pydantic schemas, `Depends()` DI, settings via `Settings(BaseSettings)`.
- **TypeScript**: pnpm, React 18 + Vite 6, Tailwind v4 + MUI, shadcn/Radix in `components/ui/`, react-router v7, React Context, `@/` alias.

## Docs

Index: [docs/README.md](docs/README.md). Start with:
- [Pipeline](docs/architecture/AUDIO_PROCESSING_PIPELINE.md)
- [LLM triggers](docs/llm_trigger/LLM_TRIGGER_FEATURE_GUIDE.md)
- [RAG](docs/rag/RAG_OVERVIEW.md)
- [API routes](docs/api/REST_API_REFERENCE.md)
- [Configuration](docs/backend/CONFIGURATION.md)
