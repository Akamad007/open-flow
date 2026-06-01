"""Episodes API — multi-episode support inside a project."""

from __future__ import annotations

import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.asset import Asset, AssetStatus, AssetType
from app.models.episode import Episode, EpisodeStatus
from app.models.project import Project, ProjectStatus
from app.models.scene import Scene
from app.schemas.episode import (
    EpisodeCreate,
    EpisodeFromTheme,
    EpisodeList,
    EpisodeRead,
    EpisodeUpdate,
)
from app.utils.audio_overlay import overlay_audio_on_video
from app.utils.youtube_audio import (
    YouTubeAudioError,
    download_audio,
    is_youtube_url,
    probe_duration,
)

router = APIRouter(tags=["episodes"])


async def _next_order_index(db: AsyncSession, project_id: uuid.UUID) -> int:
    n = await db.scalar(
        select(func.coalesce(func.max(Episode.order_index), -1) + 1)
        .where(Episode.project_id == project_id)
    )
    return int(n or 0)


async def _scene_count_for(db: AsyncSession, episode_id: uuid.UUID) -> int:
    return await db.scalar(
        select(func.count(Scene.id)).where(Scene.episode_id == episode_id)
    ) or 0


async def _maybe_dispatch_pipeline(db: AsyncSession, project: Project) -> None:
    """Mark project draft so the queue scanner picks it up; commit happens after."""
    project.status = ProjectStatus.draft
    if not (project.original_story_text or "").strip():
        # Make scanner's NOT NULL filter pass — story_analysis reads from the
        # active episode, not from the project, but the scanner still gates on
        # project.original_story_text != ''.
        project.original_story_text = " "


@router.get("/projects/{project_id}/episodes", response_model=List[EpisodeList])
async def list_episodes(project_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(
        select(Episode).where(Episode.project_id == project_id)
        .order_by(Episode.order_index)
    )).scalars().all()
    out = []
    for ep in rows:
        item = EpisodeList.model_validate(ep)
        item.scene_count = await _scene_count_for(db, ep.id)
        out.append(item)
    return out


def _probe_youtube_or_400(url: str) -> float:
    if not is_youtube_url(url):
        raise HTTPException(
            status_code=400,
            detail=f"Not a YouTube URL: {url!r}",
        )
    try:
        return probe_duration(url)
    except YouTubeAudioError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/projects/{project_id}/episodes", response_model=EpisodeRead, status_code=201)
async def create_episode(
    project_id: uuid.UUID, data: EpisodeCreate, db: AsyncSession = Depends(get_db),
):
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    order_index = await _next_order_index(db, project_id)
    title = data.title or f"Episode {order_index + 1}"

    # YouTube URL: probe duration upfront and use it as target. In REPLACE mode
    # (the default) force skip_audio so audio_planning bypasses and the YT track
    # IS the audio. In BACKGROUND-MUSIC mode keep narration ON; audio_generation
    # mixes narration + YT in one file.
    yt_url = (data.youtube_audio_url or "").strip() or None
    yt_dur: float | None = None
    target_duration = data.target_duration_seconds
    skip_audio_effective = data.skip_audio
    yt_bg = bool(data.youtube_as_background_music)
    if yt_url:
        yt_dur = _probe_youtube_or_400(yt_url)
        target_duration = yt_dur
        if not yt_bg:
            skip_audio_effective = True

    ep = Episode(
        project_id=project_id,
        order_index=order_index,
        title=title,
        status=EpisodeStatus.draft,
        theme_hint=(data.theme_hint or None),
        original_story_text=(data.original_story_text or ""),
        target_duration_seconds=target_duration,
        continue_from_previous=(False if order_index == 0 else data.continue_from_previous),
        skip_audio=skip_audio_effective,
        youtube_audio_url=yt_url,
        youtube_audio_duration_seconds=yt_dur,
        youtube_as_background_music=yt_bg,
    )
    db.add(ep)
    await _maybe_dispatch_pipeline(db, project)
    await db.flush()
    await db.refresh(ep)
    return EpisodeRead.model_validate(ep)


@router.post("/projects/{project_id}/episodes/from-theme", response_model=EpisodeRead, status_code=201)
async def create_episode_from_theme(
    project_id: uuid.UUID, data: EpisodeFromTheme, db: AsyncSession = Depends(get_db),
):
    return await create_episode(
        project_id,
        EpisodeCreate(
            title=data.title,
            theme_hint=data.theme_hint,
            target_duration_seconds=data.target_duration_seconds,
            continue_from_previous=data.continue_from_previous,
            skip_audio=data.skip_audio,
            youtube_audio_url=data.youtube_audio_url,
            youtube_as_background_music=data.youtube_as_background_music,
        ),
        db,
    )


@router.get("/episodes/{episode_id}", response_model=EpisodeRead)
async def get_episode(episode_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    ep = await db.get(Episode, episode_id)
    if not ep:
        raise HTTPException(status_code=404, detail="Episode not found")
    out = EpisodeRead.model_validate(ep)
    out.scene_count = await _scene_count_for(db, ep.id)
    return out


_LATE_TOGGLABLE = {"skip_audio"}


@router.patch("/episodes/{episode_id}", response_model=EpisodeRead)
async def update_episode(
    episode_id: uuid.UUID, data: EpisodeUpdate, db: AsyncSession = Depends(get_db),
):
    ep = await db.get(Episode, episode_id)
    if not ep:
        raise HTTPException(status_code=404, detail="Episode not found")
    update = data.model_dump(exclude_unset=True)
    is_terminal = ep.status in (EpisodeStatus.draft, EpisodeStatus.failed)
    if not is_terminal:
        rejected = [k for k in update.keys() if k not in _LATE_TOGGLABLE]
        if rejected:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Episode in status {ep.status.value} cannot edit "
                    f"{rejected}. Only {sorted(_LATE_TOGGLABLE)} can be toggled mid-pipeline."
                ),
            )
    for k, v in update.items():
        setattr(ep, k, v)
    await db.flush()
    await db.refresh(ep)
    return EpisodeRead.model_validate(ep)


class AttachYouTubeAudio(BaseModel):
    youtube_audio_url: str = Field(..., min_length=10, description="Public YouTube URL")
    mode: str = Field(
        default="replace",
        description="'replace' (default) strips existing audio and overlays YT. 'mix' keeps existing audio (voiceover) and ducks YT in as background music.",
    )


@router.post("/episodes/{episode_id}/attach-youtube-audio", response_model=EpisodeRead)
async def attach_youtube_audio(
    episode_id: uuid.UUID, data: AttachYouTubeAudio, db: AsyncSession = Depends(get_db),
):
    """Strip the existing audio from this episode's final render and overlay
    the audio from a YouTube URL. Works on any episode whose `final_render`
    asset exists on disk (silent or already narrated)."""
    import asyncio
    from pathlib import Path as _Path

    ep = await db.get(Episode, episode_id)
    if not ep:
        raise HTTPException(status_code=404, detail="Episode not found")
    url = data.youtube_audio_url.strip()
    mode = (data.mode or "replace").lower().strip()
    if mode not in ("replace", "mix"):
        raise HTTPException(status_code=400, detail=f"mode must be 'replace' or 'mix', got {mode!r}")
    if not is_youtube_url(url):
        raise HTTPException(status_code=400, detail=f"Not a YouTube URL: {url!r}")

    # Need a stitched video to overlay onto.
    render = (await db.execute(
        select(Asset)
        .where(Asset.episode_id == ep.id)
        .where(Asset.asset_type == AssetType.final_render)
        .where(Asset.status == AssetStatus.complete)
        .order_by(Asset.created_at.desc()).limit(1)
    )).scalar_one_or_none()
    if not render or not render.file_path or not _Path(render.file_path).exists():
        raise HTTPException(
            status_code=400,
            detail="No stitched final_render found on disk for this episode — "
                   "wait for the pipeline to finish before attaching audio.",
        )

    # Probe + download YouTube audio (yt-dlp is sync — run in a thread).
    try:
        yt_dur = await asyncio.to_thread(probe_duration, url)
    except YouTubeAudioError as e:
        raise HTTPException(status_code=400, detail=f"YouTube probe failed: {e}")

    from app.config import settings
    audio_dir = settings.storage_root / "audio" / str(ep.project_id) / "episodes" / str(ep.id)
    audio_path = audio_dir / "youtube.mp3"
    try:
        audio_path = await asyncio.to_thread(download_audio, url, audio_path)
    except YouTubeAudioError as e:
        raise HTTPException(status_code=500, detail=f"YouTube download failed: {e}")

    # Run ffmpeg overlay: strip orig audio, add YouTube audio. Output goes
    # next to the original render so we don't clobber it mid-write.
    src = _Path(render.file_path)
    suffix_tag = "_yt_bg" if mode == "mix" else "_with_youtube"
    out_path = src.parent / f"{src.stem}{suffix_tag}{src.suffix}"
    try:
        await overlay_audio_on_video(src, audio_path, out_path, mode=mode)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"ffmpeg overlay failed: {e}")

    # Swap the final_render asset to point at the new file. Keep the old one
    # on disk so the user can fall back if they don't like the result.
    render.file_path = str(out_path)
    ep.final_video_path = str(out_path)
    ep.youtube_audio_url = url
    ep.youtube_audio_duration_seconds = yt_dur
    ep.youtube_as_background_music = (mode == "mix")
    await db.flush()
    await db.refresh(ep)
    return EpisodeRead.model_validate(ep)


@router.delete("/episodes/{episode_id}", status_code=204)
async def delete_episode(episode_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    ep = await db.get(Episode, episode_id)
    if not ep:
        raise HTTPException(status_code=404, detail="Episode not found")
    await db.execute(delete(Episode).where(Episode.id == episode_id))
