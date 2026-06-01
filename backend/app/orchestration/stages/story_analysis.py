"""Stage 1: story analysis — extract beats/characters/locations for the active episode.

Reads/writes the EPISODE's story_text + analysis columns. Characters/locations/
products stay project-scoped (shared across episodes). If episode.theme_hint
is set and original_story_text is empty, a theme-expansion sub-step LLM-fills
the story first."""

from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.story_analyst import StoryAnalystAgent
from app.agents.theme_expander import ThemeExpanderAgent
from app.database import async_session_factory
from app.models.character import Character
from app.models.episode import Episode, EpisodeStatus
from app.models.location import Location
from app.models.product import Product
from app.models.project import Project, ProjectStatus
from app.models.render_job import JobStatus, JobType, RenderJob
from app.orchestration._common import assert_project_active, get_llm_provider
from app.orchestration.episode_helpers import resolve_active_episode

logger = logging.getLogger(__name__)


def _create_characters(db: AsyncSession, project_id: UUID, characters_data: list[dict[str, Any]]) -> None:
    for char_data in characters_data:
        physical = (
            f"Gender: {char_data.get('gender', 'N/A')} | "
            f"Ethnicity: {char_data.get('ethnicity', 'N/A')} | "
            f"Skin tone: {char_data.get('skin_tone', 'N/A')} | "
            f"{char_data.get('physical_description', '')}"
        )
        kind = (char_data.get("character_kind") or "human").strip().lower()
        if kind not in {"human", "mascot", "creature", "object"}:
            kind = "human"
        db.add(Character(
            project_id=project_id,
            canonical_name=char_data.get("canonical_name", "Unknown"),
            character_kind=kind,
            physical_description=physical,
            clothing_description=char_data.get("clothing_description"),
            personality_notes=char_data.get("personality_notes"),
            voice_notes=char_data.get("voice_notes"),
        ))


def _create_locations(db: AsyncSession, project_id: UUID, locations_data: list[dict[str, Any]]) -> None:
    for loc_data in locations_data:
        db.add(Location(
            project_id=project_id,
            name=loc_data.get("name", "Unknown"),
            description=loc_data.get("description"),
        ))


def _create_products(db: AsyncSession, project_id: UUID, products_data: list[dict[str, Any]]) -> None:
    for p in products_data or []:
        db.add(Product(
            project_id=project_id,
            canonical_name=p.get("canonical_name", "Unknown product"),
            category=p.get("category"),
            physical_description=p.get("physical_description"),
            brand_marks=p.get("brand_marks"),
            color_palette=p.get("color_palette"),
            hero_angle=p.get("hero_angle"),
        ))


async def _already_analyzed(db: AsyncSession, episode: Episode) -> bool:
    has_beats = False
    if episode.beat_list_json:
        try:
            has_beats = bool(json.loads(episode.beat_list_json))
        except json.JSONDecodeError:
            logger.warning("Corrupt beat_list_json on episode %s — re-analyzing", episode.id)
            has_beats = False
    return bool(has_beats)


async def _load_project_cast(db: AsyncSession, project_id: UUID) -> tuple[list[dict], list[dict]]:
    chars = (await db.execute(
        select(Character).where(Character.project_id == project_id)
    )).scalars().all()
    locs = (await db.execute(
        select(Location).where(Location.project_id == project_id)
    )).scalars().all()
    return (
        [{
            "canonical_name": c.canonical_name,
            "character_kind": c.character_kind,
            "physical_description": c.physical_description,
        } for c in chars],
        [{"name": l.name, "description": l.description} for l in locs],
    )


async def _load_prior_episode_summaries(
    db: AsyncSession, project_id: UUID, current_order_index: int,
) -> list[dict]:
    rows = (await db.execute(
        select(Episode)
        .where(Episode.project_id == project_id)
        .where(Episode.order_index < current_order_index)
        .order_by(Episode.order_index)
    )).scalars().all()
    out = []
    for ep in rows:
        beats = []
        if ep.beat_list_json:
            try:
                beats = json.loads(ep.beat_list_json)
            except json.JSONDecodeError:
                beats = []
        out.append({
            "order_index": ep.order_index,
            "title": ep.title,
            "summary": ep.story_summary or "",
            "beats": beats,
        })
    return out


async def _expand_theme(
    db: AsyncSession, episode: Episode, project_id: UUID,
) -> str:
    chars, locs = await _load_project_cast(db, project_id)
    prior = await _load_prior_episode_summaries(db, project_id, episode.order_index)
    if not episode.continue_from_previous:
        prior = []
    agent = ThemeExpanderAgent(get_llm_provider())
    result = await agent.run({
        "theme": episode.theme_hint or "",
        "duration_seconds": episode.target_duration_seconds or 30.0,
        "characters": chars,
        "locations": locs,
        "prior_episodes": prior,
    })
    if not result.success:
        raise RuntimeError(f"Theme expansion failed: {result.errors}")
    return result.data["story_text"]


async def run(project_id: str) -> None:
    async with async_session_factory() as db:
        project = await assert_project_active(db, project_id, "story_analysis")

        episode = await resolve_active_episode(db, project_id)
        if episode is None:
            raise RuntimeError(f"No episode found for project {project_id}")

        if await _already_analyzed(db, episode):
            logger.info("Episode %s already analyzed, skipping", episode.id)
            episode.status = EpisodeStatus.planning
            project.status = ProjectStatus.planning
            await db.commit()
            return

        if (not (episode.original_story_text or "").strip()
                and (episode.theme_hint or "").strip()):
            logger.info("Episode %s has theme_hint — expanding to story", episode.id)
            episode.original_story_text = await _expand_theme(db, episode, project.id)
            await db.flush()

        if not (episode.original_story_text or "").strip():
            raise RuntimeError(
                f"Episode {episode.id} has neither theme_hint nor original_story_text"
            )

        # Mirror to project.original_story_text so the scanner's NOT-NULL gate
        # plus older code paths reading from the project still work.
        project.original_story_text = episode.original_story_text

        job = RenderJob(
            project_id=project.id, job_type=JobType.story_analysis,
            status=JobStatus.running,
        )
        db.add(job)
        project.status = ProjectStatus.analyzing
        episode.status = EpisodeStatus.analyzing
        await db.flush()

        job.payload_json = json.dumps({
            "model": "default",
            "system_prompt_path": "app/prompts/story_analyst.txt",
            "episode_id": str(episode.id),
            "episode_order_index": episode.order_index,
            "story_chars": len(episode.original_story_text or ""),
            "target_duration_seconds": episode.target_duration_seconds,
        })

        try:
            agent = StoryAnalystAgent(get_llm_provider())
            result = await agent.run({
                "story_text": episode.original_story_text,
                "target_duration": episode.target_duration_seconds
                    or project.total_target_duration_seconds,
            })
            if not result.success:
                raise RuntimeError(f"Analysis failed: {result.errors}")

            data = result.data
            episode.story_summary = data.get("story_summary", "")
            episode.beat_list_json = json.dumps(data.get("beats", []))
            episode.pacing_notes = data.get("pacing_notes", "")
            episode.style_lock = data.get("style_lock", "")

            # Mirror to project for backwards-compat readers.
            project.story_summary = episode.story_summary
            project.beat_list_json = episode.beat_list_json
            project.pacing_notes = episode.pacing_notes
            project.style_lock = episode.style_lock

            # Project-scoped cast: only create entries that don't yet exist
            # (later episodes reuse the cast established in earlier ones).
            existing_chars = await db.scalar(
                select(func.count(Character.id)).where(Character.project_id == project.id)
            )
            if not existing_chars:
                _create_characters(db, project.id, data.get("characters", []))
            existing_locs = await db.scalar(
                select(func.count(Location.id)).where(Location.project_id == project.id)
            )
            if not existing_locs:
                _create_locations(db, project.id, data.get("locations", []))
            existing_prods = await db.scalar(
                select(func.count(Product.id)).where(Product.project_id == project.id)
            )
            if not existing_prods:
                _create_products(db, project.id, data.get("products", []))

            job.status = JobStatus.complete
            job.result_json = json.dumps({
                "summary": episode.story_summary,
                "style_lock": episode.style_lock,
                "characters": len(data.get("characters", [])),
                "locations": len(data.get("locations", [])),
                "products": len(data.get("products", []) or []),
                "beats": len(data.get("beats", [])),
            })
            episode.status = EpisodeStatus.planning
            project.status = ProjectStatus.planning

        except Exception as e:
            logger.exception("Story analysis failed")
            job.status = JobStatus.failed
            job.error_text = str(e)
            episode.status = EpisodeStatus.failed
            project.status = ProjectStatus.failed
            await db.commit()
            raise

        await db.commit()
