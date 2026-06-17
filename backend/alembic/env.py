"""Alembic env wired for the project's async SQLAlchemy engine and SQLModel
metadata.

Reads ``DATABASE_URL`` from the app's ``settings`` (so the same .env that
runs the API runs migrations). Strips ``+asyncpg`` for the synchronous
inspector that alembic uses to detect autogenerate diffs — runtime
migrations themselves still go through asyncpg.
"""
from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.core.config import settings

# Importing the package triggers every model module, which registers every
# table on SQLModel.metadata — required for --autogenerate to see them.
import app.models  # noqa: F401
from sqlmodel import SQLModel


config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def _resolve_database_url() -> str:
    url = settings.DATABASE_URL
    if not url:
        raise RuntimeError("DATABASE_URL is empty — set it in .env before running alembic")
    return url


target_metadata = SQLModel.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode — emit SQL to stdout without a live DB."""
    context.configure(
        url=_resolve_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Run migrations in 'online' mode against the async engine."""
    config_section = config.get_section(config.config_ini_section, {}) or {}
    config_section["sqlalchemy.url"] = _resolve_database_url()

    connectable = async_engine_from_config(
        config_section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(_do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
