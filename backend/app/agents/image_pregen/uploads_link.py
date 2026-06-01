"""Match user-uploaded character/product reference images to the LLM-extracted
Character / Product entities for a project, then pre-populate the right field
so the existing image-pregen sub-modules skip generation and reuse the upload.

Run at the start of `character_portraits.generate_all` and `products.generate_all`.
Pure DB read + write; no GPU.

Matching strategy: case-insensitive whole-word match between the upload label
(from Asset.metadata_json) and the entity's canonical_name. Bidirectional —
upload "Alice protagonist" matches Character "Alice", and vice versa.
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.asset import Asset, AssetType
from app.models.character import Character
from app.models.product import Product

logger = logging.getLogger(__name__)


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", text.lower()) if len(t) >= 2}


def label_matches_name(label: str | None, canonical_name: str | None) -> bool:
    """True iff the label and canonical_name share at least one meaningful
    word (token ≥ 2 chars, lowercase, alnum-only). Empty inputs → False."""
    if not label or not canonical_name:
        return False
    return bool(_tokens(label) & _tokens(canonical_name))


async def _user_upload_assets(
    db: AsyncSession, project_id: uuid.UUID, asset_type: AssetType,
) -> list[tuple[Asset, str]]:
    rows = (await db.execute(
        select(Asset).where(
            Asset.project_id == project_id,
            Asset.asset_type == asset_type,
            Asset.generation_provider == "user_upload",
        )
    )).scalars().all()
    out: list[tuple[Asset, str]] = []
    for a in rows:
        try:
            md = json.loads(a.metadata_json or "{}")
        except json.JSONDecodeError:
            md = {}
        label = (md.get("label") or "").strip()
        if label:
            out.append((a, label))
    return out


async def link_character_uploads(
    db: AsyncSession, project_id: uuid.UUID, characters: Iterable[Character],
) -> int:
    """For each Character with no reference_image_path yet, find a user-upload
    character_ref Asset whose label shares a word with the character's
    canonical_name and link it. Returns count linked."""
    uploads = await _user_upload_assets(db, project_id, AssetType.character_ref)
    if not uploads:
        return 0
    linked = 0
    for char in characters:
        if char.reference_image_path:
            continue
        for asset, label in uploads:
            if label_matches_name(label, char.canonical_name):
                char.reference_image_path = asset.file_path
                logger.info(
                    "Character '%s' linked to user upload '%s' (%s)",
                    char.canonical_name, label, asset.file_path,
                )
                linked += 1
                break
    if linked:
        await db.flush()
    return linked


async def link_product_uploads(
    db: AsyncSession, project_id: uuid.UUID, products: Iterable[Product],
) -> int:
    """For each Product with no user_uploaded_path yet, find a user-upload
    product_ref Asset whose label shares a word with the product's
    canonical_name and link it. Returns count linked.

    Sets `Product.user_uploaded_path` (not `reference_image_path`) because the
    existing products.generate_all() code path checks that field first and
    copies it onto `reference_image_path` itself — keeping the same code path
    for upload-driven vs generation-driven products.
    """
    uploads = await _user_upload_assets(db, project_id, AssetType.product_ref)
    if not uploads:
        return 0
    linked = 0
    for prod in products:
        if prod.user_uploaded_path:
            continue
        for asset, label in uploads:
            if label_matches_name(label, prod.canonical_name):
                prod.user_uploaded_path = asset.file_path
                logger.info(
                    "Product '%s' linked to user upload '%s' (%s)",
                    prod.canonical_name, label, asset.file_path,
                )
                linked += 1
                break
    if linked:
        await db.flush()
    return linked
