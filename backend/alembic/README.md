# Alembic migrations

Alembic manages incremental schema changes. It reads `DATABASE_URL` through `app.core.config.settings` (`env.py`) and runs nothing automatically: compose, CI, the deploy workflow and the backend image all leave it out. How Alembic relates to `infra/db/01_schema.sql` and to `create_all` at startup, including the known gaps, is covered in [docs/architecture/DATABASE_SCHEMA.md](../../docs/architecture/DATABASE_SCHEMA.md).

Run every command from `backend/`.

| Goal | Command |
|---|---|
| Apply pending | `uv run alembic upgrade head` |
| Current / history | `uv run alembic current` / `uv run alembic history` |
| Mark a DB as already at a revision | `uv run alembic stamp <rev>` (writes `alembic_version` only) |
| New migration from a model diff | `uv run alembic revision --autogenerate -m "..."` |
| Roll back one | `uv run alembic downgrade -1` |

## Conventions

- Change the SQLModel in `app/models/` first, then autogenerate. Always read the generated file. `env.py` enables `compare_type` and `compare_server_default`, but autogenerate still misses things such as CHECK constraints and partial indexes.
- Keep one logical change per revision, and provide a working `downgrade()`.
- Prefer idempotent DDL (`IF NOT EXISTS`) when a target DB may already have the object, for example from `create_all` or `infra/db/*.sql`.
- File names follow `alembic.ini`: `YYYYMMDD_HHMM_<rev>_<slug>.py`. A Ruff format hook runs on new revisions.
