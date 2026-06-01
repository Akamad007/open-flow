"""Asset Pydantic schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from app.models.asset import AssetStatus, AssetType


class AssetRead(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    episode_id: Optional[uuid.UUID] = None
    scene_id: Optional[uuid.UUID]
    asset_type: AssetType
    file_path: Optional[str]
    metadata_json: Optional[str]
    generation_provider: Optional[str]
    generation_params_json: Optional[str]
    status: AssetStatus
    created_at: datetime

    model_config = {"from_attributes": True}
