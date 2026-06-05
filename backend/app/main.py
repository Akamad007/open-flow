"""
FastAPI application entry point.
"""

import logging
from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.security import require_api_key

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Startup / shutdown lifecycle."""
    settings.ensure_storage_dirs()
    logger.info("Storage directories ensured at %s", settings.storage_root)
    yield
    logger.info("Shutting down")


app = FastAPI(
    title="OpenFlow",
    description="OpenFlow — multi-agent system for converting stories into cinematic videos",
    version="0.1.0",
    lifespan=lifespan,
    dependencies=[Depends(require_api_key)],  # no-op unless API_KEY is set
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Register API routers ──
from app.api.projects import router as projects_router
from app.api.episodes import router as episodes_router
from app.api.scenes import router as scenes_router
from app.api.characters import router as characters_router
from app.api.locations import router as locations_router
from app.api.products import router as products_router
from app.api.audio_plans import router as audio_plans_router
from app.api.assets import router as assets_router
from app.api.render_jobs import router as render_jobs_router
from app.api.generate import router as generate_router
from app.api.images import router as images_router
from app.api.celery_log import router as celery_log_router
from app.api.uploads import router as uploads_router
from app.api.youtube_uploads import router as youtube_uploads_router

app.include_router(projects_router, prefix="/api")
app.include_router(episodes_router, prefix="/api")
app.include_router(scenes_router, prefix="/api")
app.include_router(characters_router, prefix="/api")
app.include_router(locations_router, prefix="/api")
app.include_router(products_router, prefix="/api")
app.include_router(audio_plans_router, prefix="/api")
app.include_router(assets_router, prefix="/api")
app.include_router(render_jobs_router, prefix="/api")
app.include_router(generate_router, prefix="/api")
app.include_router(images_router, prefix="/api")
app.include_router(celery_log_router, prefix="/api")
app.include_router(uploads_router, prefix="/api")
app.include_router(youtube_uploads_router, prefix="/api")

# Serve generated assets
app.mount("/storage", StaticFiles(directory=str(settings.storage_root)), name="storage")


@app.get("/api/health")
async def health_check():
    """Liveness: process is up. Cheap, never touches dependencies."""
    return {"status": "ok", "version": "0.1.0"}


@app.get("/api/readiness")
async def readiness_check():
    """Readiness: verify DB and Redis are reachable. Returns 503 if degraded."""
    checks: dict[str, str] = {}

    try:
        from sqlalchemy import text

        from app.database import async_session_factory

        async with async_session_factory() as session:
            await session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["database"] = f"error: {type(exc).__name__}"

    try:
        import redis.asyncio as aioredis

        client = aioredis.from_url(settings.redis_url)
        await client.ping()
        await client.aclose()
        checks["redis"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["redis"] = f"error: {type(exc).__name__}"

    ready = all(v == "ok" for v in checks.values())
    return JSONResponse(
        status_code=200 if ready else 503,
        content={"status": "ready" if ready else "degraded", "checks": checks},
    )
