"""Per-stage Celery tasks (analysis, planning, prompts, audio, review, image_pregen, audio_gen, stitch)."""

from __future__ import annotations

import logging

from celery.exceptions import Ignore

from app.orchestration.locks import stage_lock
from app.orchestration.tasks._app import celery_app
from app.orchestration.tasks._runtime import is_cancelled, run_async

logger = logging.getLogger(__name__)


def _retry_async(self, name: str, exc: Exception, base_countdown: int):
    if is_cancelled(exc):
        logger.info("%s: %s", name, exc)
        raise Ignore()
    logger.warning("%s attempt %d failed: %s", name, self.request.retries + 1, exc)
    raise self.retry(exc=exc, countdown=base_countdown * (2 ** self.request.retries))


@celery_app.task(name="storyvideo.analyze_story", bind=True, max_retries=3, default_retry_delay=15)
def task_analyze_story(self, project_id: str):
    from app.orchestration.pipeline import Pipeline
    with stage_lock(project_id, "analyze_story", self.request.id):
        try:
            run_async(Pipeline().run_story_analysis(project_id))
        except Ignore:
            raise
        except Exception as exc:
            _retry_async(self, "analyze_story", exc, 15)


@celery_app.task(name="storyvideo.plan_scenes", bind=True, max_retries=3, default_retry_delay=15)
def task_plan_scenes(self, project_id: str):
    from app.orchestration.pipeline import Pipeline
    with stage_lock(project_id, "plan_scenes", self.request.id):
        try:
            run_async(Pipeline().run_scene_planning(project_id))
        except Ignore:
            raise
        except Exception as exc:
            _retry_async(self, "plan_scenes", exc, 15)


@celery_app.task(name="storyvideo.generate_prompts", bind=True, max_retries=3, default_retry_delay=15)
def task_generate_prompts(self, project_id: str):
    from app.orchestration.pipeline import Pipeline
    with stage_lock(project_id, "generate_prompts", self.request.id):
        try:
            run_async(Pipeline().run_prompt_generation(project_id))
        except Ignore:
            raise
        except Exception as exc:
            _retry_async(self, "generate_prompts", exc, 15)


@celery_app.task(name="storyvideo.plan_audio", bind=True, max_retries=3, default_retry_delay=15)
def task_plan_audio(self, project_id: str):
    from app.orchestration.pipeline import Pipeline
    with stage_lock(project_id, "plan_audio", self.request.id):
        try:
            run_async(Pipeline().run_audio_planning(project_id))
        except Ignore:
            raise
        except Exception as exc:
            _retry_async(self, "plan_audio", exc, 15)


@celery_app.task(name="storyvideo.review_consistency", bind=True, max_retries=2, default_retry_delay=10)
def task_review_consistency(self, project_id: str):
    """Stage 5: NON-FATAL — failure advances project to image_pregen."""
    from app.orchestration.pipeline import Pipeline
    with stage_lock(project_id, "review_consistency", self.request.id):
        try:
            run_async(Pipeline().run_consistency_review(project_id))
        except Ignore:
            raise
        except Exception as exc:
            if is_cancelled(exc):
                logger.info("review_consistency: %s", exc)
                raise Ignore()
            logger.warning("review_consistency failed (non-fatal): %s", exc)


@celery_app.task(name="storyvideo.pregen_images", bind=True, max_retries=2, default_retry_delay=60)
def task_pregen_images(self, project_id: str):
    """Stage 5.5: FATAL — videos cannot be generated without conditioning images.
    Profile-driven (F-WAN-PHANTOM iter8): the project's pipeline_profile
    decides if image_pregen runs. LTX text_only skips it (text-only). Phantom
    profiles need character reference images at minimum — pregen runs."""
    from app.orchestration.pipeline import Pipeline
    from app.orchestration.profiles import get_profile
    from app.database import async_session_factory
    from app.models.project import Project as _Project
    import asyncio as _asyncio
    import uuid as _uuid

    async def _profile_for():
        async with async_session_factory() as db:
            proj = await db.get(_Project, _uuid.UUID(project_id))
            return get_profile(proj.pipeline_profile if proj else None)
    profile = run_async(_profile_for())

    needs_pregen = profile.image_pregen_enabled or profile.canonical_portrait_enabled
    if not needs_pregen:
        logger.info(
            "pregen_images: SKIPPED for project %s (profile %s — text-only)",
            project_id, profile.name,
        )
        from app.orchestration._common import (
            assert_project_active, ProjectCancelledError,
        )
        from app.models.project import ProjectStatus

        async def _advance():
            async with async_session_factory() as db:
                try:
                    proj = await assert_project_active(db, project_id, "pregen_images_skip")
                except ProjectCancelledError:
                    return
                # SKIPPED path → advance to `generating` so the project status
                # reflects the actual next phase (scene-gen). Leaving it at
                # `image_pregen` made the watchdog force-fail multi-scene LTX
                # projects after 30 min because project.updated_at hadn't moved.
                proj.status = ProjectStatus.generating
                await db.commit()
        run_async(_advance())
        return
    with stage_lock(project_id, "pregen_images", self.request.id, ttl=7200):
        try:
            run_async(Pipeline().run_image_pregen(project_id))
        except Ignore:
            raise
        except Exception as exc:
            if is_cancelled(exc):
                logger.info("pregen_images: %s", exc)
                raise Ignore()
            logger.error(
                "pregen_images FAILED (attempt %d/%d): %s",
                self.request.retries + 1, self.max_retries + 1, exc,
            )
            raise self.retry(exc=exc, countdown=60 * (self.request.retries + 1))


@celery_app.task(name="storyvideo.generate_audio", bind=True, max_retries=2, default_retry_delay=30)
def task_generate_audio(self, project_id: str):
    from app.orchestration.pipeline import Pipeline
    with stage_lock(project_id, "generate_audio", self.request.id, ttl=1800):
        try:
            run_async(Pipeline().run_audio_generation(project_id))
        except Ignore:
            raise
        except Exception as exc:
            _retry_async(self, "generate_audio", exc, 30)


@celery_app.task(name="storyvideo.stitch", bind=True, max_retries=2, default_retry_delay=10)
def task_stitch(self, project_id: str):
    from app.orchestration.pipeline import Pipeline
    with stage_lock(project_id, "stitch", self.request.id):
        try:
            run_async(Pipeline().run_stitching(project_id))
        except Ignore:
            raise
        except Exception as exc:
            _retry_async(self, "stitch", exc, 10)


async def _redo_all_prompts(project_id: str) -> dict:
    """Run analysis → planning → prompts for EVERY episode, no rendering.
    Per-episode try/except so one bad episode doesn't abort the batch."""
    import uuid as _uuid

    from sqlalchemy import select

    from app.database import async_session_factory
    from app.models.episode import Episode
    from app.models.project import Project, ProjectStatus
    from app.orchestration.stages import (
        prompt_generation, scene_planning, story_analysis,
    )

    async with async_session_factory() as db:
        project = await db.get(Project, _uuid.UUID(project_id))
        project.status = ProjectStatus.analyzing  # keep stages from short-circuiting
        ep_ids = [str(e.id) for e in (await db.execute(
            select(Episode).where(Episode.project_id == project.id)
            .order_by(Episode.order_index)
        )).scalars().all()]
        await db.commit()

    done, failed = 0, []
    for eid in ep_ids:
        try:
            await story_analysis.run(project_id, episode_id=eid)
            await scene_planning.run(project_id, episode_id=eid)
            await prompt_generation.run(project_id, episode_id=eid)
            done += 1
        except Exception as exc:
            logger.exception("redo_all_prompts: episode %s failed: %s", eid, exc)
            failed.append(eid)
        logger.info("redo_all_prompts: %d/%d done (%d failed)", done, len(ep_ids), len(failed))
    return {"prompted": done, "failed": failed}


@celery_app.task(name="storyvideo.redo_all_prompts", bind=True, max_retries=0)
def task_redo_all_prompts(self, project_id: str):
    with stage_lock(project_id, "redo_all_prompts", self.request.id):
        result = run_async(_redo_all_prompts(project_id))
        logger.info("redo_all_prompts complete for %s: %s", project_id, result)
        return result
