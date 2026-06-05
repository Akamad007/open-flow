"""Scene Pydantic schemas."""

from __future__ import annotations

import uuid
from typing import List, Optional

from pydantic import BaseModel

from app.models.scene import SceneStatus
from app.schemas.character import CharacterRead
from app.schemas.scene_prompt import ScenePromptRead


class SceneCreate(BaseModel):
    episode_id: Optional[uuid.UUID] = None  # defaults to the project's active episode
    order_index: int = 0  # ignored — new scenes are appended to the end of the episode
    source_excerpt: Optional[str] = None
    duration_seconds: float = 4.0
    scene_purpose: Optional[str] = None
    visual_summary: Optional[str] = None
    audio_alignment_notes: Optional[str] = None
    continuity_from_previous: Optional[str] = None
    continuity_to_next: Optional[str] = None


class SceneUpdate(BaseModel):
    order_index: Optional[int] = None
    source_excerpt: Optional[str] = None
    duration_seconds: Optional[float] = None
    scene_purpose: Optional[str] = None
    visual_summary: Optional[str] = None
    audio_alignment_notes: Optional[str] = None
    continuity_from_previous: Optional[str] = None
    continuity_to_next: Optional[str] = None
    continuity_prev_scene_id: Optional[uuid.UUID] = None
    target_audio_segment_start: Optional[float] = None
    target_audio_segment_end: Optional[float] = None
    caption: Optional[str] = None
    status: Optional[SceneStatus] = None
    locked: Optional[bool] = None
    location_id: Optional[uuid.UUID] = None


class SceneRead(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    episode_id: uuid.UUID
    order_index: int
    source_excerpt: Optional[str]
    duration_seconds: float
    scene_purpose: Optional[str]
    visual_summary: Optional[str]
    audio_alignment_notes: Optional[str]
    continuity_from_previous: Optional[str]
    continuity_to_next: Optional[str]
    continuity_prev_scene_id: Optional[uuid.UUID] = None
    target_audio_segment_start: Optional[float]
    target_audio_segment_end: Optional[float]
    caption: Optional[str] = None
    location_id: Optional[uuid.UUID]
    status: SceneStatus
    locked: bool
    prompt: Optional[ScenePromptRead] = None
    characters: List[CharacterRead] = []
    evaluation_json: Optional[str] = None

    model_config = {"from_attributes": True}


class SceneReorder(BaseModel):
    """Payload to reorder scenes."""
    scene_ids: List[uuid.UUID]
