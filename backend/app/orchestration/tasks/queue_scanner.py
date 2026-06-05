"""Queue scanner used by `scripts/queue_scanner.py` (standalone daemon).

Lets users enqueue many projects at once. The single-concurrency celery
worker (one GPU task at a time) chugs through them serially. If celery
crashes mid-pipeline and a project gets stuck in an active status, the
watchdog half of this scan force-fails it after `STUCK_THRESHOLD_S` of
no `updated_at` movement so the queue keeps draining.

Decoupled from celery on purpose: putting the scanner *inside* celery
means a long-running pipeline task (40+ min Phantom-Wan scene) blocks
the scan from firing.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.database import async_session_factory
from app.models.asset import Asset, AssetType
from app.models.episode import Episode, EpisodeStatus
from app.models.project import Project, ProjectStatus
from app.models.render_job import JobStatus, JobType, RenderJob
from app.utils.gpu_routing import assign_project_gpu, assigned_gpu, pick_free_gpu

logger = logging.getLogger(__name__)

ACTIVE_STATUSES = (
    ProjectStatus.analyzing, ProjectStatus.planning,
    ProjectStatus.prompting, ProjectStatus.audio_planning,
    ProjectStatus.reviewing, ProjectStatus.image_pregen,
    ProjectStatus.generating, ProjectStatus.stitching,
)
# Stages that occupy the `cpu` worker (LLM/prompt-side). A new draft can be
# dispatched only if NO project is currently in one of these — its chain
# would otherwise compete with the LLM-side stages of the active one.
CPU_BUSY_STATUSES = (
    ProjectStatus.analyzing, ProjectStatus.planning,
    ProjectStatus.prompting, ProjectStatus.audio_planning,
    ProjectStatus.reviewing,
)
# Stages on the `gpu` worker — when the active project is here, the cpu
# worker is idle and a new draft can start its prompt-side stages in
# parallel.
GPU_BUSY_STATUSES = (
    ProjectStatus.image_pregen, ProjectStatus.generating, ProjectStatus.stitching,
)
STUCK_THRESHOLD_S = 14400  # 4 hr of no updated_at change → fail it
ORPHAN_RESUME_S = 300  # 5 min of no movement + no celery lock → re-dispatch
INTER_PROJECT_COOLDOWN_S = 30  # GPU breather between projects (mitigates GPU bus-fault risk)
# LTX scene-gen at 80 steps × 1280×768 runs ~14 min/scene; a 5-scene project
# could otherwise blow the watchdog between scene 1 and scene 2 if project.updated_at
# isn't bumped per-scene. Scene tasks DO bump it now (see scene_video.generate_single),
# but the larger threshold is a safety margin.


def _has_redis_stage_lock(project_id) -> bool:
    """True if any pipeline stage lock exists for this project in Redis.
    Used to distinguish 'actively-running but slow' from 'orphaned'."""
    try:
        from app.orchestration.locks import _get_redis
        r = _get_redis()
        return any(True for _ in r.scan_iter(f"pipeline:stage:{project_id}:*", count=10))
    except Exception:
        return False


async def scan_and_dispatch() -> str:
    """One pass of the scanner. Returns a short status string."""
    async with async_session_factory() as db:
        active = (await db.execute(
            select(Project).where(Project.status.in_(ACTIVE_STATUSES))
            .order_by(Project.updated_at.asc())
        )).scalars().all()

        # Heartbeat / auto-corrector. The OLD celery worker doesn't refresh
        # project.updated_at per scene, so a long video chord can look idle to
        # the watchdog even though scenes are actively completing. For each
        # active project, check if a scene_video asset was completed since the
        # last scan — if so, bump updated_at, and flip image_pregen→generating
        # when a video chord is live.
        now = datetime.now(timezone.utc)
        any_changed = False
        for p in active:
            running_video = (await db.execute(
                select(RenderJob.id).where(
                    RenderJob.project_id == p.id,
                    RenderJob.job_type == JobType.video_generation,
                    RenderJob.status == JobStatus.running,
                ).limit(1)
            )).scalar_one_or_none()
            latest_asset_at = (await db.execute(
                select(Asset.created_at).where(
                    Asset.project_id == p.id,
                    Asset.asset_type == AssetType.scene_video,
                ).order_by(Asset.created_at.desc()).limit(1)
            )).scalar_one_or_none()
            if p.status == ProjectStatus.image_pregen and running_video:
                logger.info(
                    "queue_scanner: project %s auto-advanced image_pregen → generating",
                    p.id,
                )
                p.status = ProjectStatus.generating
                p.updated_at = now
                any_changed = True
                continue
            if (running_video and latest_asset_at
                    and (not p.updated_at or latest_asset_at > p.updated_at)):
                p.updated_at = latest_asset_at
                any_changed = True
        if any_changed:
            await db.commit()

        # Watchdog: any active project sitting silent past threshold gets failed.
        stale_cut = now - timedelta(seconds=STUCK_THRESHOLD_S)
        for p in active:
            if p.updated_at and p.updated_at < stale_cut:
                logger.warning(
                    "queue_scanner: project %s stuck at %s for >%ds — force-failing",
                    p.id, p.status.value, STUCK_THRESHOLD_S,
                )
                p.status = ProjectStatus.failed
        if any(p.status == ProjectStatus.failed for p in active):
            await db.commit()
            active = [p for p in active if p.status != ProjectStatus.failed]

        # Orphan recovery: active project that hasn't moved in ORPHAN_RESUME_S
        # AND has no Redis stage lock = celery died mid-pipeline. Re-dispatch
        # full_pipeline (idempotent — resumes from current stage).
        orphan_cut = now - timedelta(seconds=ORPHAN_RESUME_S)
        for p in active:
            if (p.updated_at and p.updated_at < orphan_cut
                    and not _has_redis_stage_lock(p.id)):
                logger.warning(
                    "queue_scanner: project %s orphaned in %s for >%ds (no lock) — resuming",
                    p.id, p.status.value, ORPHAN_RESUME_S,
                )
                p.updated_at = now
                await db.commit()
                # Keep the orphan on its assigned card (refresh TTL / re-pin
                # after a redis flush) so resume lands on the same GPU.
                assign_project_gpu(str(p.id), assigned_gpu(str(p.id)))
                from app.orchestration.tasks.full_pipeline import task_run_full_pipeline
                task_run_full_pipeline.delay(str(p.id))
                return f"resumed orphan {p.id} ({p.status.value}) → gpu{assigned_gpu(str(p.id))}"

        # Single-flight on the cpu worker: if any project is currently in an
        # LLM stage, don't dispatch a new draft (would race the same worker).
        # If ALL active projects are in GPU stages, the cpu worker is idle so
        # we can dispatch the next draft to fill it.
        cpu_busy = [p for p in active if p.status in CPU_BUSY_STATUSES]
        if cpu_busy:
            return f"active: {cpu_busy[0].id} ({cpu_busy[0].status.value})"
        if active:
            logger.info(
                "queue_scanner: %d active project(s) in GPU stage — cpu worker is "
                "free, dispatching next draft in parallel",
                len(active),
            )

        # Pick the oldest project that is draft AND has at least one draft
        # episode with story_text OR theme_hint. Story_text-only projects (no
        # episode rows from legacy data) still qualify because the migration
        # backfilled Episode 0 for every existing project.
        ep_subq = (
            select(Episode.project_id)
            .where(Episode.status == EpisodeStatus.draft)
            .where(
                (Episode.original_story_text != "")
                | (Episode.theme_hint.isnot(None))
            )
            .scalar_subquery()
        )
        draft = (await db.execute(
            select(Project).where(Project.status == ProjectStatus.draft)
            .where(Project.id.in_(ep_subq))
            .order_by(Project.created_at.asc()).limit(1)
        )).scalar_one_or_none()
        if not draft:
            return "queue empty"

        # GPU breather: hold off dispatch until INTER_PROJECT_COOLDOWN_S has
        # passed since the last project finished. Mitigates GPU bus-fault risk
        # from back-to-back model load/unload churn under cpu_offload.
        last_finished = (await db.execute(
            select(Project.updated_at).where(
                Project.status.in_([ProjectStatus.complete, ProjectStatus.failed])
            ).order_by(Project.updated_at.desc()).limit(1)
        )).scalar_one_or_none()
        if last_finished:
            since = (now - last_finished).total_seconds()
            if since < INTER_PROJECT_COOLDOWN_S:
                return f"cooldown {INTER_PROJECT_COOLDOWN_S - int(since)}s before next dispatch"

        # Pin the new project to a free GPU so it renders in parallel with
        # any project already running on another card. No free card → wait.
        gpu = pick_free_gpu([str(p.id) for p in active])
        if gpu is None:
            return "all GPUs busy"
        assign_project_gpu(str(draft.id), gpu)
        draft.status = ProjectStatus.analyzing
        await db.commit()
        from app.orchestration.tasks.full_pipeline import task_run_full_pipeline
        task_run_full_pipeline.delay(str(draft.id))
        return f"dispatched draft {draft.id} → gpu{gpu}"
