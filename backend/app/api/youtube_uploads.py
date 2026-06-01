"""YouTube upload routes — kick off and list uploads per episode."""

from __future__ import annotations

import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pydantic import BaseModel

from app.database import get_db
from app.models.asset import Asset, AssetStatus, AssetType
from app.models.episode import Episode
from app.models.project import Project
from app.models.youtube_upload import (
    YouTubeUpload,
    YouTubeUploadStatus,
)
from app.orchestration._common import get_llm_provider
from app.orchestration.tasks import task_upload_to_youtube
from app.schemas.youtube_upload import YouTubeUploadCreate, YouTubeUploadRead

router = APIRouter(tags=["youtube"])

_ACTIVE = (YouTubeUploadStatus.queued, YouTubeUploadStatus.uploading)


class YouTubeMetadataSuggestion(BaseModel):
    title: str
    description: str


_METADATA_SYSTEM = (
    "You write YouTube video metadata that's ready to paste straight into the "
    "YouTube creator UI. Given the story content of a short video, produce:\n"
    "\n"
    "• title — ≤100 chars. Specific, evocative, no clickbait, no emojis. Mention "
    "  the main subject and the hook (e.g. 'Swami Vivekananda — The Kanyakumari "
    "  Resolve, Dec 1892').\n"
    "• description — ≤4500 chars, plain text:\n"
    "    - First line: a single tight hook sentence (under 140 chars).\n"
    "    - 2–4 short paragraphs (≤4 lines each) that summarise the story "
    "      vividly with concrete imagery from the scenes.\n"
    "    - A short 'In this video:' bullet list (3–5 bullets, each ≤80 chars).\n"
    "    - A blank line, then 8–12 hashtags on ONE line, each prefixed with #, "
    "      separated by single spaces (e.g. '#Vivekananda #Spirituality "
    "      #IndianHistory #Animation'). Use single-word or camelCase tags only.\n"
    "\n"
    "Output VALID JSON ONLY with keys 'title' and 'description'. No prose outside "
    "the JSON."
)


@router.post(
    "/episodes/{episode_id}/youtube-metadata",
    response_model=YouTubeMetadataSuggestion,
)
async def suggest_youtube_metadata(
    episode_id: uuid.UUID, db: AsyncSession = Depends(get_db),
):
    """Ask the configured LLM (default: gpt-5.4-nano) for a YouTube title + description."""
    ep = await db.get(Episode, episode_id)
    if not ep:
        raise HTTPException(status_code=404, detail="Episode not found")
    project = await db.get(Project, ep.project_id)

    story = (ep.original_story_text or "").strip()
    summary = (ep.story_summary or "").strip()
    theme = (ep.theme_hint or "").strip()
    ep_title = (ep.title or "").strip()
    proj_title = (project.title or "").strip() if project else ""

    if not (story or summary or theme or ep_title):
        raise HTTPException(status_code=400, detail="Episode has no text content to summarise.")

    parts = []
    if proj_title:
        parts.append(f"Project: {proj_title}")
    if ep_title:
        parts.append(f"Episode title: {ep_title}")
    if theme:
        parts.append(f"Theme: {theme}")
    if summary:
        parts.append(f"Story summary: {summary}")
    if story:
        # Cap to keep prompt cheap.
        parts.append(f"Story:\n{story[:6000]}")
    user_prompt = "\n\n".join(parts)

    provider = get_llm_provider()
    try:
        data = await provider.complete_json(
            system_prompt=_METADATA_SYSTEM,
            user_prompt=user_prompt,
            temperature=0.7,
            max_tokens=1200,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM error: {e}")

    title = str(data.get("title") or "").strip()[:100]
    description = str(data.get("description") or "").strip()[:5000]
    if not title:
        raise HTTPException(status_code=502, detail="LLM returned no title.")
    return YouTubeMetadataSuggestion(title=title, description=description)


@router.post(
    "/episodes/{episode_id}/upload-youtube",
    response_model=YouTubeUploadRead,
    status_code=202,
)
async def upload_to_youtube(
    episode_id: uuid.UUID,
    data: YouTubeUploadCreate,
    db: AsyncSession = Depends(get_db),
):
    ep = await db.get(Episode, episode_id)
    if not ep:
        raise HTTPException(status_code=404, detail="Episode not found")

    # Need a stitched final_render on disk.
    from pathlib import Path
    render = (await db.execute(
        select(Asset)
        .where(Asset.episode_id == ep.id)
        .where(Asset.asset_type == AssetType.final_render)
        .where(Asset.status == AssetStatus.complete)
        .order_by(Asset.created_at.desc()).limit(1)
    )).scalar_one_or_none()
    if not render or not render.file_path or not Path(render.file_path).exists():
        raise HTTPException(
            status_code=409,
            detail="No completed final_render on disk for this episode.",
        )

    # Block only when an ACTIVE upload is already in flight; allow retry after failure.
    active = (await db.execute(
        select(YouTubeUpload)
        .where(YouTubeUpload.episode_id == ep.id)
        .where(YouTubeUpload.status.in_(_ACTIVE))
    )).scalar_one_or_none()
    if active:
        raise HTTPException(
            status_code=409,
            detail=f"Upload {active.id} is already {active.status.value}.",
        )

    row = YouTubeUpload(
        episode_id=ep.id,
        asset_id=render.id,
        title=data.title,
        description=data.description,
        privacy=data.privacy,
    )
    db.add(row)
    await db.flush()
    await db.refresh(row)

    task_upload_to_youtube.delay(str(row.id), render.file_path)
    return YouTubeUploadRead.model_validate(row)


@router.get(
    "/episodes/{episode_id}/uploads",
    response_model=List[YouTubeUploadRead],
)
async def list_episode_uploads(
    episode_id: uuid.UUID, db: AsyncSession = Depends(get_db),
):
    ep = await db.get(Episode, episode_id)
    if not ep:
        raise HTTPException(status_code=404, detail="Episode not found")
    rows = (await db.execute(
        select(YouTubeUpload)
        .where(YouTubeUpload.episode_id == episode_id)
        .order_by(YouTubeUpload.created_at.desc())
    )).scalars().all()
    return [YouTubeUploadRead.model_validate(r) for r in rows]
