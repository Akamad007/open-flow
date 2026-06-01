"""Pipeline cleanup task + Redis lock release helper."""

from __future__ import annotations

import logging

from celery.exceptions import Ignore

from app.orchestration.tasks._app import celery_app
from app.orchestration.tasks._runtime import run_async, to_uuid

logger = logging.getLogger(__name__)


def release_pipeline_lock_for_project(project_id: str) -> None:
    """Release the project-level pipeline lock. Called at pipeline end or on failure."""
    try:
        from app.orchestration.locks import _get_redis, _pipeline_key
        r = _get_redis()
        task_key = f"pipeline:full_task:{project_id}"
        task_id = r.get(task_key)
        if task_id:
            lock_key = _pipeline_key(project_id)
            current = r.get(lock_key)
            if current == task_id:
                r.delete(lock_key)
            r.delete(task_key)
            logger.info("Released pipeline lock for project %s (task=%s)", project_id, task_id)
    except Exception as e:
        logger.warning("Could not release pipeline lock for project %s: %s", project_id, e)


async def _mark_full_pipeline_done(project_id: str) -> None:
    from sqlalchemy import select as sa_select

    from app.database import async_session_factory
    from app.models.render_job import JobStatus, JobType, RenderJob

    async with async_session_factory() as db:
        result = await db.execute(
            sa_select(RenderJob)
            .where(RenderJob.project_id == to_uuid(project_id))
            .where(RenderJob.job_type == JobType.full_pipeline)
            .where(RenderJob.status == JobStatus.running)
            .order_by(RenderJob.created_at.desc())
            .limit(1)
        )
        job = result.scalar_one_or_none()
        if job:
            job.status = JobStatus.complete
            await db.commit()
            logger.info("Marked full_pipeline job %s complete for project %s", job.id, project_id)


@celery_app.task(name="storyvideo.pipeline_cleanup", bind=True, max_retries=2)
def task_pipeline_cleanup(self, project_id: str):
    """Final task: releases the pipeline lock and marks full_pipeline job complete."""
    release_pipeline_lock_for_project(project_id)
    try:
        run_async(_mark_full_pipeline_done(project_id))
    except Ignore:
        raise
    except Exception as e:
        logger.warning("Could not mark full_pipeline job complete: %s", e)
    logger.info("[Pipeline] Full pipeline complete and lock released for project %s", project_id)
