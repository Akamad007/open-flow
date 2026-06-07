"""Audio Plans API router."""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api._common import NOT_FOUND_RESPONSE, get_or_404
from app.database import get_db
from app.models.audio_plan import AudioPlan
from app.schemas.audio_plan import AudioPlanRead, AudioPlanUpdate

router = APIRouter(tags=["audio_plans"], responses=NOT_FOUND_RESPONSE)


@router.get("/projects/{project_id}/audio-plan", response_model=AudioPlanRead | None)
async def get_audio_plan(project_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    # Legacy/back-compat: returns the first audio_plan for this project.
    # Prefer /episodes/{id}/audio-plan when working with multi-episode projects.
    stmt = select(AudioPlan).where(AudioPlan.project_id == project_id).limit(1)
    result = await db.execute(stmt)
    plan = result.scalar_one_or_none()
    if not plan:
        return None
    return AudioPlanRead.model_validate(plan)


@router.get("/episodes/{episode_id}/audio-plan", response_model=AudioPlanRead | None)
async def get_audio_plan_for_episode(
    episode_id: uuid.UUID, db: AsyncSession = Depends(get_db),
):
    stmt = select(AudioPlan).where(AudioPlan.episode_id == episode_id)
    plan = (await db.execute(stmt)).scalar_one_or_none()
    return AudioPlanRead.model_validate(plan) if plan else None


@router.put("/audio-plans/{plan_id}", response_model=AudioPlanRead)
async def update_audio_plan(
    plan_id: uuid.UUID,
    data: AudioPlanUpdate,
    db: AsyncSession = Depends(get_db),
):
    plan = await get_or_404(db, AudioPlan, plan_id, "Audio plan")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(plan, key, value)

    await db.flush()
    await db.refresh(plan)
    return AudioPlanRead.model_validate(plan)
