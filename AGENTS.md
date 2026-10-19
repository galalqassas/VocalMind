# VocalMind — Agent Guide

Call-center QA platform: **upload call audio → transcribe + diarize → emotion → LLM compliance reasoning → scores → manager/agent dashboards.** Multi-tenant: every `Organization` has manager and agent `User`s, and all data is org-scoped.

## Rules

1. Keep code concise and match the surrounding style.
2. Make minimal changes, but update every affected component, including the docs in this file.
3. Verify before finishing by running the relevant tests, lint and type checks (see [Commands](#commands)).
4. **Merging to `main` deploys the backend to production** (see [Production](#production)). Work on a branch.

## Architecture

```
frontend :3000 (Vite proxy /api) ─▶ backend :8000 (FastAPI, no ML libs) ─▶ Postgres (host :5434 → :5432)
                                        │
                                        ├─▶ Kaggle GPU server (services/kaggle, default) ── all models:
                                        │     speech, emotion, text emotion, embeddings, rerank, PDF parsing
                                        │   or local containers (`local-ml` profile): whisperx :8003,
                                        │     emotion :8001, vad :8002, ollama :11434
                                        ├─▶ Qdrant :6333 ◀─ ingestion (services/rag, watches storage/docs)
                                        └─▶ LLM: Ollama Cloud (default) or Groq
```

**Where models run** is chosen by two switches:
- `IS_LOCAL`: speech and emotion. `false` means Kaggle (the compose default); `true` means the local containers.
- `RAG_MODELS_HOST`: embeddings, Docling and rerank. The values are `kaggle` (default) and `local`.

The Kaggle server's API contract and setup steps are in [services/kaggle/README.md](services/kaggle/README.md). It runs from `services/kaggle/vocalmind_gpu.ipynb` and reads its tokens from Kaggle Secrets. When it starts, it registers itself through `POST /api/v1/internal/set-kaggle-url`; that route has no auth by design.

`docker-compose.yml` services:
- **Default:** db, backend, frontend, qdrant, ingestion.
- **`local-ml` profile:** ollama, vad, emotion, whisperx.

Overlays:
- `docker-compose.gpu.yml`: GPU for the local containers.
- `docker-compose.native.yml`: the frontend container proxying to a backend running on the host.

VAD is only reachable through `/api/v1/vad/*`; the pipeline doesn't call it.

## Processing pipeline (the core flow)

1. Audio arrives through one of three paths:
   - `POST /api/v1/interactions` (upload)
   - `POST /api/v1/interactions/from-storage`
   - the folder watcher (`storage/audio/<org_slug>/CALL_<NN>_<agent>_<scenario>.wav`)
2. That creates an `Interaction` (status `pending`) and 6 `ProcessingJob`s: diarization → stt → emotion → reasoning → scoring → rag_eval.
3. The worker in `backend/app/core/interaction_processing.py` runs everything else:
   1. Fetches audio (local disk or Supabase Storage, `AUDIO_STORAGE_BACKEND`).
   2. Runs inference through `full_client` (`api/routes/full/service.py`): Kaggle `/full`, or locally WhisperX `/transcribe` followed by the emotion service with `segments`. Both give text, speaker cluster and **per-segment** emotion2vec emotion.
   3. Normalizes the response (`inference_contracts.py`). A segment without an emotion stays `unknown`; nothing is guessed.
   4. Checks that the transcript isn't gibberish (an LLM call, `chains.is_gibberish`).
   5. Assigns speaker roles (`assign_speaker_roles`), using only the trained **LR+TF-IDF model** (`core/model.pkl`, `core/vectorizer.pkl`):
      - Stereo channel labels are kept as they are.
      - With 2 or more clusters, the agent is the cluster with the highest mean P(agent).
      - Otherwise each segment is classified separately.
   6. Persists Transcript → Utterances → EmotionEvents.
   7. Evaluates LLM triggers (`backend/app/llm_trigger/service.py`, ~2.2k lines), making 4 LLM calls per interaction:
      - Topic classification runs once, on the fast model (`build_topic_classification_chain`).
      - Then three chains run over rolling 8-turn windows (stride 4): emotion shift, process adherence (SOP steps from `RESOLUTION_GRAPHS` in `prompt_constants.py`) and NLI policy check.
      - Resolution, efficiency, missing steps and evidence quotes all come from the LLM.
      - SOP/policy evidence comes from org files in `storage/docs/` and Qdrant (order is in the [trigger guide](docs/llm_trigger/LLM_TRIGGER_FEATURE_GUIDE.md)).
      - The result is cached in `interaction_llm_trigger_cache`.
   8. Writes policy violations (`policy_violation_mapping.py`) and scores (`llm_trigger/scoring.py`, `core/score_utils.py`).

4. `GET /api/v1/interactions/{id}` serves the result. Reprocess with `POST .../{id}/reprocess?priority=true`.

**Failures are never guessed.** There are no keyword fallbacks or default scores. If a model or the LLM is unavailable:
- That `ProcessingJob` is marked `failed` (`StageFailed`, `LLMUnavailableError`, `TextEmotionUnavailable`, `SpeakerRoleModelUnavailable`).
- Later stages are marked "Not run" and no score row is written.
- The interaction ends `failed`; reprocess to retry.
- `POST /llm-trigger/interaction/{id}/run` returns 503.

**Emotion fusion** (`emotion_fusion.fuse_emotion_signals`): acoustic ×0.55 + text ×0.45, +0.08 when they agree, −0.12 when they disagree. Text emotion comes from `/predict_text` (DistilRoBERTa). Fusion is computed on read (`emotionComparison` and the per-utterance fused fields in the interaction detail) and is not persisted.

**Explainability:** every trigger verdict carries `TriggerAttribution` + `ClaimProvenance`, linking transcript spans to the retrieved policy/SOP chunk (`llm_trigger/schemas.py`).

**Manager assistant** (`api/routes/assistant.py`): natural language → SQL → read-only execution (`ASSISTANT_DATABASE_URL` read-only role) → answer. With `ASSISTANT_LLM_PROVIDER=auto` it tries Groq → Ollama Cloud; compose sets `ollama_cloud`.

**RAG** (`services/rag/`): Docling → parent/child chunks → embeddings → Qdrant. Docling and the embeddings run on Kaggle or locally, per `RAG_MODELS_HOST`; after switching, re-ingest with `uv run python main.py --ingest --force`, because the embedding models differ. It writes three collections:

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
| `backend/app/api/main.py` | Router registry. Prefixes: auth, emotion, interactions, dashboard, knowledge, agents, assistant, users, llm-trigger, rag, vad, internal, notifications, reviews, feedback, policy-compliance |
| `backend/app/api/deps.py` | DI: DB session, current user |
| `backend/app/core/` | Config, pipeline worker, fusion, audio resolver/watcher, Kaggle client, knowledge versioning, rate limit, circuit breaker |
| `backend/app/llm_trigger/` | Trigger engine: `service.py`, `chains.py`, `prompts.py`, `prompt_constants.py` (incl. `INJECTION_GUARD`), `retrieval.py`, `schemas.py`, `scoring.py` |
| `backend/app/models/` | SQLModel tables + enums |
| `backend/alembic/versions/` | 5 migrations |
| `backend/scripts/` | `seed_nexalink.py`, `seed_meridian.py` (run at startup), `reset_local_db.py`, misc ops |
| `backend/tests/` | 38 pytest files (SQLite in-memory) |
| `frontend/src/app/` | React 18 SPA: `routes.tsx`, `services/api.ts`, `contexts/`, `components/{manager,agent,layouts,ui}` |
| `services/kaggle/` | Kaggle GPU server (`server.py`), notebook, API contract |
| `services/{vad,whisperx,emotion}/app.py` | Local inference containers (`local-ml` profile) |
| `services/rag/` | Ingestion + query engine + evaluators + RAGAS |
| `infra/db/` | SQL mounted into Postgres initdb: `01_schema.sql`, `03`–`06` incremental (`04` = assistant read-only role) |
| `infra/scripts/` | `eval/` (quality gates), `migrate.py`, `e2e_local_audio.py`, `ingest_audio_folder.py`, `build_session_export.py` |
| `infra/benchmarks/` | Gold labels (`expected/`), `fixtures/`, `schema/thresholds.json` |
| `storage/` | Bind-mounted `audio/<org>/`, `docs/<org>/` (RAG sources), `uploads/` |
| `tools/` | Pipeline-vs-ground-truth eval harness, `sync_remote_supabase.sql` |
| `research/` | Notebooks only; not used at runtime |

## Commands

```bash
cp .env.example .env && cp backend/.env.example backend/.env   # fill OLLAMA_API_KEY, KAGGLE_SERVER_URL
make up                 # app stack; models on Kaggle (start services/kaggle notebook first)
make up-local           # + local model containers (CPU); make up-gpu for NVIDIA; then make ollama-pull-embed
make support-up         # db + qdrant only, then: make be-dev / make fe-dev  (support-up-local adds models)
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

- `IS_LOCAL` / `RAG_MODELS_HOST` / `KAGGLE_SERVER_URL`: where the models run (see [Architecture](#architecture)).
- `LLM_PROVIDER`: `ollama_cloud` (compose default; heavy `kimi-k2.6:cloud`, fast `ministral-3:8b`) or `groq`.
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
- **Tests use SQLite.** JSONB and Postgres-only indexes are not exercised.
- **Dashboard cache TTL is 5 min**, so data looks stale right after reprocessing.
- **Emotion windows** are converted to mono 16 kHz, are at least 0.8 s long, and are capped at 30 s (`EMOTION_MAX_AUDIO_SECONDS`).
- **Postgres from the host is `localhost:5434`**; inside compose it is `db:5432`. `backend/.env` overrides the root `.env` in the backend container, so its `DATABASE_URL` must use `db:5432` (or Supabase) when the backend runs in Docker.
- **For ngrok/public demos, tunnel port 3000** (the frontend proxies `/api`), not 8000.
- **Offline UI demo:** `VITE_USE_OFFLINE_DEMO=true` serves bundled NexaLink data (`frontend/src/app/data/`), with no backend needed.
- **Committed artifacts:** `backend/uv.lock`, `model.pkl` and `vectorizer.pkl` are committed. Run `uv sync` after pulling.
- **On Windows**, use `make build-retry` for transient Docker errors.

## Known issues (tracked cleanup)

- **Security:**
  - Public routes:
    - inference passthroughs `/vad/*` (including `analyze-local`, which reads server file paths) and `/emotion/process`;
    - `/metrics` and `/health/circuit-breakers`.
  - Knowledge CRUD only requires login, not the manager role.
  - The auth rate limit described in `core/rate_limit.py` is never applied.

- **Unmeasured models:** the Kaggle server and the LR-only speaker roles haven't been run against the ground-truth calls yet (`tools/evaluate_pipeline.py`).
- **Missing metrics:** `Transcript.overall_confidence`, silence and response time are `None` (TODO), because they have no real source yet.
- **Dead code:** about 30 unused `components/ui/*`.
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
