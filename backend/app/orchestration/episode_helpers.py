"""Episode resolution helpers — find the active episode for a project."""

from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.episode import Episode, EpisodeStatus

_TERMINAL = (EpisodeStatus.complete, EpisodeStatus.failed)


async def resolve_active_episode(db: AsyncSession, project_id: str) -> Optional[Episode]:
    """The oldest non-terminal episode for the project, or the latest if all terminal."""
    pid = uuid.UUID(project_id) if isinstance(project_id, str) else project_id
    active = (await db.execute(
        select(Episode)
        .where(Episode.project_id == pid)
        .where(Episode.status.notin_(_TERMINAL))
        .order_by(Episode.order_index.asc())
        .limit(1)
    )).scalar_one_or_none()
    if active:
        return active
    return (await db.execute(
        select(Episode)
        .where(Episode.project_id == pid)
        .order_by(Episode.order_index.desc())
        .limit(1)
    )).scalar_one_or_none()


async def get_episode(db: AsyncSession, episode_id: str | uuid.UUID) -> Optional[Episode]:
    eid = uuid.UUID(episode_id) if isinstance(episode_id, str) else episode_id
    return await db.get(Episode, eid)


async def previous_episode(db: AsyncSession, episode: Episode) -> Optional[Episode]:
    if episode.order_index <= 0:
        return None
    return (await db.execute(
        select(Episode)
        .where(Episode.project_id == episode.project_id)
        .where(Episode.order_index == episode.order_index - 1)
        .limit(1)
    )).scalar_one_or_none()
