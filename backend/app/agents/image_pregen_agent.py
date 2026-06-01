"""Image pre-gen coordinator — runs portrait, background, and action-still passes."""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import func, select

from app.agents.base import AgentResult, BaseAgent
from app.agents.image_pregen import action_stills, backgrounds, character_portraits, products
from app.models.character import Character
from app.models.location import Location
from app.models.product import Product
from app.providers.image.base import ImageProvider

logger = logging.getLogger(__name__)


class ImagePreGenAgent(BaseAgent):
    """Runs the four image-generation passes in order:
    portraits → backgrounds → products → action stills.

    `image_provider` is the SD3.5/stub provider used for portraits,
    backgrounds, products, and the t2i action-still path. `identity_provider`
    is optional — when supplied AND `supports_identity=True`, action stills
    for human characters route through it (InstantID-XL face lock). Falls
    back to `image_provider` otherwise.
    """

    def __init__(self, image_provider: ImageProvider, llm,
                 identity_provider: ImageProvider | None = None):
        super().__init__(llm=llm)
        self.image_provider = image_provider
        self.identity_provider = identity_provider

    async def run(self, context: dict[str, Any]) -> AgentResult:
        project_id = context.get("project_id")
        db: AsyncSession = context.get("db")
        story_summary = context.get("story_summary", "")

        if not project_id or not db:
            return AgentResult(success=False, errors=["project_id and db required"])

        project_uuid = uuid.UUID(project_id) if isinstance(project_id, str) else project_id
        errors: list[str] = []

        # Profile gates which sub-stages run. Phantom-Wan text-only profile
        # uses only the canonical portrait — no action stills (InstantID
        # daemon dependency, slow, and the provider drops them anyway via
        # `pin_action_stills=False` in scene_video.py).
        from app.models.project import Project as _Project
        from app.orchestration.profiles import get_profile
        proj = await db.get(_Project, project_uuid)
        profile = get_profile(proj.pipeline_profile if proj else None)
        run_action_stills = profile.image_pregen_enabled and profile.pin_action_stills

        n_chars = await db.scalar(
            select(func.count(Character.id)).where(Character.project_id == project_uuid)
        ) or 0
        n_locs = await db.scalar(
            select(func.count(Location.id)).where(Location.project_id == project_uuid)
        ) or 0
        n_prods = await db.scalar(
            select(func.count(Product.id)).where(Product.project_id == project_uuid)
        ) or 0

        # Phase A: portraits + backgrounds run concurrently. No
        # interdependencies; the GPU pool throttles parallel image-gen
        # subprocesses across both GPUs. Shared db_lock keeps DB writes
        # serialized on the AsyncSession.
        # Phase B: action_stills runs after Phase A — stills need portraits
        # for InstantID identity reference.
        # NOTE: products hero-shot rendering is intentionally skipped —
        # the post-hoc compositor produced unusable artifacts (oversized
        # bottles, ghosted wallets, double-backpacks) so the entire
        # product-placement path is removed. Products may still be
        # extracted into the DB during story_analysis; they're just no
        # longer rendered or composited.
        # Sequential — asyncio.gather + shared AsyncSession triggers asyncpg
        # "another operation in progress" when inner helpers issue queries
        # outside the explicit db_lock window.
        db_lock = asyncio.Lock()
        await character_portraits.generate_all(
            db, project_uuid, self.image_provider, self.llm,
            story_summary, errors, db_lock=db_lock,
        )
        await backgrounds.generate_all(
            db, project_uuid, self.image_provider, self.llm,
            story_summary, errors, db_lock=db_lock,
        )
        if run_action_stills:
            scenes_done = await action_stills.generate_all(
                db, project_uuid, self.image_provider, self.llm, story_summary,
                identity_provider=self.identity_provider,
            )
        else:
            logger.info(
                "Skipping action_stills (profile %s does not pin them)",
                profile.name,
            )
            scenes_done = 0

        return AgentResult(
            success=len(errors) == 0 or scenes_done > 0,
            data={
                "characters_processed": n_chars,
                "locations_processed": n_locs,
                "products_processed": n_prods,
                "action_scenes_generated": scenes_done,
                "errors": errors,
            },
            errors=errors,
        )
