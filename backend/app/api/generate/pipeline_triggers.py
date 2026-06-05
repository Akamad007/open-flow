"""Full-pipeline / regenerate / single-scene endpoints."""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete as sa_delete, func, select, update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.generate._helpers import (
    TriggerResponse, create_job_and_dispatch, find_existing_job, get_project,
)
from app.config import settings
from app.database import get_db
from app.models.asset import Asset, AssetType
from app.models.project import Project, ProjectStatus
from app.models.render_job import JobStatus, JobType, RenderJob
from app.models.scene import Scene, SceneStatus
from app.orchestration.tasks import (
    task_dispatch_video_chord,
    task_pregen_images, task_run_full_pipeline,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["generate"])


_ACTIVE_PROJECT_STATUSES = [
    ProjectStatus.analyzing, ProjectStatus.planning, ProjectStatus.prompting,
    ProjectStatus.audio_planning, ProjectStatus.reviewing, ProjectStatus.image_pregen,
    ProjectStatus.generating, ProjectStatus.stitching,
]


async def _other_project_active(project_id: uuid.UUID, db: AsyncSession) -> bool:
    count = await db.scalar(
        select(func.count(Project.id)).where(
            Project.status.in_(_ACTIVE_PROJECT_STATUSES),
            Project.id != project_id,
        )
    )
    return bool(count and count > 0)


async def _clear_redis_stage_locks(project_id: uuid.UUID) -> None:
    try:
        from app.orchestration.locks import _get_redis
        r = _get_redis()
        keys = list(r.scan_iter(f"pipeline:stage:{project_id}:*"))
        if keys:
            r.delete(*keys)
    except Exception as exc:
        logger.warning("Failed to clear redis stage locks for %s: %s", project_id, exc)


async def _wipe_videos_for_regen(project_id: uuid.UUID, db: AsyncSession) -> None:
    await db.execute(
        sa_delete(Asset).where(
            Asset.project_id == project_id,
            Asset.asset_type == AssetType.scene_video,
        )
    )
    await db.execute(
        sa_update(Scene)
        .where(Scene.project_id == project_id)
        .values(status=SceneStatus.prompted)
    )
    await db.execute(
        sa_update(Project)
        .where(Project.id == project_id)
        .values(status=ProjectStatus.image_pregen)
    )
    await db.execute(
        sa_delete(RenderJob).where(
            RenderJob.project_id == project_id,
            RenderJob.job_type == JobType.video_generation,
            RenderJob.status.in_([JobStatus.queued, JobStatus.running]),
        )
    )
    await db.commit()


@router.post("/projects/{project_id}/regenerate-videos", response_model=TriggerResponse, status_code=202)
async def regenerate_videos(
    project_id: uuid.UUID, db: AsyncSession = Depends(get_db),
):
    """Force-regenerate all scene videos: clear locks, wipe asset rows, reset state, then dispatch."""
    await get_project(project_id, db)
    await _clear_redis_stage_locks(project_id)
    await _wipe_videos_for_regen(project_id, db)
    return await create_job_and_dispatch(
        project_id, JobType.video_generation, task_dispatch_video_chord, db,
        True,  # force=True
    )


_ACTION_ASSET_TYPES = (
    AssetType.scene_action_seq,
    AssetType.scene_action,
    AssetType.scene_action_2,
    AssetType.product_ref,
)


async def _wipe_action_stills_for_regen(project_id: uuid.UUID, db: AsyncSession) -> int:
    """Wipe action-still asset rows + on-disk PNGs so regen actually runs.

    Action stills are skipped when the .png exists (idempotent fast path),
    so we MUST delete the files for regeneration to proceed.
    """
    await db.execute(
        sa_delete(Asset).where(
            Asset.project_id == project_id,
            Asset.asset_type.in_(_ACTION_ASSET_TYPES),
        )
    )

    action_dir = Path(settings.storage_root) / "scene_actions" / str(project_id)
    deleted = 0
    if action_dir.exists():
        for f in action_dir.iterdir():
            try:
                if f.is_file():
                    f.unlink()
                    deleted += 1
            except Exception as e:
                logger.warning("Failed to delete %s: %s", f, e)

    await db.execute(
        sa_update(Project)
        .where(Project.id == project_id)
        .values(status=ProjectStatus.image_pregen)
    )
    await db.commit()
    logger.info(
        "Wiped action stills for project %s: %d files deleted from %s",
        project_id, deleted, action_dir,
    )
    return deleted


@router.post("/projects/{project_id}/regenerate-images", response_model=TriggerResponse, status_code=202)
async def regenerate_images(
    project_id: uuid.UUID, db: AsyncSession = Depends(get_db),
):
    """Force-regenerate all per-second action stills: wipe assets + files, then re-run pregen."""
    await get_project(project_id, db)
    await _clear_redis_stage_locks(project_id)
    await _wipe_action_stills_for_regen(project_id, db)
    return await create_job_and_dispatch(
        project_id, JobType.image_pregen, task_pregen_images, db,
    )


@router.post("/projects/{project_id}/generate-all", response_model=TriggerResponse, status_code=202)
async def generate_all(project_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Run the full pipeline. 409 if any project (including this one) is mid-pipeline."""
    await get_project(project_id, db)

    existing = await find_existing_job(project_id, JobType.full_pipeline, db)
    if existing:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "A full pipeline is already running for this project",
                "job_id": str(existing.id),
                "celery_task_id": existing.celery_task_id or "",
            },
        )

    if await _other_project_active(project_id, db):
        raise HTTPException(
            status_code=409,
            detail="Another project is currently running. Please wait for it to complete.",
        )

    job = RenderJob(
        project_id=project_id, job_type=JobType.full_pipeline, status=JobStatus.queued,
    )
    db.add(job)
    await db.flush()

    celery_result = task_run_full_pipeline.delay(str(project_id))

    job.celery_task_id = celery_result.id
    job.status = JobStatus.running
    await db.commit()

    return TriggerResponse(
        job_id=str(job.id),
        celery_task_id=celery_result.id,
        message="Full pipeline workflow dispatched",
    )


@router.post("/scenes/{scene_id}/regenerate", response_model=TriggerResponse, status_code=202)
async def regenerate_scene(scene_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Regenerate a single scene's video.

    Deletes the existing video (DB row + file on disk) synchronously, resets the
    scene to `prompted` and the project to `generating`, then re-dispatches the
    video chord. The chord skips all already-complete scenes and fires the
    audio → stitch → eval → cleanup chain when this scene finishes. So a single
    regenerate triggers: delete → regen → stitch → eval, end-to-end.
    """
    scene = await db.get(Scene, scene_id)
    if not scene:
        raise HTTPException(status_code=404, detail="Scene not found")

    existing = (await db.execute(
        select(Asset).where(
            Asset.scene_id == scene_id,
            Asset.asset_type == AssetType.scene_video,
        )
    )).scalars().all()
    for asset in existing:
        if asset.file_path:
            file_abs = (settings.storage_root.parent / asset.file_path).resolve()
            try:
                if file_abs.is_file():
                    # Soft-delete: move aside instead of destroying the prior render.
                    file_abs.rename(file_abs.with_name(f"{file_abs.name}.bak-{asset.id}"))
            except OSError as exc:
                logger.warning("regenerate_scene: failed to move aside %s: %s", file_abs, exc)
        await db.delete(asset)
    scene.status = SceneStatus.prompted
    project = await db.get(Project, scene.project_id)
    if project:
        project.status = ProjectStatus.generating
    await db.commit()
    await _clear_redis_stage_locks(scene.project_id)
    logger.info(
        "regenerate_scene %s: wiped %d asset(s), reset scene + project, dispatching chord",
        scene_id, len(existing),
    )

    return await create_job_and_dispatch(
        scene.project_id, JobType.video_generation, task_dispatch_video_chord, db,
        False,  # force=False — other scenes skip if already complete; only this one regens
    )
