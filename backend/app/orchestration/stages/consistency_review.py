"""Stage 5: consistency critic — reviews scenes & may trigger a prompt-correction pass."""

from __future__ import annotations

import json
import logging

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.agents.consistency_critic import ConsistencyCriticAgent
from app.database import async_session_factory
from app.models.audio_plan import AudioPlan
from app.models.character import Character
from app.models.episode import EpisodeStatus
from app.models.project import ProjectStatus
from app.models.render_job import JobStatus, JobType, RenderJob
from app.models.scene import Scene
from app.config import settings
from app.orchestration._common import assert_project_active, get_llm_provider
from app.orchestration.episode_helpers import resolve_active_episode
from app.orchestration.stages import prompt_generation

logger = logging.getLogger(__name__)

MAX_CORRECTION_PASSES = 2


async def _already_reviewed(db, project_id) -> bool:
    count = await db.scalar(
        select(func.count(RenderJob.id))
        .where(RenderJob.project_id == project_id)
        .where(RenderJob.job_type == JobType.consistency_review)
        .where(RenderJob.status == JobStatus.complete)
    )
    return bool(count)


async def _load_scenes_for_review(db, episode_id):
    result = await db.execute(
        select(Scene).where(Scene.episode_id == episode_id)
        .options(
            selectinload(Scene.prompt),
            selectinload(Scene.characters),
            selectinload(Scene.location),
        )
        .order_by(Scene.order_index)
    )
    out = []
    for s in result.scalars().all():
        d = {
            "order_index": s.order_index,
            "duration_seconds": s.duration_seconds,
            "visual_summary": s.visual_summary,
            "character_names": [c.canonical_name for c in s.characters],
            "location_name": s.location.name if s.location else "",
            "continuity_from_previous": s.continuity_from_previous,
        }
        if s.prompt:
            d["video_prompt"] = s.prompt.video_prompt
        out.append(d)
    return out


async def _load_review_inputs(db, project_id, episode_id):
    scenes = await _load_scenes_for_review(db, episode_id)

    chars_result = await db.execute(select(Character).where(Character.project_id == project_id))
    chars = [
        {"canonical_name": c.canonical_name, "physical_description": c.physical_description}
        for c in chars_result.scalars().all()
    ]

    ap_result = await db.execute(select(AudioPlan).where(AudioPlan.episode_id == episode_id))
    ap = ap_result.scalar_one_or_none()
    audio_plan = {"total_estimated_audio_duration": ap.total_estimated_audio_duration if ap else 0}

    return scenes, chars, audio_plan


async def run(project_id: str) -> None:
    async with async_session_factory() as db:
        project = await assert_project_active(db, project_id, "consistency_review")
        episode = await resolve_active_episode(db, project_id)
        if episode is None:
            raise RuntimeError(f"No episode for project {project_id}")

        if await _already_reviewed(db, project.id):
            logger.info("Consistency review already complete, skipping")
            episode.status = EpisodeStatus.image_pregen
            project.status = ProjectStatus.image_pregen
            await db.commit()
            return

        job = RenderJob(
            project_id=project.id, job_type=JobType.consistency_review,
            status=JobStatus.running,
        )
        db.add(job)
        await db.flush()

        job.payload_json = json.dumps({
            "system_prompt_path": "app/prompts/consistency_critic.txt",
            "max_correction_passes": MAX_CORRECTION_PASSES,
            "gate_enabled": settings.consistency_gate_enabled,
        })

        try:
            agent = ConsistencyCriticAgent(get_llm_provider())
            passes: list[dict] = []
            final_data: dict | None = None

            for attempt in range(MAX_CORRECTION_PASSES + 1):
                scenes, chars, audio_plan = await _load_review_inputs(db, project.id, episode.id)
                result = await agent.run({
                    "scenes": scenes, "characters": chars, "audio_plan": audio_plan,
                })
                passes.append({
                    "attempt": attempt,
                    "approved": result.data.get("approved", True),
                    "overall_quality": result.data.get("overall_quality"),
                    "issues": result.data.get("issues", []),
                    "suggestions": result.data.get("suggestions", []),
                })
                final_data = result.data

                approved = result.data.get("approved", True)
                issues = result.data.get("issues", [])
                high_issues = [i for i in issues if i.get("severity") in ("medium", "high")]

                if approved or not high_issues:
                    logger.info("Critic approved on attempt %d", attempt + 1)
                    break

                if attempt >= MAX_CORRECTION_PASSES:
                    logger.warning(
                        "Critic still rejected after %d correction pass(es)",
                        MAX_CORRECTION_PASSES,
                    )
                    break

                logger.warning(
                    "Critic attempt %d: approved=False with %d medium/high "
                    "issues — running correction pass",
                    attempt + 1, len(high_issues),
                )
                feedback = {"issues": high_issues,
                           "suggestions": result.data.get("suggestions", [])}
                await db.commit()
                await prompt_generation.run(project_id, critique_feedback=feedback)

            job.status = JobStatus.complete
            job.result_json = json.dumps({
                **(final_data or {}),
                "passes": passes,
            })

            final_approved = (final_data or {}).get("approved", True)
            final_high_issues = [i for i in (final_data or {}).get("issues", [])
                                if i.get("severity") in ("medium", "high")]

            if not final_approved and final_high_issues and settings.consistency_gate_enabled:
                msg = (
                    f"Consistency critic still rejected after "
                    f"{MAX_CORRECTION_PASSES} correction pass(es): "
                    f"{len(final_high_issues)} medium/high issue(s). "
                    f"Set CONSISTENCY_GATE_ENABLED=false to override."
                )
                logger.error(msg)
                episode.status = EpisodeStatus.failed
                project.status = ProjectStatus.failed
                job.error_text = msg
                await db.commit()
                raise RuntimeError(msg)

            if not final_approved:
                logger.warning(
                    "Critic gate disabled — advancing to image_pregen with "
                    "unresolved issues."
                )
            episode.status = EpisodeStatus.image_pregen
            project.status = ProjectStatus.image_pregen

        except RuntimeError:
            raise
        except Exception as e:
            logger.exception("Consistency review failed")
            job.status = JobStatus.failed
            job.error_text = str(e)
            if settings.consistency_gate_enabled:
                episode.status = EpisodeStatus.failed
                project.status = ProjectStatus.failed
                await db.commit()
                raise
            episode.status = EpisodeStatus.image_pregen
            project.status = ProjectStatus.image_pregen

        await db.commit()
