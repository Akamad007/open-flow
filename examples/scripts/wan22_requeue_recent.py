#!/usr/bin/env python3
"""Re-trigger video regeneration for every wan22 project created in the
last 24h that already has prompts. One at a time, blocking on completion
before dispatching the next.

Why: after improvements to the wan22 provider (motion-aware steps/CFG,
face-distortion negatives, smart character-aware I2V seed picker) we want
to re-render the existing clip library on the new code path.

Usage: scripts/wan22_requeue_recent.py [--include-active] [--dry-run]
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from sqlalchemy import select, delete  # noqa: E402

from app.database import async_session_factory  # noqa: E402
from app.models import Project, Asset, Scene, ScenePrompt, RenderJob  # noqa: E402
from app.models.project import ProjectStatus  # noqa: E402
from app.models.asset import AssetType  # noqa: E402
from app.models.render_job import JobStatus  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("regen")

POLL_INTERVAL_S = 30
TIMEOUT_S = 90 * 60  # per-project ceiling


async def list_eligible(include_active: bool) -> list[tuple[str, str, str]]:
    """Returns [(project_id, title, status)] for wan22 projects created
    in the last 24h that have at least one scene prompt."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    async with async_session_factory() as db:
        projects = (await db.execute(
            select(Project)
            .where(Project.created_at >= cutoff)
            .where(Project.pipeline_profile == "wan22_text_only")
            .order_by(Project.created_at)
        )).scalars().all()
        eligible = []
        for p in projects:
            has_prompt = (await db.execute(
                select(ScenePrompt).join(Scene, Scene.id == ScenePrompt.scene_id)
                .where(Scene.project_id == p.id).limit(1)
            )).scalar_one_or_none()
            if not has_prompt:
                continue
            if p.status == ProjectStatus.complete:
                eligible.append((str(p.id), p.title, p.status.value))
            elif include_active and p.status != ProjectStatus.draft:
                eligible.append((str(p.id), p.title, p.status.value))
    return eligible


async def prep_project(project_id: str) -> None:
    """Delete existing scene_video assets, free stuck render jobs, flip
    project status to `generating` so the dispatch task's status guard
    accepts it."""
    async with async_session_factory() as db:
        proj = (await db.execute(
            select(Project).where(Project.id == project_id)
        )).scalar_one()
        # Delete scene video assets
        n_deleted = (await db.execute(
            delete(Asset).where(
                Asset.project_id == project_id,
                Asset.asset_type == AssetType.scene_video,
            )
        )).rowcount
        # Free any stuck render jobs so the dispatch guard releases
        n_jobs = (await db.execute(
            select(RenderJob).where(
                RenderJob.project_id == project_id,
                RenderJob.status.in_([JobStatus.queued, JobStatus.running]),
            )
        )).scalars().all()
        for j in n_jobs:
            j.status = JobStatus.failed
        proj.status = ProjectStatus.generating
        proj.final_video_path = None
        await db.commit()
        log.info(
            "  prep: deleted %d scene assets, freed %d render jobs, status=generating",
            n_deleted, len(n_jobs),
        )


async def poll_until_done(project_id: str, title: str) -> str:
    """Block until the project's status leaves the active set."""
    deadline = time.time() + TIMEOUT_S
    last_status = None
    while time.time() < deadline:
        async with async_session_factory() as db:
            proj = (await db.execute(
                select(Project).where(Project.id == project_id)
            )).scalar_one()
            status = proj.status.value
        if status != last_status:
            log.info("  [%s] status=%s", title, status)
            last_status = status
        if status in ("complete", "failed"):
            return status
        await asyncio.sleep(POLL_INTERVAL_S)
    return "timeout"


def dispatch(project_id: str) -> str:
    """Fire dispatch_video_chord with force=True. Returns the task id."""
    from celery_worker import celery_app
    res = celery_app.send_task(
        "storyvideo.dispatch_video_chord", args=[project_id, True],
    )
    return res.id


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="List what would be requeued, don't dispatch")
    ap.add_argument("--include-active", action="store_true",
                    help="Also requeue projects that are currently in a non-draft "
                         "active stage (default: skip them)")
    args = ap.parse_args()

    eligible = await list_eligible(args.include_active)
    log.info("Found %d eligible projects:", len(eligible))
    for pid, title, status in eligible:
        log.info("  - %s (status=%s, id=%s)", title, status, pid)

    if args.dry_run:
        log.info("Dry run — exiting.")
        return
    if not eligible:
        log.info("Nothing to do.")
        return

    log.info("Starting sequential regen — one at a time.")
    for i, (pid, title, _) in enumerate(eligible, 1):
        log.info("=" * 60)
        log.info("[%d/%d] regenerating %s", i, len(eligible), title)
        await prep_project(pid)
        task_id = dispatch(pid)
        log.info("  dispatched chord (task=%s) — polling for completion...", task_id)
        final = await poll_until_done(pid, title)
        log.info("[%d/%d] %s -> %s", i, len(eligible), title, final)
    log.info("=" * 60)
    log.info("All %d projects regenerated.", len(eligible))


if __name__ == "__main__":
    asyncio.run(main())
