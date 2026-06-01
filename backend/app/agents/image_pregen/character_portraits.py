"""Generate one SD3.5 portrait per character (with bg removal).

Saves an opaque sidecar `<name>_opaque.png` next to the bg-removed
canonical PNG. The opaque copy is what InstantID/InsightFace consume —
they need a real RGB image to detect a face. The bg-removed canonical is
what LTX-Video composites onto location plates."""

from __future__ import annotations

import asyncio
import logging
import random
import shutil
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.image_pregen._assets import safe_name, save_asset
from app.agents.image_pregen.prompts import build_character_prompt
from app.config import settings
from app.models.asset import AssetType
from app.models.character import Character
from app.models.scene import Scene, scene_characters
from app.providers.image.base import ImageSettings
from app.utils.scene_compositor import remove_background


def opaque_sidecar_path(reference_image_path: str) -> Path:
    """Convention: opaque copy lives next to the canonical bg-removed PNG."""
    p = Path(reference_image_path)
    return p.with_name(p.stem + "_opaque.png")

logger = logging.getLogger(__name__)


# A standing person's bounding box is tall and narrow — head is ~13% of
# height, shoulders are ~25% of height. If the bbox aspect (h/w) is below
# this, the foreground is a torso/bust shot, not a full-body portrait.
# Empirically, full-body bbox aspect is 2.5–4.0; bust shots cluster at
# 1.0–1.8. Threshold at 2.2 with margin.
_FULL_BODY_BBOX_ASPECT_MIN = 2.2


def _is_full_body_portrait(image_path: str) -> tuple[bool, float]:
    """Inspect the rembg alpha channel of `image_path`. Returns (ok, aspect)
    where aspect is bbox_height / bbox_width of the foreground. ok=True
    means the foreground is plausibly a head-to-toe standing person."""
    from PIL import Image
    with Image.open(image_path) as im:
        if im.mode != "RGBA":
            return True, 0.0  # No alpha to judge — trust the model.
        bbox = im.split()[-1].getbbox()
    if bbox is None:
        return False, 0.0
    x0, y0, x1, y1 = bbox
    w, h = max(1, x1 - x0), max(1, y1 - y0)
    return (h / w) >= _FULL_BODY_BBOX_ASPECT_MIN, h / w


def _is_nonhuman_char(char: Character) -> bool:
    """Mascots / creatures / objects don't have human proportions, so the
    full-body bbox-aspect critic doesn't apply — skip the retry loop."""
    return (getattr(char, "character_kind", None) or "human").strip().lower() in {
        "mascot", "creature", "object",
    }


async def generate_all(
    db: AsyncSession,
    project_uuid: uuid.UUID,
    image_provider,
    llm,
    story_summary: str,
    errors: list[str],
    db_lock: "asyncio.Lock | None" = None,
) -> None:
    # Only render portraits for characters actually linked to at least one
    # scene. Story analysis can over-extract (e.g. characters merely
    # referenced in narration); rendering them wastes ~60s of GPU each and
    # they're never used downstream.
    linked_subq = (
        select(scene_characters.c.character_id)
        .join(Scene, Scene.id == scene_characters.c.scene_id)
        .where(Scene.project_id == project_uuid)
    )
    chars = (await db.execute(
        select(Character)
        .where(Character.project_id == project_uuid)
        .where(Character.id.in_(linked_subq))
    )).scalars().all()
    logger.info("Rendering portraits for %d scene-linked character(s)", len(chars))

    # Pre-link any user-uploaded character refs to matching Character rows so
    # SD3.5 portrait gen skips them (they already have a reference_image_path).
    from app.agents.image_pregen.uploads_link import link_character_uploads
    await link_character_uploads(db, project_uuid, chars)

    pending = [
        c for c in chars
        if not (c.reference_image_path and Path(c.reference_image_path).exists())
    ]
    for c in chars:
        if c not in pending:
            logger.info("Character '%s' portrait already exists, reusing", c.canonical_name)
    await asyncio.gather(*[
        _generate_one(db, project_uuid, image_provider, llm, c, story_summary, errors, db_lock)
        for c in pending
    ])
    await db.commit()


async def _render_portrait_attempt(
    image_provider, prompt: str, neg: str, output_path: Path, seed: int,
):
    return await image_provider.generate_image(
        prompt=prompt,
        negative_prompt=neg,
        output_path=output_path,
        settings=ImageSettings(
            width=settings.sd35_char_width,
            height=settings.sd35_char_height,
            num_inference_steps=settings.sd35_steps,
            guidance_scale=settings.sd35_guidance,
            seed=seed,
        ),
    )


async def _generate_one(
    db: AsyncSession,
    project_uuid: uuid.UUID,
    image_provider,
    llm,
    char: Character,
    story_summary: str,
    errors: list[str],
    db_lock: "asyncio.Lock | None" = None,
) -> None:
    logger.info("Generating portrait for character: %s", char.canonical_name)
    try:
        prompt, neg = await build_character_prompt(llm, char, story_summary=story_summary)
        output_path = (
            settings.storage_root / "characters" / str(project_uuid)
            / f"{safe_name(char.canonical_name)}.png"
        )

        # Generate → bg-remove → bbox-check loop. If the foreground bbox is
        # too boxy (torso shot), retry with a different seed. We can't judge
        # head-to-toe before bg-removal because the alpha channel is what
        # gives us the bounding box.
        rng = random.Random(hash(char.canonical_name) & 0xFFFF)
        last_aspect = 0.0
        clean_path: str | None = None
        opaque: str | None = None
        for attempt in range(settings.portrait_critic_max_retries + 1):
            seed = rng.randint(1, 2**31 - 1)
            result = await _render_portrait_attempt(
                image_provider, prompt, neg, output_path, seed,
            )
            if not result.success:
                logger.warning("Portrait failed for %s: %s", char.canonical_name, result.error)
                errors.append(f"Character portrait failed ({char.canonical_name}): {result.error}")
                return

            opaque = str(Path(result.file_path).with_name(
                Path(result.file_path).stem + "_opaque.png"
            ))
            try:
                shutil.copy2(result.file_path, opaque)
            except OSError as e:
                logger.warning("Opaque sidecar copy failed for %s: %s", char.canonical_name, e)

            kind = (getattr(char, "character_kind", None) or "human").strip().lower()
            clean_path = remove_background(result.file_path, subject_kind=kind)
            if _is_nonhuman_char(char):
                # Non-human: any rendered bbox is acceptable (toothbrush, cloud,
                # bee etc. are not 2.2-tall). Accept the first attempt.
                last_aspect = 0.0
                logger.info(
                    "Portrait critic [%s] attempt %d: non-human kind=%s — accepting (no aspect check)",
                    char.canonical_name, attempt + 1, char.character_kind,
                )
                break
            ok, aspect = _is_full_body_portrait(clean_path)
            last_aspect = aspect
            logger.info(
                "Portrait critic [%s] attempt %d/%d: aspect=%.2f ok=%s seed=%d",
                char.canonical_name, attempt + 1,
                settings.portrait_critic_max_retries + 1, aspect, ok, seed,
            )
            if ok:
                break
            if attempt < settings.portrait_critic_max_retries:
                logger.warning(
                    "Portrait for %s rejected (bbox aspect %.2f < %.2f — torso shot). Regenerating with new seed.",
                    char.canonical_name, aspect, _FULL_BODY_BBOX_ASPECT_MIN,
                )

        async def _persist():
            char.reference_image_path = clean_path
            await save_asset(
                db, project_uuid, AssetType.character_ref, clean_path, char.canonical_name,
            )
        if db_lock is not None:
            async with db_lock:
                await _persist()
        else:
            await _persist()
        logger.info(
            "Portrait saved for %s → %s (opaque=%s, final bbox aspect=%.2f)",
            char.canonical_name, clean_path, opaque, last_aspect,
        )
    except Exception as e:
        logger.exception("Portrait generation error for %s", char.canonical_name)
        errors.append(f"Portrait exception ({char.canonical_name}): {e}")
