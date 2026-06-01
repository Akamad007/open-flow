"""Stage 2: scene planning — break beats into ~4s scenes with timing."""

from __future__ import annotations

import json
import logging
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.scene_planner import ScenePlannerAgent
from app.database import async_session_factory
from app.models.character import Character
from app.models.episode import Episode, EpisodeStatus
from app.models.location import Location
from app.models.product import Product
from app.models.project import ProjectStatus
from app.models.render_job import JobStatus, JobType, RenderJob
from app.models.scene import Scene, SceneStatus, scene_products
from app.orchestration._common import assert_project_active, get_llm_provider
from app.orchestration.episode_helpers import resolve_active_episode

logger = logging.getLogger(__name__)


async def _load_characters_for_planner(db: AsyncSession, project_id: UUID) -> list[dict[str, Any]]:
    result = await db.execute(select(Character).where(Character.project_id == project_id))
    return [
        {"canonical_name": c.canonical_name, "physical_description": c.physical_description}
        for c in result.scalars().all()
    ]


async def _load_locations_for_planner(db: AsyncSession, project_id: UUID) -> list[dict[str, Any]]:
    result = await db.execute(select(Location).where(Location.project_id == project_id))
    return [{"name": l.name, "description": l.description} for l in result.scalars().all()]


async def _load_products_for_planner(db: AsyncSession, project_id: UUID) -> list[dict[str, Any]]:
    result = await db.execute(select(Product).where(Product.project_id == project_id))
    return [
        {
            "canonical_name": p.canonical_name,
            "category": p.category,
            "physical_description": p.physical_description,
            "brand_marks": p.brand_marks,
        }
        for p in result.scalars().all()
    ]


async def _load_single_product(db: AsyncSession, project_id: UUID) -> Product | None:
    """v1: cap=1, so we always link the single project-product to every scene
    where shows_product=true. Returns None for non-branded ads."""
    result = await db.execute(select(Product).where(Product.project_id == project_id))
    return result.scalars().first()


def _strip_parens(name: str) -> str:
    """'Farmer (unseen, hands only)' → 'farmer'."""
    import re
    return re.sub(r"\s*\(.*?\)\s*", " ", name).strip().lower()


async def _build_lookups(
    db: AsyncSession, project_id: UUID,
) -> tuple[dict[str, Character], dict[str, Any]]:
    """Build name → object maps with multiple aliases per character/location.

    LLM planners often emit shortened names ("Farmer") that don't exact-match
    the canonical name ("Farmer (unseen, hands only)"). We register several
    keys per entity so the lookup tolerates these variations.
    """
    char_lookup: dict[str, Character] = {}
    chars = await db.execute(select(Character).where(Character.project_id == project_id))
    for char in chars.scalars().all():
        keys = {char.canonical_name.lower(), _strip_parens(char.canonical_name)}
        for key in keys:
            if key:
                char_lookup.setdefault(key, char)

    loc_lookup: dict[str, object] = {}
    locs = await db.execute(select(Location).where(Location.project_id == project_id))
    for loc in locs.scalars().all():
        keys = {loc.name.lower(), _strip_parens(loc.name)}
        for key in keys:
            if key:
                loc_lookup.setdefault(key, loc.id)

    return char_lookup, loc_lookup


def _resolve_char(name: str, char_lookup: dict[str, Character]) -> Character | None:
    """Look up a character by exact / paren-stripped / substring match."""
    if not name:
        return None
    n = name.lower().strip()
    if n in char_lookup:
        return char_lookup[n]
    n_stripped = _strip_parens(name)
    if n_stripped in char_lookup:
        return char_lookup[n_stripped]
    # Substring fallback: planner says "Farmer", DB key "farmer" matches because
    # we registered the paren-stripped form above. But if the LLM says
    # "the farmer's hands", fall back to substring containment in either direction.
    for key, char in char_lookup.items():
        if key and (key in n or n in key or key in n_stripped):
            return char
    return None


def _resolve_loc_id(name: str, loc_lookup: dict[str, Any]) -> Optional[UUID]:
    if not name:
        return None
    n = name.lower().strip()
    if n in loc_lookup:
        return loc_lookup[n]
    n_stripped = _strip_parens(name)
    if n_stripped in loc_lookup:
        return loc_lookup[n_stripped]
    for key, loc_id in loc_lookup.items():
        if key and (key in n or n in key):
            return loc_id
    return None


def _build_scene(
    scene_data: dict[str, Any],
    project_id: UUID,
    episode_id: UUID,
    loc_lookup: dict[str, Any],
    char_lookup: dict[str, Character],
) -> tuple[Scene, float]:
    loc_name = scene_data.get("location_name", "")
    loc_id = _resolve_loc_id(loc_name, loc_lookup)

    scene = Scene(
        project_id=project_id,
        episode_id=episode_id,
        order_index=scene_data.get("order_index", 0),
        source_excerpt=scene_data.get("source_excerpt"),
        duration_seconds=scene_data.get("duration_seconds", 4.0),
        scene_purpose=scene_data.get("scene_purpose"),
        visual_summary=scene_data.get("visual_summary"),
        audio_alignment_notes=scene_data.get("audio_alignment_notes"),
        continuity_from_previous=scene_data.get("continuity_from_previous"),
        continuity_to_next=scene_data.get("continuity_to_next"),
        location_id=loc_id,
        status=SceneStatus.planned,
    )
    for cname in scene_data.get("character_names", []):
        char_obj = _resolve_char(cname, char_lookup)
        if char_obj:
            if char_obj not in scene.characters:
                scene.characters.append(char_obj)
        else:
            logger.warning(
                "Scene %d references unknown character '%s' — skipping link",
                scene_data.get("order_index", 0), cname,
            )
    return scene, scene.duration_seconds


async def _link_product_to_scene(
    db: AsyncSession, scene_id: UUID, product_id: UUID, role: str,
) -> None:
    """Insert into scene_products with the planner's role + shows_product=true."""
    await db.execute(
        scene_products.insert().values(
            scene_id=scene_id,
            product_id=product_id,
            product_role=role or "holding",
            shows_product=True,
        )
    )


async def run(project_id: str) -> None:
    async with async_session_factory() as db:
        project = await assert_project_active(db, project_id, "scene_planning")
        episode = await resolve_active_episode(db, project_id)
        if episode is None:
            raise RuntimeError(f"No episode for project {project_id}")

        scene_count = await db.scalar(
            select(func.count(Scene.id)).where(Scene.episode_id == episode.id)
        )
        if scene_count and scene_count > 0:
            logger.info("Scenes already exist (%d), skipping planning", scene_count)
            project.status = ProjectStatus.prompting
            episode.status = EpisodeStatus.prompting
            await db.commit()
            return

        job = RenderJob(
            project_id=project.id, job_type=JobType.scene_planning,
            status=JobStatus.running,
        )
        db.add(job)
        await db.flush()

        try:
            chars = await _load_characters_for_planner(db, project.id)
            locs = await _load_locations_for_planner(db, project.id)
            products = await _load_products_for_planner(db, project.id)
            try:
                beats = json.loads(episode.beat_list_json or "[]")
            except json.JSONDecodeError:
                logger.warning("Corrupt beat_list_json on episode %s — using empty beats", episode.id)
                beats = []

            target_total = (
                episode.target_duration_seconds
                or project.total_target_duration_seconds
            )
            job.payload_json = json.dumps({
                "system_prompt_path": "app/prompts/scene_planner.txt",
                "episode_id": str(episode.id),
                "episode_order_index": episode.order_index,
                "target_total_duration_seconds": target_total,
                "target_scene_duration": 5.0,
                "num_beats": len(beats),
                "num_characters": len(chars),
                "num_locations": len(locs),
                "num_products": len(products),
            })
            await db.flush()

            agent = ScenePlannerAgent(get_llm_provider())
            result = await agent.run({
                "story_text": episode.original_story_text,
                "beats": beats,
                "characters": chars,
                "locations": locs,
                "products": products,
                "target_total_duration": target_total,
                "target_scene_duration": 5.0,   # matches Wan22's fixed 5.04s render (121 frames @ 24fps)
            })
            if not result.success:
                raise RuntimeError(f"Scene planning failed: {result.errors}")

            char_lookup, loc_lookup = await _build_lookups(db, project.id)
            single_product = await _load_single_product(db, project.id)

            total_duration = 0.0
            prev_loc_id = None
            scene_links: list[tuple[Scene, dict]] = []
            for scene_data in result.data.get("scenes", []):
                scene, dur = _build_scene(scene_data, project.id, episode.id, loc_lookup, char_lookup)
                # Reuse previous scene's location if planner left it null OR
                # invented an unknown name. Keeps backgrounds stable across
                # consecutive scenes the planner forgot to anchor.
                if scene.location_id is None and prev_loc_id is not None:
                    logger.info(
                        "Scene %d location was null/unknown — reusing previous scene's location",
                        scene.order_index,
                    )
                    scene.location_id = prev_loc_id
                prev_loc_id = scene.location_id or prev_loc_id
                db.add(scene)
                total_duration += dur
                scene_links.append((scene, scene_data))

            # Flush so scenes get IDs, then link products via the M2M (which
            # carries product_role + shows_product).
            await db.flush()
            if single_product is not None:
                for scene, scene_data in scene_links:
                    if scene_data.get("shows_product", True):
                        role = scene_data.get("product_role") or "holding"
                        if role == "none":
                            continue
                        await _link_product_to_scene(
                            db, scene.id, single_product.id, role,
                        )

            if not episode.target_duration_seconds:
                episode.target_duration_seconds = total_duration
            if not project.total_target_duration_seconds:
                project.total_target_duration_seconds = total_duration
            episode.status = EpisodeStatus.prompting
            project.status = ProjectStatus.prompting
            job.status = JobStatus.complete
            job.result_json = json.dumps({
                "scene_count": len(result.data.get("scenes", [])),
                "total_duration": total_duration,
            })

        except Exception as e:
            logger.exception("Scene planning failed")
            job.status = JobStatus.failed
            job.error_text = str(e)
            episode.status = EpisodeStatus.failed
            project.status = ProjectStatus.failed
            await db.commit()
            raise

        await db.commit()
