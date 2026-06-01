"""F-CANON-PORTRAIT (iter7): generate ONLY per-project character portraits.

Lightweight cousin of `image_pregen.run` — runs JUST `character_portraits.
generate_all` to populate `character.reference_image_path` for every linked
character, then advances project status. Skips backgrounds, products, and
action stills (those caused stiff poses; do not revert per FIXES_LOG).

The portrait becomes the LTX `--character-image` anchor at frame 0 of every
scene, killing inter-scene face drift without re-introducing the
heavy-handed action-still pipeline.
"""

from __future__ import annotations

import json
import logging

from sqlalchemy import func, select

from app.agents.image_pregen import character_portraits
from app.config import settings
from app.database import async_session_factory
from app.models.character import Character
from app.models.project import ProjectStatus
from app.models.render_job import JobStatus, JobType, RenderJob
from app.orchestration._common import (
    assert_project_active, get_image_provider, get_llm_provider,
)

logger = logging.getLogger(__name__)


async def run(project_id: str) -> None:
    async with async_session_factory() as db:
        project = await assert_project_active(db, project_id, "canonical_portrait")

        num_chars = await db.scalar(
            select(func.count(Character.id)).where(Character.project_id == project.id)
        ) or 0
        if num_chars == 0:
            logger.info("canonical_portrait: no characters linked, skipping")
            project.status = ProjectStatus.image_pregen
            await db.commit()
            return

        job = RenderJob(
            project_id=project.id, job_type=JobType.image_pregen,
            status=JobStatus.running,
            payload_json=json.dumps({
                "stage": "canonical_portrait",
                "provider": settings.image_provider,
                "num_characters": num_chars,
            }),
        )
        db.add(job)
        project.status = ProjectStatus.image_pregen
        await db.flush()

        errors: list[str] = []
        try:
            await character_portraits.generate_all(
                db=db,
                project_uuid=project.id,
                image_provider=get_image_provider(),
                llm=get_llm_provider(),
                story_summary=project.story_summary or "",
                errors=errors,
            )
            job.status = JobStatus.complete if not errors else JobStatus.failed
            job.result_json = json.dumps({"errors": errors})
            if errors:
                job.error_text = "; ".join(errors)
                logger.warning(
                    "canonical_portrait: %d portrait error(s) — non-fatal, continuing",
                    len(errors),
                )
        except Exception as e:
            logger.exception("canonical_portrait failed (non-fatal)")
            job.status = JobStatus.failed
            job.error_text = str(e)
        finally:
            try:
                from app.utils.daemon_pool import get_instantid_manager
                mgr = get_instantid_manager()
                if mgr is not None:
                    mgr.shutdown_all()
            except Exception:
                logger.exception("instantid daemon shutdown_all failed")

        await db.commit()
