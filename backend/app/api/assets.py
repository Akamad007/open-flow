"""Assets API router."""

import uuid
from pathlib import Path
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.asset import Asset
from app.schemas.asset import AssetRead

router = APIRouter(tags=["assets"])

# Map file suffix → MIME type
_MEDIA_TYPES: dict[str, str] = {
    ".mp4":  "video/mp4",
    ".webm": "video/webm",
    ".mov":  "video/quicktime",
    ".wav":  "audio/wav",
    ".mp3":  "audio/mpeg",
    ".ogg":  "audio/ogg",
    ".png":  "image/png",
    ".jpg":  "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}


@router.get("/projects/{project_id}/assets", response_model=List[AssetRead])
async def list_assets(project_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    stmt = (
        select(Asset)
        .where(Asset.project_id == project_id)
        .order_by(Asset.created_at.desc())
    )
    result = await db.execute(stmt)
    return [AssetRead.model_validate(a) for a in result.scalars().all()]


@router.get("/assets/{asset_id}", response_model=AssetRead)
async def get_asset(asset_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    asset = await db.get(Asset, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    return AssetRead.model_validate(asset)


async def _serve(asset_id: uuid.UUID, db: AsyncSession) -> FileResponse:
    asset = await db.get(Asset, asset_id)
    if not asset or not asset.file_path:
        raise HTTPException(status_code=404, detail="Asset file not found")
    file_path = Path(asset.file_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Asset file missing from disk")
    media_type = _MEDIA_TYPES.get(file_path.suffix.lower(), "application/octet-stream")
    # Renders are re-burned in place (same filename) when captions change, so tell
    # the browser to revalidate instead of serving a stale cached video.
    return FileResponse(
        file_path, media_type=media_type, filename=file_path.name,
        headers={"Cache-Control": "no-cache, must-revalidate"},
    )


@router.get("/assets/{asset_id}/file")
async def serve_asset_file(asset_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Legacy route — serves the asset file with its real filename in Content-Disposition."""
    return await _serve(asset_id, db)


@router.get("/assets/{asset_id}/file/{filename}")
async def serve_asset_file_named(
    asset_id: uuid.UUID, filename: str, db: AsyncSession = Depends(get_db),
):
    """Filename suffix is decorative — asset_id resolves the actual file."""
    return await _serve(asset_id, db)
