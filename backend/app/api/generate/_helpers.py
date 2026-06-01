"""Shared helpers for generate-* endpoints: project lookup + idempotent job dispatch."""

from __future__ import annotations

import logging
import uuid

from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project
from app.models.render_job import JobStatus, JobType, RenderJob

logger = logging.getLogger(__name__)


class TriggerResponse(BaseModel):
    job_id: str
    celery_task_id: str
    status: str = "queued"
    message: str = ""


async def get_project(project_id: uuid.UUID, db: AsyncSession) -> Project:
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


async def _reconcile_stuck_running(job: RenderJob, db: AsyncSession) -> bool:
    """If Celery already finished the job, mark it failed so a retry isn't blocked.
    Returns True if the job should be treated as released (caller can dispatch fresh)."""
    if not (job.celery_task_id and job.status == JobStatus.running):
        return False
    try:
        from app.orchestration.tasks import celery_app
        task_result = celery_app.AsyncResult(job.celery_task_id)
    except Exception:
        return False

    if task_result.state not in ("SUCCESS", "FAILURE", "REVOKED"):
        return False

    logger.warning(
        "Job %s (%s) stuck as 'running' but Celery state=%s — marking failed",
        job.id, job.job_type.value, task_result.state,
    )
    job.status = JobStatus.failed
    job.error_text = f"Auto-reconciled: Celery task {task_result.state} but job was never updated"
    await db.commit()
    return True


async def find_existing_job(
    project_id: uuid.UUID, job_type: JobType, db: AsyncSession,
) -> RenderJob | None:
    result = await db.execute(
        select(RenderJob)
        .where(RenderJob.project_id == project_id)
        .where(RenderJob.job_type == job_type)
        .where(RenderJob.status.in_([JobStatus.queued, JobStatus.running]))
        .order_by(RenderJob.created_at.desc())
        .limit(1)
    )
    job = result.scalar_one_or_none()
    if job is None:
        return None
    if await _reconcile_stuck_running(job, db):
        return None
    return job


async def create_job_and_dispatch(
    project_id: uuid.UUID,
    job_type: JobType,
    celery_task,
    db: AsyncSession,
    *task_args,
    **task_kwargs,
) -> TriggerResponse:
    existing = await find_existing_job(project_id, job_type, db)
    if existing:
        raise HTTPException(
            status_code=409,
            detail={
                "message": f"A '{job_type.value}' job is already queued or running for this project",
                "job_id": str(existing.id),
                "celery_task_id": existing.celery_task_id or "",
            },
        )

    job = RenderJob(project_id=project_id, job_type=job_type, status=JobStatus.queued)
    db.add(job)
    await db.flush()

    celery_result = celery_task.delay(str(project_id), *task_args, **task_kwargs)

    job.celery_task_id = celery_result.id
    job.status = JobStatus.running
    await db.commit()

    return TriggerResponse(job_id=str(job.id), celery_task_id=celery_result.id)
