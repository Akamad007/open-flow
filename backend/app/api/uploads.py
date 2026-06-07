"""User upload endpoints for character + product reference images.

Two SEPARATE endpoints — they look symmetric but kept distinct because:
- Character uploads downstream feed InstantID face-identity conditioning.
- Product uploads downstream feed SD3.5 img2img with `product_img2img_strength`.
- The label semantics differ (character = entity name; product = SKU name).

Each upload writes a normalized PNG to disk and creates an `Asset` row with
asset_type=character_ref (or product_ref), generation_provider='user_upload',
metadata_json carrying the label so the prompting stage can match the LLM-
extracted character / product entities.
"""
from __future__ import annotations

import io
import json
import logging
import re
import uuid
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import delete as sa_delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api._common import NOT_FOUND_RESPONSE, get_or_404
from app.config import settings
from app.database import get_db
from app.models.asset import Asset, AssetStatus, AssetType
from app.models.project import Project

logger = logging.getLogger(__name__)
router = APIRouter(tags=["uploads"], responses=NOT_FOUND_RESPONSE)

MAX_BYTES = 10 * 1024 * 1024
NORMALIZED_SIZE = 1024
ACCEPTED_CONTENT_TYPES = {"image/png", "image/jpeg", "image/jpg", "image/webp"}


def _slug(label: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")
    return s[:60] or "unlabeled"


async def _load_project(project_id: uuid.UUID, db: AsyncSession) -> Project:
    return await get_or_404(db, Project, project_id, "Project")


def _normalize_image(file_bytes: bytes) -> Image.Image:
    """Validate + normalize: respect EXIF rotation, strip metadata, resize+pad
    to NORMALIZED_SIZE × NORMALIZED_SIZE on a white background, RGB."""
    try:
        img = Image.open(io.BytesIO(file_bytes))
        img.verify()
    except (UnidentifiedImageError, OSError) as exc:
        raise HTTPException(status_code=400, detail=f"Not a valid image: {exc}")
    img = Image.open(io.BytesIO(file_bytes))
    img = ImageOps.exif_transpose(img).convert("RGB")
    img.thumbnail((NORMALIZED_SIZE, NORMALIZED_SIZE), Image.LANCZOS)
    canvas = Image.new("RGB", (NORMALIZED_SIZE, NORMALIZED_SIZE), (255, 255, 255))
    canvas.paste(img, (
        (NORMALIZED_SIZE - img.width) // 2,
        (NORMALIZED_SIZE - img.height) // 2,
    ))
    return canvas


async def _save_upload(
    project_id: uuid.UUID, kind: Literal["character", "product"],
    label: str, file: UploadFile, db: AsyncSession,
) -> Asset:
    if file.content_type not in ACCEPTED_CONTENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported content-type {file.content_type!r}. "
                   f"Allowed: {sorted(ACCEPTED_CONTENT_TYPES)}",
        )
    raw = await file.read()
    if len(raw) > MAX_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"File too large ({len(raw)} bytes > {MAX_BYTES})",
        )
    if not label.strip():
        raise HTTPException(status_code=400, detail="Label is required")

    img = _normalize_image(raw)
    asset_type = AssetType.character_ref if kind == "character" else AssetType.product_ref
    fname = f"{kind}_{_slug(label)}.png"
    abs_dir = settings.storage_root / "uploads" / str(project_id)
    abs_dir.mkdir(parents=True, exist_ok=True)
    abs_path = abs_dir / fname
    img.save(abs_path, format="PNG", optimize=True)
    rel_path = str(abs_path.relative_to(settings.storage_root.parent))

    asset = Asset(
        id=uuid.uuid4(),
        project_id=project_id,
        scene_id=None,
        asset_type=asset_type,
        file_path=rel_path,
        status=AssetStatus.complete,
        generation_provider="user_upload",
        metadata_json=json.dumps({
            "source": "user_upload",
            "label": label.strip(),
            "original_filename": file.filename or "",
            "kind": kind,
        }),
    )
    db.add(asset)
    await db.commit()
    await db.refresh(asset)
    logger.info(
        "user_upload %s asset %s for project %s label=%r → %s",
        kind, asset.id, project_id, label, rel_path,
    )
    return asset


def _asset_to_response(asset: Asset) -> dict:
    md = json.loads(asset.metadata_json) if asset.metadata_json else {}
    return {
        "asset_id": str(asset.id),
        "project_id": str(asset.project_id),
        "asset_type": asset.asset_type.value,
        "file_path": asset.file_path,
        "label": md.get("label"),
        "kind": md.get("kind"),
        "source": md.get("source"),
    }


@router.post("/projects/{project_id}/uploads/character", status_code=201)
async def upload_character(
    project_id: uuid.UUID,
    label: str = Form(..., description="Character name as referenced in the story (e.g. 'Alice')"),
    file: UploadFile = File(..., description="Face or full-body shot of the character"),
    db: AsyncSession = Depends(get_db),
):
    """Upload a character reference image. Used downstream as the InstantID
    face-identity source and as the SD3.5 img2img init image for per-scene
    character renders."""
    await _load_project(project_id, db)
    asset = await _save_upload(project_id, "character", label, file, db)
    return _asset_to_response(asset)


@router.post("/projects/{project_id}/uploads/product", status_code=201)
async def upload_product(
    project_id: uuid.UUID,
    label: str = Form(..., description="Product name as referenced in the story (e.g. 'tan Birkin handbag')"),
    file: UploadFile = File(..., description="Hero shot of the product (ideally on a plain background)"),
    db: AsyncSession = Depends(get_db),
):
    """Upload a product reference image. Used downstream as the SD3.5 img2img
    init image for per-scene action stills with the product composited in."""
    await _load_project(project_id, db)
    asset = await _save_upload(project_id, "product", label, file, db)
    return _asset_to_response(asset)


@router.get("/projects/{project_id}/uploads")
async def list_uploads(project_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """List all user-uploaded character + product refs for this project."""
    await _load_project(project_id, db)
    rows = (await db.execute(
        select(Asset).where(
            Asset.project_id == project_id,
            Asset.asset_type.in_([AssetType.character_ref, AssetType.product_ref]),
            Asset.generation_provider == "user_upload",
        )
    )).scalars().all()
    return [_asset_to_response(a) for a in rows]


@router.delete("/projects/{project_id}/uploads/{asset_id}", status_code=204)
async def delete_upload(
    project_id: uuid.UUID, asset_id: uuid.UUID, db: AsyncSession = Depends(get_db),
):
    """Delete a user-uploaded ref (DB row + file on disk). 404 if not found or
    not a user upload (we don't let users delete SD3.5-generated refs through
    this endpoint)."""
    asset = await db.get(Asset, asset_id)
    if not asset or asset.project_id != project_id:
        raise HTTPException(status_code=404, detail="Upload not found")
    if asset.generation_provider != "user_upload":
        raise HTTPException(status_code=403, detail="Not a user upload")
    if asset.file_path:
        abs_path = (settings.storage_root.parent / asset.file_path).resolve()
        storage_root = settings.storage_root.resolve()
        try:
            abs_path.relative_to(storage_root)
        except ValueError:
            logger.warning("delete_upload: refusing to unlink path outside storage: %s", abs_path)
        else:
            try:
                if abs_path.is_file():
                    abs_path.unlink()
            except OSError as exc:
                logger.warning("delete_upload: failed to unlink %s: %s", abs_path, exc)
    await db.delete(asset)
    await db.commit()
