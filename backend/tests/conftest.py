"""Shared pytest fixtures: testcontainers Postgres + per-test sessions + FakeLLM.

Forces stub providers and blocks outbound HTTP / subprocess so the test suite
never hits OpenAI, HF, LTX, Chatterbox, ffmpeg, or any remote service.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import AsyncIterator

import pytest
import pytest_asyncio

# Force stub providers BEFORE app imports so settings reflects test mode.
os.environ.setdefault("LLM_PROVIDER", "stub")
os.environ.setdefault("VIDEO_PROVIDER", "stub")
os.environ.setdefault("AUDIO_PROVIDER", "stub")
os.environ.setdefault("IMAGE_PROVIDER", "stub")

from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from testcontainers.postgres import PostgresContainer  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent))


# ── Block outbound HTTP + subprocess ──────────────────────────────────────────

_NETWORK_BLOCK_MSG = (
    "Test attempted external {kind}: {detail}. "
    "Use stub providers / FakeLLM instead, or mark the test @pytest.mark.live."
)


def _block_httpx():
    """Block HTTP to non-local hosts. Local (test ASGI / 127.0.0.1) is allowed."""
    import httpx

    _LOCAL_HOSTS = {"test", "localhost", "127.0.0.1", "::1", ""}

    def _is_local(request) -> bool:
        try:
            host = request.url.host
        except Exception:
            return False
        return host in _LOCAL_HOSTS

    original_sync_send = httpx.Client.send
    original_async_send = httpx.AsyncClient.send

    def _guarded_sync_send(self, request, *args, **kwargs):
        if not _is_local(request):
            raise RuntimeError(_NETWORK_BLOCK_MSG.format(
                kind="HTTP request", detail=f"httpx.Client.send → {request.url}",
            ))
        return original_sync_send(self, request, *args, **kwargs)

    async def _guarded_async_send(self, request, *args, **kwargs):
        if not _is_local(request):
            raise RuntimeError(_NETWORK_BLOCK_MSG.format(
                kind="HTTP request", detail=f"httpx.AsyncClient.send → {request.url}",
            ))
        return await original_async_send(self, request, *args, **kwargs)

    httpx.Client.send = _guarded_sync_send
    httpx.AsyncClient.send = _guarded_async_send


def _block_urllib():
    import urllib.request as _ur

    def _blocked_urlopen(*args, **kwargs):
        raise RuntimeError(_NETWORK_BLOCK_MSG.format(kind="HTTP request", detail="urllib.urlopen"))

    _ur.urlopen = _blocked_urlopen


def _block_openai_sdk():
    """Best-effort: stop the OpenAI client from making real calls if it gets instantiated."""
    try:
        import openai  # noqa
    except ImportError:
        return

    def _blocked(*args, **kwargs):
        raise RuntimeError(_NETWORK_BLOCK_MSG.format(kind="OpenAI call", detail="openai SDK"))

    try:
        openai.OpenAI.__init__ = _blocked  # type: ignore[attr-defined]
    except Exception:
        pass


def _block_subprocess():
    """Block subprocess spawns except for an allowlist of safe local tools."""
    import asyncio as _asyncio
    import os as _os
    import subprocess as _sp

    # Local tools that are safe + needed by stub providers (no network, no GPU model loads).
    _ALLOWED_BASENAMES = {"ffmpeg", "ffprobe"}

    def _allowed(args) -> bool:
        if isinstance(args, str):
            first = args.split()[0] if args.split() else ""
        else:
            first = str(args[0]) if args else ""
        return _os.path.basename(first) in _ALLOWED_BASENAMES

    original_popen_init = _sp.Popen.__init__

    def _blocked_popen_init(self, args, *a, **kw):
        if _allowed(args):
            return original_popen_init(self, args, *a, **kw)
        cmd = args if isinstance(args, str) else " ".join(str(x) for x in (args or []))
        raise RuntimeError(_NETWORK_BLOCK_MSG.format(
            kind="subprocess spawn", detail=f"Popen({cmd!r})",
        ))

    _sp.Popen.__init__ = _blocked_popen_init

    original_create_exec = _asyncio.create_subprocess_exec

    async def _blocked_create_subprocess_exec(*args, **kwargs):
        if args and _os.path.basename(str(args[0])) in _ALLOWED_BASENAMES:
            return await original_create_exec(*args, **kwargs)
        raise RuntimeError(_NETWORK_BLOCK_MSG.format(
            kind="subprocess spawn", detail=f"create_subprocess_exec({args!r})",
        ))

    _asyncio.create_subprocess_exec = _blocked_create_subprocess_exec

    async def _blocked_create_subprocess_shell(cmd, *args, **kwargs):
        raise RuntimeError(_NETWORK_BLOCK_MSG.format(
            kind="subprocess spawn", detail=f"create_subprocess_shell({cmd!r})",
        ))

    _asyncio.create_subprocess_shell = _blocked_create_subprocess_shell


@pytest.fixture(scope="session", autouse=True)
def _block_external_calls():
    _block_httpx()
    _block_urllib()
    _block_openai_sdk()
    _block_subprocess()
    yield


# ── Postgres container — session-scoped (one per pytest run) ──────────────────

@pytest.fixture(scope="session")
def postgres_container():
    """Spins up Postgres 15 in Docker. Skipped if Docker is unavailable."""
    try:
        container = PostgresContainer("postgres:15-alpine")
        container.start()
    except Exception as exc:
        pytest.skip(f"Could not start Postgres container: {exc}")
        return
    try:
        yield container
    finally:
        container.stop()


@pytest.fixture(scope="session")
def database_url(postgres_container) -> str:
    """asyncpg URL for the test container."""
    raw = postgres_container.get_connection_url()
    # testcontainers gives us postgresql+psycopg2://...; normalize to asyncpg.
    return raw.replace("postgresql+psycopg2://", "postgresql+asyncpg://")


# ── Engine / schema setup ─────────────────────────────────────────────────────

@pytest_asyncio.fixture(scope="session")
async def _schema_engine(database_url) -> AsyncIterator[AsyncEngine]:
    """Creates the schema once per session via `Base.metadata.create_all`."""
    from app.database import Base
    # Import models so all tables are registered on Base.metadata.
    import app.models.asset            # noqa: F401
    import app.models.audio_plan       # noqa: F401
    import app.models.character        # noqa: F401
    import app.models.location         # noqa: F401
    import app.models.project          # noqa: F401
    import app.models.render_job       # noqa: F401
    import app.models.scene            # noqa: F401
    import app.models.scene_prompt     # noqa: F401

    engine = create_async_engine(database_url, echo=False, future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def db_engine(_schema_engine, monkeypatch, database_url) -> AsyncIterator[AsyncEngine]:
    """Per-test engine bound to the same DB. Patches app.database singletons."""
    import app.database as db_module

    engine = create_async_engine(database_url, echo=False, future=True)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    monkeypatch.setattr(db_module, "_engine", engine)
    monkeypatch.setattr(db_module, "_session_factory", factory)

    try:
        yield engine
    finally:
        await engine.dispose()
        monkeypatch.setattr(db_module, "_engine", None)
        monkeypatch.setattr(db_module, "_session_factory", None)


@pytest_asyncio.fixture
async def db_session(db_engine) -> AsyncIterator[AsyncSession]:
    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session


# ── Truncate-between-tests fixture ────────────────────────────────────────────

@pytest_asyncio.fixture(autouse=True)
async def _truncate_tables(db_engine):
    """Wipe rows after each test so tests are independent."""
    yield
    from app.database import Base
    async with db_engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            await conn.exec_driver_sql(f'TRUNCATE TABLE "{table.name}" RESTART IDENTITY CASCADE')


# ── Fake LLM ──────────────────────────────────────────────────────────────────

class FakeLLM:
    """Minimal LLM stub that returns canned JSON or raises if unconfigured."""

    def __init__(self, responses: list[dict] | dict | None = None):
        if isinstance(responses, dict):
            self._queue = [responses]
        else:
            self._queue = list(responses or [])
        self.calls: list[dict] = []

    async def complete_json(self, system_prompt: str = "", user_prompt: str = "", **kwargs):
        self.calls.append({"system": system_prompt, "user": user_prompt, **kwargs})
        if not self._queue:
            return {}
        return self._queue.pop(0) if len(self._queue) > 1 else self._queue[0]

    async def complete(self, *args, **kwargs):
        result = await self.complete_json(*args, **kwargs)
        return str(result)


@pytest.fixture
def fake_llm():
    return FakeLLM()
