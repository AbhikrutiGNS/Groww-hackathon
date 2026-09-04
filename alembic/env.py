# alembic/env.py
"""
Async-aware Alembic environment, targeting app.models.Base.metadata.

Gotcha this file exists to solve: Alembic must run against Supabase's
DIRECT connection (port 5432), not the pgbouncer pooler (port 6543,
transaction mode). Transaction-mode pooling breaks Alembic's session-level
migration advisory lock and doesn't reliably support DDL. Set
ALEMBIC_DATABASE_URL in .env to the direct connection string; if it's not
set, this falls back to DATABASE_URL.
"""
from __future__ import annotations

import asyncio
import os
import sys
from logging.config import fileConfig
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# Make `app` importable regardless of the working directory Alembic is
# invoked from (matters on Windows if you run `alembic` from a different
# folder than the project root in VS Code's integrated terminal).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models import Base  # noqa: E402

load_dotenv()

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_url() -> str:
    url = os.environ.get("ALEMBIC_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "Set ALEMBIC_DATABASE_URL (preferred) or DATABASE_URL in .env "
            "before running Alembic."
        )
    if not url.startswith("postgresql+asyncpg://"):
        raise RuntimeError(
            "Alembic's database URL must use the postgresql+asyncpg:// "
            f"driver prefix, got: {url.split('://')[0]}://..."
        )
    return url


def run_migrations_offline() -> None:
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = get_url()

    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())