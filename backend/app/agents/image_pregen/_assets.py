"""Helpers shared across image_pregen modules."""

from __future__ import annotations

import json
import uuid

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.asset import Asset, AssetStatus, AssetType


def safe_name(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in name).lower()


async def save_asset(
    db: AsyncSession,
    project_id: uuid.UUID,
    asset_type: AssetType,
    file_path: str,
    label: str,
    scene_id: uuid.UUID | None = None,
) -> None:
    db.add(Asset(
        project_id=project_id,
        scene_id=scene_id,
        asset_type=asset_type,
        status=AssetStatus.complete,
        file_path=file_path,
        generation_provider="SD35ImageProvider",
        generation_params_json=json.dumps({"label": label}),
    ))


async def delete_assets_for_scene(
    db: AsyncSession,
    project_id: uuid.UUID,
    scene_id: uuid.UUID,
    asset_type: AssetType,
) -> None:
    await db.execute(
        delete(Asset)
        .where(Asset.project_id == project_id)
        .where(Asset.scene_id == scene_id)
        .where(Asset.asset_type == asset_type)
    )
