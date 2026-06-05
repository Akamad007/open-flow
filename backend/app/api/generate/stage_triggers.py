"""Per-stage POST endpoints — each kicks off one async pipeline step."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.generate._helpers import (
    TriggerResponse, create_job_and_dispatch, get_project,
)
from app.database import get_db
from app.models.project import ProjectStatus
from app.models.render_job import JobType
from app.orchestration.tasks import (
    task_analyze_story,
    task_dispatch_video_chord,
    task_generate_audio,
    task_generate_prompts,
    task_plan_audio,
    task_plan_scenes,
    task_review_consistency,
    task_stitch,
)

router = APIRouter(tags=["generate"])


@router.post("/projects/{project_id}/analyze", response_model=TriggerResponse, status_code=202)
async def analyze_story(project_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    await get_project(project_id, db)
    return await create_job_and_dispatch(
        project_id, JobType.story_analysis, task_analyze_story, db,
    )


@router.post("/projects/{project_id}/plan-scenes", response_model=TriggerResponse, status_code=202)
async def plan_scenes(project_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    await get_project(project_id, db)
    return await create_job_and_dispatch(
        project_id, JobType.scene_planning, task_plan_scenes, db,
    )


@router.post("/projects/{project_id}/generate-prompts", response_model=TriggerResponse, status_code=202)
async def generate_prompts(project_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    await get_project(project_id, db)
    return await create_job_and_dispatch(
        project_id, JobType.prompt_generation, task_generate_prompts, db,
    )


@router.post("/projects/{project_id}/plan-audio", response_model=TriggerResponse, status_code=202)
async def plan_audio(project_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    await get_project(project_id, db)
    return await create_job_and_dispatch(
        project_id, JobType.audio_planning, task_plan_audio, db,
    )


@router.post("/projects/{project_id}/review", response_model=TriggerResponse, status_code=202)
async def review_consistency(project_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    await get_project(project_id, db)
    return await create_job_and_dispatch(
        project_id, JobType.consistency_review, task_review_consistency, db,
    )


@router.post("/projects/{project_id}/generate-videos", response_model=TriggerResponse, status_code=202)
async def generate_videos(project_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    project = await get_project(project_id, db)
    # Rerun rescues failed projects — flip back to generating so scene tasks
    # don't get cancelled by assert_project_active.
    if project.status == ProjectStatus.failed:
        project.status = ProjectStatus.generating
        await db.commit()
    return await create_job_and_dispatch(
        project_id, JobType.video_generation, task_dispatch_video_chord, db,
    )


@router.post("/projects/{project_id}/generate-audio", response_model=TriggerResponse, status_code=202)
async def generate_audio(project_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    await get_project(project_id, db)
    return await create_job_and_dispatch(
        project_id, JobType.audio_generation, task_generate_audio, db,
    )


@router.post("/projects/{project_id}/stitch", response_model=TriggerResponse, status_code=202)
async def stitch_project(project_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    await get_project(project_id, db)
    return await create_job_and_dispatch(
        project_id, JobType.stitching, task_stitch, db,
    )
