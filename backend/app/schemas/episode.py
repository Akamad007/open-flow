"""Episode Pydantic schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, model_validator

from app.models.episode import EpisodeStatus


class EpisodeCreate(BaseModel):
    title: Optional[str] = Field(default=None, max_length=500)
    theme_hint: Optional[str] = Field(default=None, description="One-line idea for the episode")
    original_story_text: Optional[str] = Field(default=None, description="Full story text; optional if theme_hint provided")
    target_duration_seconds: Optional[float] = Field(default=30.0, ge=3.0, le=1200.0)
    continue_from_previous: bool = True
    skip_audio: bool = Field(default=False, description="Skip narration generation and stitch the final video silent for custom audio overlay")
    youtube_audio_url: Optional[str] = Field(
        default=None,
        description=(
            "Public YouTube URL. When set, narration is skipped, the audio is "
            "downloaded at audio-gen time and overlaid on the final video, and "
            "the video duration matches the YouTube clip's length."
        ),
    )
    youtube_as_background_music: bool = Field(
        default=False,
        description=(
            "If True, the YouTube track is mixed UNDER the generated narration "
            "as background music (voiceover stays foreground). If False (default), "
            "the YouTube track REPLACES narration entirely."
        ),
    )

    @model_validator(mode="after")
    def _exactly_one_input(self) -> "EpisodeCreate":
        has_theme = bool((self.theme_hint or "").strip())
        has_story = bool((self.original_story_text or "").strip())
        if not has_theme and not has_story:
            raise ValueError("Provide either `theme_hint` or `original_story_text`")
        return self


class EpisodeFromTheme(BaseModel):
    theme_hint: str = Field(..., min_length=3, description="One-line idea")
    title: Optional[str] = Field(default=None, max_length=500)
    target_duration_seconds: Optional[float] = Field(default=30.0, ge=3.0, le=1200.0)
    continue_from_previous: bool = True
    skip_audio: bool = False
    youtube_audio_url: Optional[str] = None
    youtube_as_background_music: bool = False


class EpisodeUpdate(BaseModel):
    title: Optional[str] = None
    theme_hint: Optional[str] = None
    original_story_text: Optional[str] = None
    target_duration_seconds: Optional[float] = None
    continue_from_previous: Optional[bool] = None
    skip_audio: Optional[bool] = None
    youtube_audio_url: Optional[str] = None
    youtube_as_background_music: Optional[bool] = None


class EpisodeRead(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    order_index: int
    title: str
    status: EpisodeStatus
    theme_hint: Optional[str]
    original_story_text: str
    target_duration_seconds: Optional[float]
    final_audio_duration_seconds: Optional[float]
    story_summary: Optional[str]
    beat_list_json: Optional[str]
    pacing_notes: Optional[str]
    style_lock: Optional[str]
    final_evaluation_json: Optional[str]
    continue_from_previous: bool
    skip_audio: bool = False
    youtube_audio_url: Optional[str] = None
    youtube_audio_duration_seconds: Optional[float] = None
    youtube_as_background_music: bool = False
    final_video_path: Optional[str]
    created_at: datetime
    updated_at: datetime
    scene_count: int = 0

    model_config = {"from_attributes": True}


class EpisodeList(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    order_index: int
    title: str
    status: EpisodeStatus
    theme_hint: Optional[str]
    target_duration_seconds: Optional[float]
    skip_audio: bool = False
    youtube_audio_url: Optional[str] = None
    youtube_as_background_music: bool = False
    final_video_path: Optional[str]
    scene_count: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
