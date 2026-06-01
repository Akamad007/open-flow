"""Action stills — DELETED.

Action stills are no longer generated. The pipeline conditions scene 0 on
the uploaded/canonical character portrait and chains scenes N>0 off the
previous scene's last frame via Wan22 I2V. Kept as a module shim so any
remaining import (`from app.agents.image_pregen import action_stills`)
keeps working with a no-op `generate_all`.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.providers.image.base import ImageProvider

logger = logging.getLogger(__name__)


async def generate_all(
    db: AsyncSession,
    project_uuid: uuid.UUID,
    image_provider,
    llm,
    story_summary: str,
    identity_provider: ImageProvider | None = None,
) -> int:
    """No-op. Retained for backward compatibility with image_pregen_agent."""
    logger.info("action_stills.generate_all called — disabled, returning 0")
    return 0
