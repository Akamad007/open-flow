"""Stage 5.5: SD 3.5 image pre-gen — character portraits, backgrounds, action stills."""

from __future__ import annotations

import json
import logging

from sqlalchemy import func, select

from app.agents.image_pregen_agent import ImagePreGenAgent
from app.config import settings
from app.database import async_session_factory
from app.models.asset import Asset, AssetStatus, AssetType
from app.models.character import Character
from app.models.episode import EpisodeStatus
from app.models.location import Location
from app.models.project import ProjectStatus
from app.models.render_job import JobStatus, JobType, RenderJob
from app.models.scene import Scene
from app.orchestration._common import (
    assert_project_active, get_identity_image_provider, get_image_provider, get_llm_provider,
)
from app.orchestration.episode_helpers import resolve_active_episode

logger = logging.getLogger(__name__)


async def _all_scenes_have_action_stills(db, episode_id) -> bool:
    total = await db.scalar(
        select(func.count(Scene.id)).where(Scene.episode_id == episode_id)
    )
    scene_ids_subq = select(Scene.id).where(Scene.episode_id == episode_id).subquery()
    with_action = await db.scalar(
        select(func.count(Asset.scene_id.distinct()))
        .where(Asset.scene_id.in_(select(scene_ids_subq.c.id)))
        .where(Asset.asset_type == AssetType.scene_action_seq)
        .where(Asset.status == AssetStatus.complete)
    )
    return bool(total and with_action and with_action >= total)


async def _clear_stale_image_paths(db, project_id) -> int:
    """Drop reference paths that point at another project's storage dir."""
    expected_char_dir = str(settings.storage_root / "characters" / str(project_id))
    expected_bg_dir = str(settings.storage_root / "backgrounds" / str(project_id))
    cleared = 0

    chars = await db.execute(select(Character).where(Character.project_id == project_id))
    for char in chars.scalars().all():
        if char.reference_image_path and expected_char_dir not in str(char.reference_image_path):
            logger.info(
                "Clearing stale portrait for '%s' (was: %s)",
                char.canonical_name, char.reference_image_path,
            )
            char.reference_image_path = None
            cleared += 1

    locs = await db.execute(select(Location).where(Location.project_id == project_id))
    for loc in locs.scalars().all():
        if loc.reference_image_path and expected_bg_dir not in str(loc.reference_image_path):
            logger.info(
                "Clearing stale background for '%s' (was: %s)",
                loc.name, loc.reference_image_path,
            )
            loc.reference_image_path = None
            cleared += 1

    return cleared


async def run(project_id: str) -> None:
    async with async_session_factory() as db:
        project = await assert_project_active(db, project_id, "image_pregen")
        episode = await resolve_active_episode(db, project_id)
        if episode is None:
            raise RuntimeError(f"No episode for project {project_id}")

        if await _all_scenes_have_action_stills(db, episode.id):
            logger.info("All scenes already have action stills, skipping image_pregen")
            episode.status = EpisodeStatus.generating
            project.status = ProjectStatus.generating
            await db.commit()
            return

        job = RenderJob(
            project_id=project.id, job_type=JobType.image_pregen,
            status=JobStatus.running,
        )
        db.add(job)
        episode.status = EpisodeStatus.image_pregen
        project.status = ProjectStatus.image_pregen
        await db.flush()

        try:
            cleared = await _clear_stale_image_paths(db, project.id)
            if cleared:
                logger.info("Cleared %d stale image path(s) before image_pregen", cleared)
                await db.flush()

            num_chars = await db.scalar(
                select(func.count(Character.id)).where(Character.project_id == project.id)
            ) or 0
            num_locs = await db.scalar(
                select(func.count(Location.id)).where(Location.project_id == project.id)
            ) or 0
            num_scenes = await db.scalar(
                select(func.count(Scene.id)).where(Scene.episode_id == episode.id)
            ) or 0
            job.payload_json = json.dumps({
                "provider": settings.image_provider,
                "sd35_steps": settings.sd35_steps,
                "num_characters": num_chars,
                "num_locations": num_locs,
                "num_scenes": num_scenes,
            })
            await db.flush()

            agent = ImagePreGenAgent(
                image_provider=get_image_provider(),
                llm=get_llm_provider(),
                identity_provider=get_identity_image_provider(),
            )
            result = await agent.run(context={
                "project_id": str(project_id),
                "db": db,
                "story_summary": project.story_summary or "",
            })

            job.status = JobStatus.complete if result.success else JobStatus.failed
            job.result_json = json.dumps(result.data or {})
            if result.errors:
                job.error_text = "; ".join(result.errors)
                raise RuntimeError(
                    f"Image pre-generation failed with {len(result.errors)} error(s): "
                    + "; ".join(result.errors)
                )

        except Exception as e:
            logger.exception("Image pre-generation failed")
            job.status = JobStatus.failed
            job.error_text = str(e)
            await db.commit()
            raise
        finally:
            # Free InstantID daemon VRAM before LTX runs — both fight for
            # cuda:0 and a resident SDXL+CN stack (~5-10 GiB) collides with
            # the LTX FP8 transformer (~13 GiB) on the 16 GiB card.
            try:
                from app.utils.daemon_pool import get_instantid_manager
                mgr = get_instantid_manager()
                if mgr is not None:
                    mgr.shutdown_all()
                    logger.info("InstantID daemons shut down (freed VRAM for LTX)")
            except Exception as se:
                logger.warning("Failed to shut down InstantID daemons: %s", se)

        await db.commit()
