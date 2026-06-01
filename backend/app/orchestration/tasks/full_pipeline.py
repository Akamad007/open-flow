"""Top-level full-pipeline task + workflow chain builder."""

from __future__ import annotations

import logging

from celery import chain
from celery.exceptions import Ignore

from app.orchestration.locks import acquire_pipeline_lock
from app.orchestration.tasks._app import celery_app
from app.orchestration.tasks.scene_tasks import task_dispatch_video_chord
from app.orchestration.tasks.stage_tasks import (
    task_analyze_story,
    task_generate_prompts,
    task_plan_audio,
    task_plan_scenes,
    task_pregen_images,
    task_review_consistency,
)

logger = logging.getLogger(__name__)


def build_pipeline_workflow(project_id: str):
    """Pre-video stages then video chord. audio_planning + audio_generation +
    stitch happen in the chord-callback chain AFTER the video is on disk so
    the narration text + TTS pace are sized to the ACTUAL rendered duration,
    not the planner's estimate. No more time-stretched audio."""
    return chain(
        task_analyze_story.si(project_id),
        task_plan_scenes.si(project_id),
        task_generate_prompts.si(project_id),
        task_review_consistency.si(project_id),
        task_pregen_images.si(project_id),
        task_dispatch_video_chord.si(project_id),
    )


@celery_app.task(name="storyvideo.full_pipeline", bind=True, max_retries=0)
def task_run_full_pipeline(self, project_id: str):
    """Acquire the project-level Redis lock then dispatch the workflow chain.

    pipeline_lock() context manager would release the lock when apply_async()
    returns — well before the chain finishes — so we hold it explicitly.
    """
    from app.orchestration.locks import _get_redis

    logger.info("[Pipeline] Starting workflow for project %s (task=%s)", project_id, self.request.id)

    if not acquire_pipeline_lock(project_id, self.request.id):
        logger.warning("[Pipeline] Duplicate pipeline trigger for project %s — dropping", project_id)
        raise Ignore()

    try:
        _get_redis().set(f"pipeline:full_task:{project_id}", self.request.id, ex=10800)
    except Exception as e:
        logger.error("CRITICAL: Could not store pipeline task ID in Redis — lock release will fail: %s", e)

    build_pipeline_workflow(project_id).apply_async()
    logger.info("[Pipeline] Workflow chain dispatched for project %s", project_id)
