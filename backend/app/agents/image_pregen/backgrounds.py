"""Generate one SD3.5 background plate per location."""

from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.image_pregen._assets import safe_name, save_asset
from app.agents.image_pregen.prompts import build_background_prompt
from app.config import settings
from app.models.asset import AssetType
from app.models.location import Location
from app.providers.image.base import ImageSettings

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
    locations = (await db.execute(
        select(Location).where(Location.project_id == project_uuid)
    )).scalars().all()

    pending = [
        loc for loc in locations
        if not (loc.reference_image_path and Path(loc.reference_image_path).exists())
    ]
    for loc in locations:
        if loc not in pending:
            logger.info("Location '%s' background already exists, reusing", loc.name)
    await asyncio.gather(*[
        _generate_one(db, project_uuid, image_provider, llm, loc, story_summary, errors, db_lock)
        for loc in pending
    ])
    await db.commit()


async def _generate_one(
    db: AsyncSession,
    project_uuid: uuid.UUID,
    image_provider,
    llm,
    loc: Location,
    story_summary: str,
    errors: list[str],
    db_lock: "asyncio.Lock | None" = None,
) -> None:
    logger.info("Generating background for location: %s", loc.name)
    try:
        prompt, neg = await build_background_prompt(llm, loc, story_summary=story_summary)
        output_path = (
            settings.storage_root / "backgrounds" / str(project_uuid)
            / f"{safe_name(loc.name)}.png"
        )
        result = await image_provider.generate_image(
            prompt=prompt,
            negative_prompt=neg,
            output_path=output_path,
            settings=ImageSettings(
                width=settings.sd35_bg_width,
                height=settings.sd35_bg_height,
                num_inference_steps=settings.sd35_steps,
                guidance_scale=settings.sd35_guidance,
            ),
        )
        if not result.success:
            logger.warning("Background failed for %s: %s", loc.name, result.error)
            errors.append(f"Background failed ({loc.name}): {result.error}")
            return

        async def _persist():
            loc.reference_image_path = result.file_path
            await save_asset(db, project_uuid, AssetType.background_ref, result.file_path, loc.name)
        if db_lock is not None:
            async with db_lock:
                await _persist()
        else:
            await _persist()
        logger.info("Background saved for %s → %s", loc.name, result.file_path)
    except Exception as e:
        logger.exception("Background generation error for %s", loc.name)
        errors.append(f"Background exception ({loc.name}): {e}")
