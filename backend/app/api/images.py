"""Images API — returns all generated reference images for a project."""

import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.asset import Asset, AssetStatus, AssetType
from app.models.character import Character
from app.models.location import Location
from app.models.product import Product
from app.models.scene import Scene

router = APIRouter(tags=["images"])


def _to_url(path: Optional[str]) -> Optional[str]:
    """Convert a storage path (absolute or relative) to a URL served by /storage."""
    if not path:
        return None
    # Normalise: strip leading slash so we can handle both styles
    # Absolute:  /home/akash/.../storage/characters/... → /storage/characters/...
    # Relative:  storage/characters/...                 → /storage/characters/...
    marker = "storage/"
    idx = path.find(marker)
    if idx == -1:
        return None
    return "/" + path[idx:]


class CharacterImageItem(BaseModel):
    id: uuid.UUID
    name: str
    physical_description: Optional[str] = None
    clothing_description: Optional[str] = None
    image_url: Optional[str] = None


class LocationImageItem(BaseModel):
    id: uuid.UUID
    name: str
    description: Optional[str] = None
    image_url: Optional[str] = None


class ProductImageItem(BaseModel):
    id: uuid.UUID
    canonical_name: str
    category: Optional[str] = None
    physical_description: Optional[str] = None
    brand_marks: Optional[str] = None
    image_url: Optional[str] = None


class SceneActionStillItem(BaseModel):
    url: str
    prompt: Optional[str] = None       # LLM-generated SD3.5 prompt
    negative: Optional[str] = None     # LLM-generated negative


class SceneRefItem(BaseModel):
    id: uuid.UUID
    order_index: int
    visual_summary: Optional[str] = None
    action_image_url: Optional[str] = None    # action still 1 (peak beat) — legacy or seq[0]
    action_image_2_url: Optional[str] = None  # action still 2 (secondary pose) — legacy or seq[-1]
    action_image_seq_urls: List[str] = []     # per-second sequence (new pipeline) — kept for FE backward-compat
    action_image_seq: List[SceneActionStillItem] = []  # richer per-still data with prompts


class ProjectImagesResponse(BaseModel):
    project_id: uuid.UUID
    characters: List[CharacterImageItem]
    locations: List[LocationImageItem]
    products: List[ProductImageItem]
    scene_refs: List[SceneRefItem]


@router.get("/projects/{project_id}/images", response_model=ProjectImagesResponse)
async def get_project_images(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Return all generated SD 3.5 reference images for a project."""

    chars_result = await db.execute(
        select(Character)
        .where(Character.project_id == project_id)
        .order_by(Character.canonical_name)
    )
    chars = [
        CharacterImageItem(
            id=c.id,
            name=c.canonical_name,
            physical_description=c.physical_description,
            clothing_description=c.clothing_description,
            image_url=_to_url(c.reference_image_path),
        )
        for c in chars_result.scalars().all()
    ]

    locs_result = await db.execute(
        select(Location)
        .where(Location.project_id == project_id)
        .order_by(Location.name)
    )
    locs = [
        LocationImageItem(
            id=l.id,
            name=l.name,
            description=l.description,
            image_url=_to_url(l.reference_image_path),
        )
        for l in locs_result.scalars().all()
    ]

    prods_result = await db.execute(
        select(Product)
        .where(Product.project_id == project_id)
        .order_by(Product.canonical_name)
    )
    prods = [
        ProductImageItem(
            id=p.id,
            canonical_name=p.canonical_name,
            category=p.category,
            physical_description=p.physical_description,
            brand_marks=p.brand_marks,
            image_url=_to_url(p.reference_image_path),
        )
        for p in prods_result.scalars().all()
    ]

    scenes_result = await db.execute(
        select(Scene)
        .where(Scene.project_id == project_id)
        .order_by(Scene.order_index)
    )
    scenes = scenes_result.scalars().all()

    # Bulk-load action stills for all scenes — one query per type
    scene_ids = [s.id for s in scenes]

    action1_result = await db.execute(
        select(Asset)
        .where(Asset.project_id == project_id)
        .where(Asset.asset_type == AssetType.scene_action)
        .where(Asset.status == AssetStatus.complete)
        .where(Asset.scene_id.in_(scene_ids))
        .order_by(Asset.scene_id, Asset.created_at.desc())
    )
    action1_by_scene: dict[uuid.UUID, str] = {}
    for a in action1_result.scalars().all():
        if a.scene_id not in action1_by_scene and a.file_path:
            action1_by_scene[a.scene_id] = a.file_path

    action2_result = await db.execute(
        select(Asset)
        .where(Asset.project_id == project_id)
        .where(Asset.asset_type == AssetType.scene_action_2)
        .where(Asset.status == AssetStatus.complete)
        .where(Asset.scene_id.in_(scene_ids))
        .order_by(Asset.scene_id, Asset.created_at.desc())
    )
    action2_by_scene: dict[uuid.UUID, str] = {}
    for a in action2_result.scalars().all():
        if a.scene_id not in action2_by_scene and a.file_path:
            action2_by_scene[a.scene_id] = a.file_path

    seq_result = await db.execute(
        select(Asset)
        .where(Asset.project_id == project_id)
        .where(Asset.asset_type == AssetType.scene_action_seq)
        .where(Asset.status == AssetStatus.complete)
        .where(Asset.scene_id.in_(scene_ids))
        .order_by(Asset.scene_id, Asset.file_path)
    )
    seq_by_scene: dict[uuid.UUID, list[str]] = {}
    for a in seq_result.scalars().all():
        if a.file_path:
            seq_by_scene.setdefault(a.scene_id, []).append(a.file_path)

    def _read_prompt_sidecar(file_path: str) -> tuple[Optional[str], Optional[str]]:
        """Read the *_prompt.txt sidecar next to the still PNG."""
        try:
            from pathlib import Path as _P
            sidecar = _P(file_path).with_name(_P(file_path).stem + "_prompt.txt")
            if not sidecar.exists():
                return None, None
            text = sidecar.read_text()
            prompt = neg = None
            if "PROMPT:" in text:
                parts = text.split("NEGATIVE:", 1)
                prompt = parts[0].replace("PROMPT:", "").strip()
                neg = parts[1].strip() if len(parts) > 1 else None
            return prompt, neg
        except Exception:
            return None, None

    scene_refs = []
    for s in scenes:
        seq_paths = seq_by_scene.get(s.id, [])
        seq_urls = [u for u in (_to_url(p) for p in seq_paths) if u]
        seq_items = []
        for path, url in zip(seq_paths, seq_urls):
            prompt, neg = _read_prompt_sidecar(path)
            seq_items.append(SceneActionStillItem(url=url, prompt=prompt, negative=neg))
        legacy1 = _to_url(action1_by_scene.get(s.id))
        legacy2 = _to_url(action2_by_scene.get(s.id))
        first_url = legacy1 or (seq_urls[0] if seq_urls else None)
        last_url = legacy2 or (seq_urls[-1] if len(seq_urls) > 1 else None)
        scene_refs.append(
            SceneRefItem(
                id=s.id,
                order_index=s.order_index,
                visual_summary=s.visual_summary,
                action_image_url=first_url,
                action_image_2_url=last_url,
                action_image_seq_urls=seq_urls,
                action_image_seq=seq_items,
            )
        )

    return ProjectImagesResponse(
        project_id=project_id,
        characters=chars,
        locations=locs,
        products=prods,
        scene_refs=scene_refs,
    )
