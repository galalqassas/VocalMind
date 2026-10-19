# Database Schema

PostgreSQL 17 runs in Docker locally. Production uses Supabase Postgres (see [DEPLOYMENT.md](../operations/DEPLOYMENT.md)). Tests run on SQLite in-memory, so Postgres-only features (JSONB, partial indexes) are not exercised there. Every domain row is scoped by `organization_id`, either directly or through its parent `interaction`.

## Schema sources (three mechanisms, not in sync)

| Source | What it does | When it runs |
|---|---|---|
| `backend/app/models/*.py` (SQLModel) | Runtime source of truth for the ORM | Backend startup calls `create_db_and_tables()` (`backend/app/core/database.py`), i.e. `SQLModel.metadata.create_all`. It **creates missing tables only** and never adds or alters columns. |
| `infra/db/*.sql` | `docker-compose.yml` mounts `./infra/db` at `/docker-entrypoint-initdb.d` | Postgres runs the files alphabetically, **only when the `vocalmind_data` volume is empty**. Order: `01_schema.sql`, then `03`–`06` patches (assistant `result_rows`, `vocalmind_readonly` role, interaction audio-path unique constraint, `policy_compliance.degraded`). `make migrate` (`infra/scripts/migrate.py`) also applies `01_schema.sql` to `DATABASE_URL` via asyncpg. This is not Alembic, and it only works on an empty DB because the file starts with `DROP TYPE ... CASCADE` and plain `CREATE TABLE`. |
| `backend/alembic/versions/` (5 migrations) | Incremental changes | Manual only: `cd backend && uv run alembic upgrade head`. Nothing in compose, CI or deploy runs Alembic. The backend image does not include `alembic/`. See [backend/alembic/README.md](../../backend/alembic/README.md). |

Alembic chain: `0001_baseline` (empty marker) → `0002_notif_and_dispute` (notifications table and enum, `policy_compliance` dispute columns) → `0003_user_avatar` (`users.avatar_url`) → `f7ed8dd3ea71` (`assistant_sessions` and `assistant_queries.session_id`) → `a1b2c3d4e5f6` (`knowledge_versions`, plus `knowledge_version` on `interaction_llm_trigger_cache` and `policy_compliance`).

**Known inconsistency:** `infra/db/01_schema.sql` has 19 `CREATE TABLE`s, and its header comment ("17 DDL tables") is stale. The SQLModel models define 20 tables. `01_schema.sql` lacks:

- the `assistant_sessions` and `knowledge_versions` tables
- the columns `users.avatar_url`, `assistant_queries.session_id`, `interaction_llm_trigger_cache.knowledge_version` and `policy_compliance.knowledge_version`

On a fresh compose volume, `create_all` adds the two missing tables at startup but not the four columns. `01_schema.sql` already contains the 0002 objects, and 0002's `op.create_table("notifications")` is unguarded. So the stamp sequence suggested in the baseline migration's docstring (`stamp 0001_baseline` → `upgrade head`) fails on a DB built from the current file.

## Tables (21)

Model files are relative to `backend/app/models/`.

| Table | Model file | Purpose | Key relations |
|---|---|---|---|
| `organizations` | `organization.py` | Tenant (`slug` unique) | — |
| `users` | `user.py` | Managers and agents (`role`, `agent_type`, `avatar_url`) | → organizations |
| `interactions` | `interaction.py` | One call recording and its `processing_status` | → organizations; `agent_id`, `uploaded_by` → users; unique (`organization_id`, `audio_file_path`) |
| `processing_jobs` | `processing.py` | One row per pipeline stage (6 per interaction) | → interactions |
| `transcripts` | `transcript.py` | Full transcript | → interactions (1:1) |
| `utterances` | `utterance.py` | Speaker turns with role, timing, text and emotion | → interactions, transcripts; optional `user_id` → users |
| `emotion_events` | `emotion_event.py` | Emotion shifts; agent dispute fields (`is_flagged`, `agent_flagged_by/at`) | → interactions, utterances |
| `interaction_scores` | `interaction_score.py` | Overall/empathy/policy/resolution scores | → interactions (1:1) |
| `company_policies` | `policy.py` | Policy documents | → organizations (owner) |
| `organization_policies` | `policy.py` | Per-org policy toggle | → organizations, company_policies |
| `policy_compliance` | `policy.py` | Per-interaction policy verdict; dispute fields; `degraded`; `knowledge_version` | → interactions, company_policies |
| `faq_articles` | `faq.py` | SOP docs, plus KB articles (category prefix `kb:`) | → organizations |
| `organization_faq_articles` | `faq.py` | Per-org SOP/KB toggle | → organizations, faq_articles |
| `emotion_feedback` | `feedback.py` | Manager corrections and review outcomes for emotion events | → emotion_events, users |
| `compliance_feedback` | `feedback.py` | Same, for compliance results | → policy_compliance, users |
| `agent_performance_snapshots` | none (`01_schema.sql` only) | Periodic agent aggregates. No model or code uses it. | → organizations, users |
| `assistant_sessions` | `query.py` | Manager assistant chat sessions (soft delete via `is_deleted`) | → users, organizations |
| `assistant_queries` | `query.py` | Assistant turns: question, generated SQL, answer, `result_rows` | → assistant_sessions, users, organizations |
| `interaction_llm_trigger_cache` | `llm_trigger_cache.py` | Cached LLM trigger report (`report_payload` JSON) and the knowledge version used | → interactions (unique) |
| `notifications` | `notification.py` | In-app notifications (polled by the frontend) | → users (recipient), organizations |
| `knowledge_versions` | `knowledge_version.py` | Immutable org knowledge snapshots; one `is_active` per org | → organizations; `created_by` → users |

## Enums (`backend/app/models/enums.py`; Postgres type `<name>_enum`)

| Enum | Values |
|---|---|
| `org_status` | active, inactive, suspended |
| `user_role` | manager, agent |
| `agent_type` | human, ai |
| `processing_status` | pending, processing, completed, failed |
| `job_stage` | diarization, stt, emotion, reasoning, scoring, rag_eval |
| `job_status` | pending, running, completed, failed |
| `speaker_role` | agent, customer |
| `query_mode` | voice, chat |
| `feedback_status` | pending, reviewed, applied |
| `period_type` | daily, weekly, monthly |
| `notification_type` | evaluation_complete, agent_flag_pending, flag_approved, flag_rejected, manager_correction, feedback_applied |

## Read-only assistant role

`infra/db/04_assistant_readonly_role.sql` creates `vocalmind_readonly` with column-level `SELECT` grants. The assistant runs its generated SQL through `ASSISTANT_DATABASE_URL`, which should use this role. Supabase does not get this role automatically, so apply the script there yourself.

## Seed data

- **Backend startup** (`SEED_DEMO_DATA=true`): `backend/scripts/seed_nexalink.py` and `seed_meridian.py` create the NexaLink and Meridian orgs and their users.
- **`make reset-local ARGS="--yes"`**: truncates app tables on a local DB only, then reseeds both orgs.
