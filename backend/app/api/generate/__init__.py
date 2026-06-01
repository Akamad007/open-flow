"""generate package — combined router for all stage-trigger and pipeline endpoints."""

from fastapi import APIRouter

from app.api.generate.pipeline_triggers import router as pipeline_router
from app.api.generate.stage_triggers import router as stage_router

router = APIRouter()
router.include_router(stage_router)
router.include_router(pipeline_router)

__all__ = ["router"]
