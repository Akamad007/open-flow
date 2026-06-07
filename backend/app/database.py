"""
Async SQLAlchemy engine, session factory, and FastAPI dependency.
"""

from collections.abc import AsyncGenerator
from typing import Optional

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

# ── Lazy engine / session factory ──
# Created on first access to avoid binding asyncpg connections
# to a stale event loop (critical for Celery workers).
_engine: Optional[AsyncEngine] = None
_session_factory: Optional[async_sessionmaker] = None

# Postgres-side safety timeouts (applied to every connection). Without these a
# kill -9'd worker leaves its transaction "idle in transaction" holding row
# locks forever, blocking later DML and hanging the backend.
# NOTE: stages currently hold a transaction open ACROSS the multi-minute LLM
# call and the ~10-min GPU render (it sits "idle in transaction" the whole
# time). So the idle timeout must exceed the longest such call, or it kills
# live work. 30min self-heals a kill -9 while leaving legitimate long stages
# alone. The real fix is to not hold a txn across external calls (shrink scope);
# until then, keep this generous.
_PG_TIMEOUTS = {
    "idle_in_transaction_session_timeout": "1800000",  # 30min: self-heal stranded txns
    "lock_timeout": "15000",                           # 15s: fail fast instead of hanging on a lock
}


def _get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = create_async_engine(
            settings.database_url,
            echo=False,
            pool_size=10,
            max_overflow=20,
            pool_pre_ping=True,
            connect_args={"server_settings": _PG_TIMEOUTS},
        )
    return _engine


def _get_session_factory() -> async_sessionmaker:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            _get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _session_factory


class _SessionFactoryProxy:
    """Proxy that delegates to the lazily-created session factory.

    This lets callers write `async with async_session_factory() as s:` while
    still deferring engine creation until first use.  The proxy can also be
    replaced wholesale by the Celery _run_async helper.
    """

    def __call__(self):
        return _get_session_factory()()

    def __repr__(self):
        return f"<SessionFactoryProxy -> {_session_factory}>"


async_session_factory = _SessionFactoryProxy()

# Keep an `async_engine` attribute so Celery tasks can dispose it
async_engine = None  # Will be set by _run_async or lazily


class Base(DeclarativeBase):
    """Base class for all ORM models."""
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields an async database session."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

