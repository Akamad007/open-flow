"""Per-scene video task + chord dispatch + chord callback."""

from __future__ import annotations

import logging
import time

from celery import chain, chord, group
from celery.exceptions import Ignore

from app.orchestration.locks import stage_lock
from app.orchestration.tasks._app import celery_app
from app.orchestration.tasks._runtime import is_cancelled, run_async

logger = logging.getLogger(__name__)

# Cool-down between consecutive scene_video tasks. Gives Wan22's CUDA/VRAM
# state time to fully release before the next scene loads the pipe — prevents
# OOM ladder + lets GPU thermals settle on long chord runs.
SCENE_VIDEO_COOLDOWN_S = 30


@celery_app.task(name="storyvideo.generate_scene_video", bind=True, max_retries=3, default_retry_delay=60)
def task_generate_scene_video(self, project_id: str, scene_id: str, force: bool = False):
    """Generate one scene's video. Returns a result dict on final-retry failure
    (instead of raising) so the chord callback still fires for partial success."""
    from app.orchestration.pipeline import Pipeline

    lock_key = f"scene_video:{scene_id}"
    with stage_lock(project_id, lock_key, self.request.id, ttl=1800):
        try:
            result = run_async(Pipeline().generate_single_scene(project_id, scene_id, force=force))
            logger.info("Scene %s generated: %s", scene_id, result.get("status"))
            # Cooldown only after a real Wan22 render — skip/cancel paths
            # used zero GPU, no thermal/VRAM settle needed.
            if result.get("status") not in ("skipped", "cancelled"):
                logger.info("Cooling down %ds before next scene...", SCENE_VIDEO_COOLDOWN_S)
                time.sleep(SCENE_VIDEO_COOLDOWN_S)
            return result
        except Ignore:
            raise
        except Exception as exc:
            if is_cancelled(exc):
                logger.info("scene_video %s: project cancelled, skipping", scene_id)
                return {"scene_id": scene_id, "status": "cancelled"}
            logger.warning(
                "scene_video %s attempt %d/%d failed: %s",
                scene_id, self.request.retries + 1, self.max_retries + 1, exc,
            )
            if self.request.retries < self.max_retries:
                raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))
            logger.error(
                "scene_video %s exhausted all %d retries — returning failure dict",
                scene_id, self.max_retries + 1,
            )
            return {"scene_id": scene_id, "status": "failed", "error": str(exc)}


@celery_app.task(name="storyvideo.dispatch_video_chord", bind=True, max_retries=2, default_retry_delay=10)
def task_dispatch_video_chord(self, project_id: str, force: bool = False):
    """Reads scene IDs, builds and dispatches the parallel video generation chord."""
    from app.orchestration.pipeline import Pipeline

    with stage_lock(project_id, "dispatch_video_chord", self.request.id):
        try:
            scene_ids = run_async(Pipeline().get_scene_ids_with_prompts(project_id))
            if not scene_ids:
                raise RuntimeError(f"No scenes with prompts for project {project_id}")

            logger.info(
                "Dispatching video chord for %d scenes (project=%s, force=%s)",
                len(scene_ids), project_id, force,
            )

            import os
            callback = task_finalize_and_continue.si([], project_id)
            if os.environ.get("PARALLEL_SCENES") == "1" and len(scene_ids) > 1:
                # Fan all scenes out as a parallel chord so every GPU worker
                # renders a scene at once (scenes are independent in this mode).
                header = group(
                    task_generate_scene_video.si(project_id, sid, force) for sid in scene_ids
                )
                logger.info("Parallel scene fan-out: %d scenes across all GPUs", len(scene_ids))
                chord(header)(callback)
            else:
                # Sequential chain — preserves scene-to-scene I2V continuity.
                video_chain = chain(
                    task_generate_scene_video.si(project_id, sid, force) for sid in scene_ids
                )
                (video_chain | callback).apply_async()

        except Ignore:
            raise
        except Exception as exc:
            logger.error("dispatch_video_chord failed: %s", exc)
            raise self.retry(exc=exc, countdown=10)


@celery_app.task(name="storyvideo.finalize_and_continue", bind=True, max_retries=1)
def task_finalize_and_continue(self, results: list, project_id: str):
    """Chord callback — validates scene results, kicks off audio → stitch → cleanup."""
    from app.orchestration.pipeline import Pipeline
    from app.orchestration.tasks.cleanup import (
        release_pipeline_lock_for_project,
        task_pipeline_cleanup,
    )
    from app.orchestration.tasks.eval_task import task_evaluate_project
    from app.orchestration.tasks.stage_tasks import (
        task_generate_audio, task_plan_audio, task_stitch,
    )

    try:
        run_async(Pipeline().finalize_videos(project_id, results or []))
    except RuntimeError as exc:
        logger.error("finalize_and_continue: %s", exc)
        release_pipeline_lock_for_project(project_id)
        raise

    logger.info("Video chord complete for project %s — planning audio against actual rendered duration, then generating + stitching", project_id)
    chain(
        task_plan_audio.si(project_id),
        task_generate_audio.si(project_id),
        task_stitch.si(project_id),
        task_evaluate_project.si(project_id),
        task_pipeline_cleanup.si(project_id),
    ).apply_async()
