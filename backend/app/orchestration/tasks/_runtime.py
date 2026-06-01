"""Per-task event-loop + DB-engine isolation, plus shared cancellation helper."""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

logger = logging.getLogger(__name__)


def is_cancelled(exc: Exception) -> bool:
    """True if the exception means the project was deleted/cancelled."""
    from app.orchestration.pipeline import ProjectCancelledError
    return isinstance(exc, ProjectCancelledError)


def run_async(coro):
    """Run a coroutine in a fresh loop with a fresh DB engine.

    Each Celery task gets its own loop+engine to avoid asyncpg cross-loop errors
    when the worker reuses processes.
    """
    import app.database as db_module

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        if db_module._engine is not None:
            try:
                loop.run_until_complete(db_module._engine.dispose())
            except Exception:
                pass
            db_module._engine = None
            db_module._session_factory = None

        engine = create_async_engine(
            settings.database_url, echo=False,
            pool_size=5, max_overflow=10, pool_pre_ping=True,
        )
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        db_module._engine = engine
        db_module._session_factory = factory
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.run_until_complete(engine.dispose())
            db_module._engine = None
            db_module._session_factory = None
    finally:
        loop.close()


def to_uuid(value: str):
    import uuid
    return uuid.UUID(value)
