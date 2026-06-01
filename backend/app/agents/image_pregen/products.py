"""Generate one SD 3.5 hero shot per product (with bg removal).

Each project has at most 1 product (cap enforced upstream). The hero shot
is rendered ONCE and re-used as the SD 3.5 img2img init image when the
per-second action stills are generated, so the product appears coherently
across every frame of the ad.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.image_pregen._assets import safe_name, save_asset
from app.agents.image_pregen.prompts import build_product_prompt
from app.config import settings
from app.models.asset import AssetType
from app.models.product import Product
from app.providers.image.base import ImageSettings
from app.utils.scene_compositor import remove_background

logger = logging.getLogger(__name__)


async def generate_all(
    db: AsyncSession,
    project_uuid: uuid.UUID,
    image_provider,
    llm,
    story_summary: str,
    errors: list[str],
    db_lock: "asyncio.Lock | None" = None,
) -> None:
    products = (await db.execute(
        select(Product).where(Product.project_id == project_uuid)
    )).scalars().all()
    if not products:
        logger.info("No products linked to project — skipping product hero shots")
        return
    logger.info("Rendering hero shots for %d product(s)", len(products))

    # Pre-link any user-uploaded product refs to matching Product rows so the
    # `prod.user_uploaded_path` branch below catches them.
    from app.agents.image_pregen.uploads_link import link_product_uploads
    await link_product_uploads(db, project_uuid, products)

    pending: list[Product] = []
    for prod in products:
        if prod.user_uploaded_path and Path(prod.user_uploaded_path).exists():
            prod.reference_image_path = prod.user_uploaded_path
            logger.info(
                "Product '%s': using user-uploaded asset %s",
                prod.canonical_name, prod.user_uploaded_path,
            )
            continue
        if prod.reference_image_path and Path(prod.reference_image_path).exists():
            logger.info("Product '%s' hero already exists, reusing", prod.canonical_name)
            continue
        pending.append(prod)
    await asyncio.gather(*[
        _generate_one(db, project_uuid, image_provider, llm, p, story_summary, errors, db_lock)
        for p in pending
    ])
    await db.commit()


async def _generate_one(
    db: AsyncSession,
    project_uuid: uuid.UUID,
    image_provider,
    llm,
    prod: Product,
    story_summary: str,
    errors: list[str],
    db_lock: "asyncio.Lock | None" = None,
) -> None:
    logger.info("Generating hero shot for product: %s", prod.canonical_name)
    try:
        prompt, neg = await build_product_prompt(llm, prod, story_summary=story_summary)
        output_path = (
            settings.storage_root / "products" / str(project_uuid)
            / f"{safe_name(prod.canonical_name)}.png"
        )
        # Square canvas for product shots — works well for img2img init when
        # baked into a portrait or wide action still.
        result = await image_provider.generate_image(
            prompt=prompt,
            negative_prompt=neg,
            output_path=output_path,
            settings=ImageSettings(
                width=1024,
                height=1024,
                num_inference_steps=settings.sd35_steps,
                guidance_scale=settings.sd35_guidance,
            ),
        )
        if not result.success:
            logger.warning("Product hero failed for %s: %s", prod.canonical_name, result.error)
            errors.append(f"Product hero failed ({prod.canonical_name}): {result.error}")
            return

        # Remove the studio backdrop so the product can later composite cleanly
        # over a character/location frame. Keep an opaque sidecar for inspection.
        remove_background(result.file_path)
        async def _persist():
            prod.reference_image_path = result.file_path
            await save_asset(
                db, project_uuid, AssetType.product_ref, result.file_path, prod.canonical_name,
            )
        if db_lock is not None:
            async with db_lock:
                await _persist()
        else:
            await _persist()
        logger.info(
            "Product hero saved (bg removed) for %s → %s",
            prod.canonical_name, result.file_path,
        )
    except Exception as e:
        logger.exception("Product hero generation error for %s", prod.canonical_name)
        errors.append(f"Product hero exception ({prod.canonical_name}): {e}")
