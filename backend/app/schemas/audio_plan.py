"""AudioPlan Pydantic schemas."""

from __future__ import annotations

import uuid
from typing import Optional

from pydantic import BaseModel


class AudioPlanUpdate(BaseModel):
    full_story_narration_text: Optional[str] = None
    full_story_dialogue_plan: Optional[str] = None
    full_story_audio_prompt: Optional[str] = None
    ambience_progression_notes: Optional[str] = None
    sound_transition_notes: Optional[str] = None
    total_estimated_audio_duration: Optional[float] = None
    timing_map_json: Optional[str] = None
    approved: Optional[bool] = None


class AudioPlanRead(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    episode_id: Optional[uuid.UUID] = None
    full_story_narration_text: Optional[str]
    full_story_dialogue_plan: Optional[str]
    full_story_audio_prompt: Optional[str]
    ambience_progression_notes: Optional[str]
    sound_transition_notes: Optional[str]
    total_estimated_audio_duration: Optional[float]
    timing_map_json: Optional[str]
    approved: bool

    model_config = {"from_attributes": True}
