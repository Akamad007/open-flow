"""Location Pydantic schemas."""

from __future__ import annotations

import uuid
from typing import Optional

from pydantic import BaseModel, Field


class LocationCreate(BaseModel):
    name: str = Field(max_length=300)
    description: Optional[str] = None
    continuity_notes: Optional[str] = None


class LocationUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    continuity_notes: Optional[str] = None


class LocationRead(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    description: Optional[str] = None
    continuity_notes: Optional[str] = None
    reference_image_path: Optional[str] = None

    model_config = {"from_attributes": True}
