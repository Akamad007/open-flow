"""Project Pydantic schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.models.project import ProjectStatus


class ProjectCreate(BaseModel):
    title: str = Field(default="Untitled Project", max_length=500)
    original_story_text: str = Field(default="")
    total_target_duration_seconds: Optional[float] = Field(default=300.0, description="Target video duration in seconds")
    pipeline_profile: Optional[str] = Field(default=None, description="Named pipeline profile (e.g. 'ltx_text_only', 'wan_phantom_text')")
    # First-episode shortcuts: setting these on project create writes them to the
    # auto-created Episode 0 so users can ship "prompt + YouTube URL" in one form.
    theme_hint: Optional[str] = Field(default=None, description="One-line prompt for Episode 0 (alternative to full story text)")
    youtube_audio_url: Optional[str] = Field(default=None, description="Public YouTube URL — audio downloaded + overlaid, video length matches the clip")
    skip_audio: bool = Field(default=False, description="Silent background video — skip narration generation")
    youtube_as_background_music: bool = Field(
        default=False,
        description="If True (and youtube_audio_url is set), the YT track is mixed UNDER the narration as background music. If False, YT REPLACES narration.",
    )


class ProjectUpdate(BaseModel):
    title: Optional[str] = None
    original_story_text: Optional[str] = None
    status: Optional[ProjectStatus] = None
    total_target_duration_seconds: Optional[float] = None
    pipeline_profile: Optional[str] = None


class ProjectRead(BaseModel):
    id: uuid.UUID
    title: str
    original_story_text: str
    status: ProjectStatus
    total_target_duration_seconds: Optional[float]
    final_audio_duration_seconds: Optional[float]
    story_summary: Optional[str]
    beat_list_json: Optional[str]
    pacing_notes: Optional[str]
    style_lock: Optional[str] = None
    pipeline_profile: str = "ltx_text_only"
    final_evaluation_json: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    # Counts for list view
    scene_count: int = 0
    character_count: int = 0
    location_count: int = 0

    model_config = {"from_attributes": True}


class ProjectList(BaseModel):
    id: uuid.UUID
    title: str
    status: ProjectStatus
    total_target_duration_seconds: Optional[float]
    pipeline_profile: str = "ltx_text_only"
    scene_count: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
