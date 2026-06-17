# Production bootstrap & schema management

> **Important context.** `infra/db/01_schema.sql` is the *current*
> snapshot of the full schema, including every Alembic-managed change
> that's been merged. Alembic migrations exist so that **existing**
> databases on older schemas can catch up incrementally. For a
> brand-new DB you bootstrap from `01_schema.sql` and then *stamp*
> Alembic at head — you do not run the migrations, because the schema
> they would build is already there.

Two scenarios. Pick the one that matches your DB's state.

## A. Brand-new Supabase / Postgres

1. **Apply the current full schema.**
   ```bash
   psql "$DATABASE_URL_SYNC" < infra/db/01_schema.sql
   ```
   (`$DATABASE_URL_SYNC` is the same connection without the `+asyncpg`.)

2. **Mark Alembic as already-at-head** (do *not* `upgrade` — the schema
   is already there):
   ```bash
   cd backend
   uv run alembic stamp head
   ```

3. **Configure the env:**
   ```env
   DATABASE_URL=postgresql+asyncpg://postgres.<ref>:<pw>@<pooler-host>:6543/postgres
   SEED_DEMO_DATA=true   # only for the first boot — flip to false after
   SUPABASE_URL=https://<ref>.supabase.co
   SUPABASE_SERVICE_KEY=...        # rotate any key you ever pasted in chat
   ```

4. **Boot the backend once.** With `SEED_DEMO_DATA=true`, lifespan calls
   `seed_nexalink` + `seed_meridian` and creates the two demo orgs +
   their users.

5. **Flip `SEED_DEMO_DATA=false` and redeploy.** Subsequent boots no
   longer touch demo data.

## B. Existing Supabase that was hand-managed before this PR

The production database we're working with (NileTech + CairoConnect)
falls into this bucket. Steps to convert it to the canonical
"Nexalink + Meridian only" world managed by Alembic:

1. **Back up first.** Supabase Dashboard → Database → Backups.

2. **Wipe the obsolete demo orgs:**
   ```sql
   -- Paste the contents of tools/sync_remote_supabase.sql into the
   -- Supabase SQL Editor and run.
   ```
   This drops NileTech, CairoConnect, and everything that cascades from
   them.

3. **Stamp the baseline:**
   ```bash
   cd backend
   uv run alembic stamp 0001_baseline
   ```

4. **Apply the new migrations:**
   ```bash
   uv run alembic upgrade head
   ```
   Migration `0002_notif_and_dispute` adds the
   `notifications` table, the `notification_type_enum`, and the four
   agent-dispute columns on `policy_compliance`. It's safe to re-run
   (`IF NOT EXISTS` guards on the type and indexes).

5. **First boot with `SEED_DEMO_DATA=true`** to create Nexalink +
   Meridian + their users, then flip to `false`.

## Day-to-day schema changes

1. Edit the SQLModel in `backend/app/models/...`.
2. `cd backend && uv run alembic revision --autogenerate -m "what changed"`.
3. Open the generated file under `backend/alembic/versions/` and
   hand-check it — autogenerate gets ~80 % right and misses things like
   custom CHECK constraints, partial indexes, and JSONB-vs-JSON variants.
4. Run `uv run alembic upgrade head` against your dev DB.
5. Run the test suite (`vocalmind-validate` skill).
6. Commit the model change + the migration in the same PR.

## Rolling back

```bash
uv run alembic downgrade -1     # back out the most recent migration
uv run alembic downgrade <rev>  # back out everything past <rev>
```

Each migration in this repo has a working `downgrade()` unless the
docstring says otherwise.

## What the env vars actually control

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | Primary DB connection — both the app *and* `alembic upgrade` read it. |
| `SEED_DEMO_DATA` | If `true`, `seed_nexalink` + `seed_meridian` run on every backend boot. Must be `false` in any shared/prod environment. |
| `SUPABASE_URL` / `SUPABASE_SERVICE_KEY` | Used by the small number of routes that talk to the Supabase Python client directly. Not used by the main SQLAlchemy/SQLModel session — that one reads `DATABASE_URL`. |
| `QDRANT_URL` | Vector DB. Default is local Docker (`http://qdrant:6333`). For a hosted Qdrant Cloud cluster set the cluster URL and add `QDRANT_API_KEY` to env + config. There is no remote vector DB today. |
| `AUDIO_FOLDER_WATCHER_ENABLED` | Default `true`. Disable in a deployment where audio comes only via the upload endpoint. |
| `IS_LOCAL` | `true` → local Docker ML services; `false` → Kaggle/remote inference. |

## Audio folder watcher — convention

`storage/audio/<org_slug>/CALL_<NN>_<agent_name_lowercase>_<scenario>.<wav|mp3>`

- The watcher picks the org by folder name matching `organizations.slug`.
- It matches the filename token to an active agent of that org by
  `User.name.lower()`. If the token doesn't match any agent, a
  deterministic fallback agent is assigned and a warning is logged.
- For the canonical orgs:
  - `storage/audio/nexalink/CALL_NN_{priya,daniel,marcus,aisha,hannah}_*.wav`
  - `storage/audio/meridian/CALL_NN_{sarah,tyler,andre,jasmine,karen}_*.wav`
