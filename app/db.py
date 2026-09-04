# app/db.py
"""
Async SQLAlchemy engine + session factory.

Supabase pooler gotcha: if DATABASE_URL points at Supabase's pgbouncer
pooler in Transaction mode (port 6543), asyncpg's server-side prepared
statement cache WILL break under concurrent load with intermittent
"prepared statement does not exist" errors. USE_PGBOUNCER=true disables
the statement cache and switches to NullPool.
"""
from __future__ import annotations

import os
from typing import AsyncGenerator

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

load_dotenv()

try:
    DATABASE_URL = os.environ["DATABASE_URL"]
except KeyError as exc:
    raise RuntimeError(
        "DATABASE_URL is not set. Refusing to start without an explicit "
        "database connection string."
    ) from exc

if not DATABASE_URL.startswith("postgresql+asyncpg://"):
    raise RuntimeError(
        "DATABASE_URL must use the postgresql+asyncpg:// driver prefix, "
        f"got scheme: {DATABASE_URL.split('://')[0]}://..."
    )

USE_PGBOUNCER = os.getenv("USE_PGBOUNCER", "false").lower() == "true"
SQL_ECHO = os.getenv("SQL_ECHO", "false").lower() == "true"

_engine_kwargs: dict = {
    "echo": SQL_ECHO,
    "pool_pre_ping": True,
}

if USE_PGBOUNCER:
    _engine_kwargs["poolclass"] = NullPool
    _engine_kwargs["connect_args"] = {
        "statement_cache_size": 0,
        "prepared_statement_cache_size": 0,
    }
else:
    _engine_kwargs["pool_size"] = 5
    _engine_kwargs["max_overflow"] = 10
    _engine_kwargs["pool_recycle"] = 1800

engine = create_async_engine(DATABASE_URL, **_engine_kwargs)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: one session per request, always rolled back on error and closed."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()