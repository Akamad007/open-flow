"""Product Pydantic schemas."""

from __future__ import annotations

import uuid
from typing import Optional

from pydantic import BaseModel, Field


class ProductCreate(BaseModel):
    canonical_name: str = Field(max_length=300)
    category: Optional[str] = None
    physical_description: Optional[str] = None
    brand_marks: Optional[str] = None
    color_palette: Optional[str] = None
    hero_angle: Optional[str] = None
    user_uploaded_path: Optional[str] = None


class ProductUpdate(BaseModel):
    canonical_name: Optional[str] = None
    category: Optional[str] = None
    physical_description: Optional[str] = None
    brand_marks: Optional[str] = None
    color_palette: Optional[str] = None
    hero_angle: Optional[str] = None
    user_uploaded_path: Optional[str] = None


class ProductRead(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    canonical_name: str
    category: Optional[str] = None
    physical_description: Optional[str] = None
    brand_marks: Optional[str] = None
    color_palette: Optional[str] = None
    hero_angle: Optional[str] = None
    user_uploaded_path: Optional[str] = None
    reference_image_path: Optional[str] = None

    model_config = {"from_attributes": True}
