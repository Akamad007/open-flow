"""Character Pydantic schemas."""

from __future__ import annotations

import uuid
from typing import Optional

from pydantic import BaseModel, Field


class CharacterCreate(BaseModel):
    canonical_name: str = Field(max_length=300)
    character_kind: Optional[str] = "human"
    physical_description: Optional[str] = None
    clothing_description: Optional[str] = None
    personality_notes: Optional[str] = None
    voice_notes: Optional[str] = None
    continuity_notes: Optional[str] = None


class CharacterUpdate(BaseModel):
    canonical_name: Optional[str] = None
    character_kind: Optional[str] = None
    physical_description: Optional[str] = None
    clothing_description: Optional[str] = None
    personality_notes: Optional[str] = None
    voice_notes: Optional[str] = None
    continuity_notes: Optional[str] = None
    reference_image_path: Optional[str] = None


class CharacterRead(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    canonical_name: str
    character_kind: Optional[str] = None
    physical_description: Optional[str] = None
    clothing_description: Optional[str] = None
    personality_notes: Optional[str] = None
    voice_notes: Optional[str] = None
    continuity_notes: Optional[str] = None
    reference_image_path: Optional[str] = None

    model_config = {"from_attributes": True}
