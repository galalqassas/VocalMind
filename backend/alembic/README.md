# Alembic migrations

The canonical fresh-DB bootstrap is still
[`infra/db/01_schema.sql`](../../infra/db/01_schema.sql). Alembic owns
**incremental** schema changes on top of that baseline.

## Apply pending migrations

```bash
cd backend
uv run alembic upgrade head
```

Reads `DATABASE_URL` from `.env` (same one the API uses).

## First-time setup against an existing DB

If your database was bootstrapped from `infra/db/01_schema.sql` and has
not yet been touched by Alembic, mark it as having the baseline
migration before applying any newer ones:

```bash
uv run alembic stamp 0001_baseline
uv run alembic upgrade head
```

The `stamp` writes a row into the `alembic_version` table without
running any SQL — it just tells Alembic "trust me, the schema is
already at this revision."

## Day-to-day commands

| Goal | Command |
|---|---|
| New empty migration | `uv run alembic revision -m "what changed"` |
| Autogenerate from model diff | `uv run alembic revision --autogenerate -m "..."` |
| Apply pending | `uv run alembic upgrade head` |
| Roll back one revision | `uv run alembic downgrade -1` |
| Show current revision | `uv run alembic current` |
| Show history | `uv run alembic history` |

## Conventions

- One revision = one logical change. Don't bundle unrelated ALTERs.
- Always provide a working `downgrade()` unless the migration is
  irreversible (and say so in the docstring).
- `compare_type=True` + `compare_server_default=True` are on in
  `env.py`, so autogenerate will catch most column-shape changes,
  but always read the generated file before committing.
- For new tables, prefer model-first: update `app/models/*.py`, then
  `--autogenerate`. Hand-edit the autogen output to remove SQLModel-isms
  that don't translate (e.g. drop `if_not_exists` clauses Alembic
  doesn't emit).
