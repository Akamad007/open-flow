"""Stage 6b: full-story audio generation."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from sqlalchemy import select

from app.agents.asset_orchestrator import AssetOrchestrator
from app.config import settings
from app.database import async_session_factory
from app.models.asset import Asset, AssetStatus, AssetType
from app.models.audio_plan import AudioPlan
from app.models.render_job import JobStatus, JobType, RenderJob
from app.orchestration._common import (
    assert_project_active, get_audio_provider, get_video_provider,
)
from app.orchestration.episode_helpers import resolve_active_episode
from app.utils.audio_overlay import mix_two_audio_tracks
from app.utils.youtube_audio import download_audio

logger = logging.getLogger(__name__)


def _existing_error(asset: Asset) -> str:
    try:
        meta = json.loads(asset.metadata_json or "{}")
        return meta.get("error", "Audio file not generated")
    except (json.JSONDecodeError, TypeError):
        return "Audio file not generated"


async def _sum_scene_video_durations(db, episode_id) -> float:
    """Probe every completed scene_video for this episode and sum the durations.
    Run AFTER the video chord, so this is the ground-truth video length the
    narration should match. Returns 0.0 if no probed durations are available."""
    result = await db.execute(
        select(Asset.file_path)
        .where(Asset.episode_id == episode_id)
        .where(Asset.asset_type == AssetType.scene_video)
        .where(Asset.status == AssetStatus.complete)
    )
    paths = [p for (p,) in result.all() if p and Path(p).exists()]
    total = 0.0
    for p in paths:
        total += await _probe_audio_duration_ffprobe(Path(p))
    return total


async def _probe_audio_duration_ffprobe(audio_path: Path) -> float:
    """Read a media file's duration via ffprobe. Falls back to 0.0 on error."""
    import asyncio
    proc = await asyncio.create_subprocess_exec(
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(audio_path),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    out, _ = await proc.communicate()
    try:
        return float((out or b"").decode().strip() or "0")
    except ValueError:
        return 0.0


async def _mix_youtube_as_background(db, project, episode, narration_asset: Asset) -> None:
    """Download YT audio + mix it UNDER the narration in place, overwriting the
    narration_asset's file. Asset metadata gets an entry recording the source."""
    import asyncio
    url = episode.youtube_audio_url.strip()
    audio_dir = settings.storage_root / "audio" / str(project.id) / "episodes" / str(episode.id)
    yt_path = audio_dir / "youtube_bg.mp3"
    logger.info("Episode %s: downloading YT bg-music %s -> %s", episode.id, url, yt_path)
    yt_path = await asyncio.to_thread(download_audio, url, yt_path)

    narration_path = Path(narration_asset.file_path)
    mixed_path = audio_dir / f"{narration_path.stem}_mixed{narration_path.suffix}"
    await mix_two_audio_tracks(narration_path, yt_path, mixed_path, background_volume=0.30)

    narration_asset.file_path = str(mixed_path)
    try:
        existing = json.loads(narration_asset.metadata_json or "{}")
    except (json.JSONDecodeError, TypeError):
        existing = {}
    existing.update({
        "youtube_background_url": url,
        "youtube_background_file": str(yt_path),
        "background_volume": 0.30,
    })
    narration_asset.metadata_json = json.dumps(existing)


async def _generate_audio_from_youtube(db, project, episode, job: RenderJob) -> None:
    """Download YouTube audio and stash it as the episode's full_story_audio asset.
    The stitching stage will then overlay it on the silent scene concat."""
    import asyncio
    url = episode.youtube_audio_url.strip()
    audio_dir = settings.storage_root / "audio" / str(project.id) / "episodes" / str(episode.id)
    audio_path = audio_dir / "youtube.mp3"
    logger.info("Episode %s: downloading YouTube audio %s -> %s", episode.id, url, audio_path)

    job.payload_json = json.dumps({
        "source": "youtube",
        "episode_id": str(episode.id),
        "youtube_audio_url": url,
        "expected_duration_seconds": episode.youtube_audio_duration_seconds,
    })
    await db.flush()

    # yt-dlp is sync; run in a thread so we don't block the event loop.
    audio_path = await asyncio.to_thread(download_audio, url, audio_path)
    actual_dur = await _probe_audio_duration_ffprobe(audio_path)

    audio_asset = Asset(
        project_id=project.id,
        episode_id=episode.id,
        asset_type=AssetType.full_story_audio,
        file_path=str(audio_path),
        status=AssetStatus.complete,
        generation_provider="youtube",
        metadata_json=json.dumps({
            "source_url": url,
            "duration_seconds": actual_dur,
            "probed_duration_seconds": episode.youtube_audio_duration_seconds,
        }),
    )
    db.add(audio_asset)
    episode.final_audio_duration_seconds = actual_dur or episode.youtube_audio_duration_seconds
    project.final_audio_duration_seconds = episode.final_audio_duration_seconds
    job.status = JobStatus.complete
    job.result_json = json.dumps({
        "source": "youtube",
        "audio_path": str(audio_path),
        "duration_seconds": actual_dur,
    })


async def run(project_id: str) -> None:
    async with async_session_factory() as db:
        project = await assert_project_active(db, project_id, "audio_generation")
        episode = await resolve_active_episode(db, project_id)
        if episode is None:
            raise RuntimeError(f"No episode for project {project_id}")

        existing = await db.execute(
            select(Asset)
            .where(Asset.episode_id == episode.id)
            .where(Asset.asset_type == AssetType.full_story_audio)
            .where(Asset.status == AssetStatus.complete)
        )
        audio_asset = existing.scalars().first()
        if audio_asset and audio_asset.file_path and Path(audio_asset.file_path).exists():
            logger.info("Audio already generated at %s, skipping", audio_asset.file_path)
            await db.commit()
            return

        job = RenderJob(
            project_id=project.id, job_type=JobType.audio_generation,
            status=JobStatus.running,
        )
        db.add(job)
        await db.flush()

        # YouTube URL set: download the audio + register it as a full_story_audio
        # asset so the stitching stage overlays it like any other audio track.
        # skip_audio is force-enabled on YT-URL episodes by the API, but the
        # YT branch still wants to produce an audio asset, so we run before the
        # skip_audio short-circuit below.
        if (episode.youtube_audio_url or "").strip():
            try:
                await _generate_audio_from_youtube(db, project, episode, job)
                await db.commit()
                return
            except Exception as e:
                logger.exception("YouTube audio download failed")
                job.status = JobStatus.failed
                job.error_text = str(e)
                await db.commit()
                raise

        if episode.skip_audio:
            logger.info("Episode %s skip_audio=true — bypassing audio generation", episode.id)
            job.status = JobStatus.complete
            job.result_json = json.dumps({"skipped": True, "reason": "skip_audio"})
            await db.commit()
            return

        try:
            ap = (await db.execute(
                select(AudioPlan).where(AudioPlan.episode_id == episode.id)
            )).scalar_one_or_none()
            if not ap or not ap.full_story_narration_text:
                raise ValueError(
                    "No audio plan / narration text found for the active episode. "
                    "Ensure run_audio_planning completed successfully."
                )

            # Prefer the actual rendered video duration over the planned one —
            # this stage runs AFTER the video chord, so the scene clips on disk
            # are the ground truth. Falls back to the planner's estimate / the
            # episode target when no clips are probable.
            actual_video_dur = await _sum_scene_video_durations(db, episode.id)
            planned = (
                ap.total_estimated_audio_duration
                or episode.target_duration_seconds
                or project.total_target_duration_seconds
                or 60.0
            )
            target = actual_video_dur if actual_video_dur > 0 else planned
            logger.info(
                "Episode %s: narration target = %.2fs (actual_video=%.2fs, planned=%.2fs)",
                episode.id, target, actual_video_dur, planned,
            )

            job.payload_json = json.dumps({
                "provider": settings.audio_provider,
                "episode_id": str(episode.id),
                "target_duration_seconds": target,
                "actual_video_duration_seconds": actual_video_dur,
                "planned_duration_seconds": planned,
                "narration_chars": len(ap.full_story_narration_text or ""),
            })
            await db.flush()

            orchestrator = AssetOrchestrator(get_video_provider(), get_audio_provider())
            audio_asset = await orchestrator.generate_full_story_audio(
                ap.full_story_narration_text, project.id, target, db,
            )
            audio_asset.episode_id = episode.id

            ok = (
                audio_asset.status.value == "complete"
                and audio_asset.file_path
                and Path(audio_asset.file_path).exists()
            )
            if not ok:
                raise RuntimeError(f"Audio generation failed: {_existing_error(audio_asset)}")

            # Background-music mode: download YT and mix UNDER the narration so
            # the final full_story_audio asset is voice + bg music in one file.
            if (episode.youtube_audio_url or "").strip() and episode.youtube_as_background_music:
                await _mix_youtube_as_background(db, project, episode, audio_asset)

            episode.final_audio_duration_seconds = target
            project.final_audio_duration_seconds = target
            job.status = JobStatus.complete

        except Exception as e:
            logger.exception("Audio generation failed")
            job.status = JobStatus.failed
            job.error_text = str(e)
            await db.commit()
            raise

        await db.commit()
