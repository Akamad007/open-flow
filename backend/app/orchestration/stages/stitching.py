"""Stage 7: stitch scene videos + full-story audio into a final render."""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path

from sqlalchemy import select

from app.agents.stitching_agent import StitchingAgent
from app.database import async_session_factory
from app.models.asset import Asset, AssetStatus, AssetType
from app.models.episode import Episode, EpisodeStatus
from app.models.project import Project, ProjectStatus
from app.models.render_job import JobStatus, JobType, RenderJob
from app.models.scene import Scene
from app.orchestration._common import assert_project_active, get_stitching_provider
from app.orchestration.episode_helpers import resolve_active_episode

logger = logging.getLogger(__name__)


async def _collect_stitch_inputs(db, episode_id, skip_audio: bool = False) -> tuple[bool, str, dict]:
    """Return (ok, error_msg, payload) describing stitch readiness for an episode."""
    scene_rows = (await db.execute(
        select(Scene.order_index)
        .where(Scene.episode_id == episode_id)
        .order_by(Scene.order_index)
    )).scalars().all()
    scene_count = len(scene_rows)

    scene_ids_subq = select(Scene.id).where(Scene.episode_id == episode_id).subquery()
    video_rows = (await db.execute(
        select(Asset)
        .where(Asset.scene_id.in_(select(scene_ids_subq.c.id)))
        .where(Asset.asset_type == AssetType.scene_video)
        .where(Asset.status == AssetStatus.complete)
    )).scalars().all()
    completed_scene_ids = {a.scene_id for a in video_rows if a.scene_id is not None}

    scenes_full = (await db.execute(
        select(Scene).where(Scene.episode_id == episode_id).order_by(Scene.order_index)
    )).scalars().all()
    missing_indices = [s.order_index for s in scenes_full if s.id not in completed_scene_ids]
    videos_complete = scene_count - len(missing_indices)

    audio_rows = (await db.execute(
        select(Asset)
        .where(Asset.episode_id == episode_id)
        .where(Asset.asset_type == AssetType.full_story_audio)
        .where(Asset.status == AssetStatus.complete)
    )).scalars().all()
    audio_complete = len(audio_rows)

    payload = {
        "scene_videos_expected": scene_count,
        "scene_videos_complete": videos_complete,
        "audio_assets_complete": audio_complete,
    }
    if videos_complete < scene_count:
        return False, (
            f"Cannot stitch: {videos_complete}/{scene_count} scene videos complete. "
            f"Missing scenes: {missing_indices}"
        ), payload
    if not skip_audio and audio_complete != 1:
        return False, (
            f"Cannot stitch: expected 1 complete full_story_audio asset, "
            f"found {audio_complete}."
        ), payload
    return True, "", payload


async def _verify_files_on_disk(db, episode_id, skip_audio: bool = False) -> None:
    scene_ids_subq = select(Scene.id).where(Scene.episode_id == episode_id).subquery()
    videos = (await db.execute(
        select(Asset)
        .where(Asset.scene_id.in_(select(scene_ids_subq.c.id)))
        .where(Asset.asset_type == AssetType.scene_video)
        .where(Asset.status == AssetStatus.complete)
    )).scalars().all()
    missing = [a for a in videos if not a.file_path or not Path(a.file_path).exists()]
    if missing and len(missing) == len(videos):
        raise RuntimeError(
            f"run_stitching: all {len(missing)} scene video file(s) missing on disk."
        )
    if missing:
        logger.warning("%d/%d scene video file(s) missing on disk", len(missing), len(videos))

    if skip_audio:
        return
    audio = (await db.execute(
        select(Asset)
        .where(Asset.episode_id == episode_id)
        .where(Asset.asset_type == AssetType.full_story_audio)
        .where(Asset.status == AssetStatus.complete)
    )).scalars().first()
    if not audio or not audio.file_path or not Path(audio.file_path).exists():
        raise RuntimeError("run_stitching: audio file not found on disk.")


async def run(project_id: str, episode_id: str | None = None) -> None:
    async with async_session_factory() as db:
        if episode_id:
            # Episode-scoped stitch: target THIS episode regardless of which is
            # "active" or the project's status (lets us stitch a second episode
            # after the first marked the project complete).
            project = await db.get(Project, uuid.UUID(project_id))
            if project is None:
                raise RuntimeError(f"Project {project_id} not found")
            episode = await db.get(Episode, uuid.UUID(episode_id))
            if episode is None or str(episode.project_id) != project_id:
                raise RuntimeError(f"Episode {episode_id} not in project {project_id}")
        else:
            project = await assert_project_active(db, project_id, "stitching")
            episode = await resolve_active_episode(db, project_id)
            if episode is None:
                raise RuntimeError(f"No episode for project {project_id}")

        job = RenderJob(
            project_id=project.id, job_type=JobType.stitching,
            status=JobStatus.running,
        )
        db.add(job)
        episode.status = EpisodeStatus.stitching
        project.status = ProjectStatus.stitching
        await db.flush()

        try:
            # Effective skip-audio: a YouTube-sourced audio asset exists by
            # this point (audio_gen downloaded it), so even though skip_audio
            # was force-true on the episode, we want to overlay normally.
            effective_skip_audio = bool(episode.skip_audio) and not (episode.youtube_audio_url or "").strip()
            ok, msg, payload = await _collect_stitch_inputs(
                db, episode.id, skip_audio=effective_skip_audio,
            )
            payload["episode_id"] = str(episode.id)
            payload["skip_audio"] = effective_skip_audio
            payload["youtube_audio_url"] = episode.youtube_audio_url or None
            job.payload_json = json.dumps(payload)
            if not ok:
                raise RuntimeError(msg)
            await _verify_files_on_disk(db, episode.id, skip_audio=effective_skip_audio)

            agent = StitchingAgent(get_stitching_provider())
            render_asset = await agent.stitch_project(
                project.id, db, episode_id=episode.id, skip_audio=effective_skip_audio,
            )

            if render_asset.status.value == "complete":
                render_asset.episode_id = episode.id
                episode.final_video_path = render_asset.file_path
                episode.status = EpisodeStatus.complete
                project.status = ProjectStatus.complete
                job.status = JobStatus.complete
            else:
                episode.status = EpisodeStatus.failed
                project.status = ProjectStatus.failed
                job.status = JobStatus.failed

        except Exception as e:
            logger.exception("Stitching failed")
            job.status = JobStatus.failed
            job.error_text = str(e)
            episode.status = EpisodeStatus.failed
            project.status = ProjectStatus.failed
            await db.commit()
            raise

        await db.commit()
