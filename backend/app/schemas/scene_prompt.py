"""ScenePrompt Pydantic schemas."""

from __future__ import annotations

import json
import uuid
from typing import Any, Optional

from pydantic import BaseModel, computed_field


class ScenePromptCreate(BaseModel):
    video_prompt: Optional[str] = None
    negative_prompt: Optional[str] = None
    style_notes: Optional[str] = None
    camera_plan: Optional[str] = None
    camera_angle: Optional[str] = None
    subject_description: Optional[str] = None
    environment_description: Optional[str] = None
    action_description: Optional[str] = None
    scene_breakdown: Optional[str] = None
    continuity_guardrails: Optional[str] = None


class ScenePromptUpdate(BaseModel):
    video_prompt: Optional[str] = None
    negative_prompt: Optional[str] = None
    style_notes: Optional[str] = None
    camera_plan: Optional[str] = None
    camera_angle: Optional[str] = None
    subject_description: Optional[str] = None
    environment_description: Optional[str] = None
    action_description: Optional[str] = None
    scene_breakdown: Optional[str] = None
    continuity_guardrails: Optional[str] = None
    critic_notes: Optional[str] = None
    approved: Optional[bool] = None


class ScenePromptRead(BaseModel):
    id: uuid.UUID
    scene_id: uuid.UUID
    video_prompt: Optional[str]
    negative_prompt: Optional[str]
    style_notes: Optional[str]
    camera_plan: Optional[str]
    camera_angle: Optional[str]
    subject_description: Optional[str]
    environment_description: Optional[str]
    action_description: Optional[str]
    scene_breakdown: Optional[str]
    continuity_guardrails: Optional[str]
    critic_notes: Optional[str]
    lora_plan_json: Optional[str] = None
    approved: bool

    @computed_field  # type: ignore[misc]
    @property
    def lora_plan(self) -> Optional[dict[str, Any]]:
        """Parsed `lora_plan_json` for convenience — UI reads this directly."""
        if not self.lora_plan_json:
            return None
        try:
            return json.loads(self.lora_plan_json)
        except (ValueError, TypeError):
            return None

    model_config = {"from_attributes": True}
