"""Pydantic schemas for YouTube uploads."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.youtube_upload import YouTubePrivacy, YouTubeUploadStatus


class YouTubeUploadCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=100)
    description: str = Field("", max_length=5000)
    privacy: YouTubePrivacy = YouTubePrivacy.private


class YouTubeUploadRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    episode_id: uuid.UUID
    title: str
    description: str
    privacy: YouTubePrivacy
    status: YouTubeUploadStatus
    youtube_id: Optional[str] = None
    youtube_url: Optional[str] = None
    progress: Optional[float] = None
    error: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None
