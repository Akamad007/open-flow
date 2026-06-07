"""Stage 3: visual prompt generation — two-pass for continuity."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.agents.lora_director import LoRADirectorAgent
from app.agents.visual_director import VisualDirectorAgent
from app.config import settings
from app.database import async_session_factory
from app.models.character import Character
from app.models.episode import EpisodeStatus
from app.models.product import Product
from app.models.project import ProjectStatus
from app.models.render_job import JobStatus, JobType, RenderJob
from app.models.scene import Scene, SceneStatus, scene_products
from app.models.scene_prompt import ScenePrompt
from app.orchestration._common import (
    assert_project_active, get_llm_provider, get_strong_llm_provider,
)
from app.orchestration.episode_helpers import get_episode, resolve_active_episode
from app.orchestration.profiles import get_profile

logger = logging.getLogger(__name__)


async def _all_scenes_have_prompts(db: AsyncSession, episode_id: UUID) -> bool:
    total = await db.scalar(select(func.count(Scene.id)).where(Scene.episode_id == episode_id))
    prompted = await db.scalar(
        select(func.count(ScenePrompt.id))
        .join(Scene, ScenePrompt.scene_id == Scene.id)
        .where(Scene.episode_id == episode_id)
        .where(ScenePrompt.video_prompt.isnot(None))
    )
    return bool(total and prompted and prompted >= total)


async def _load_unlocked_scenes(db: AsyncSession, episode_id: UUID) -> list[Scene]:
    result = await db.execute(
        select(Scene)
        .where(Scene.episode_id == episode_id, Scene.locked == False)
        .options(selectinload(Scene.prompt))
        .order_by(Scene.order_index)
    )
    return list(result.scalars().all())


async def _load_characters(db: AsyncSession, project_id: UUID) -> list[dict[str, Any]]:
    result = await db.execute(select(Character).where(Character.project_id == project_id))
    return [
        {
            "canonical_name": c.canonical_name,
            "physical_description": c.physical_description,
            "clothing_description": c.clothing_description,
        }
        for c in result.scalars().all()
    ]


async def _load_scene_product_links(db: AsyncSession, episode_id: UUID) -> dict[UUID, dict[str, Any]]:
    """scene_id → {product_dict, role}. Empty dict for non-branded ads."""
    rows = await db.execute(
        select(
            scene_products.c.scene_id,
            scene_products.c.product_role,
            Product,
        )
        .join(Product, Product.id == scene_products.c.product_id)
        .join(Scene, Scene.id == scene_products.c.scene_id)
        .where(Scene.episode_id == episode_id, scene_products.c.shows_product == True)
    )
    out: dict[UUID, dict[str, Any]] = {}
    for scene_id, role, prod in rows.all():
        out[scene_id] = {
            "product": {
                "canonical_name": prod.canonical_name,
                "category": prod.category,
                "physical_description": prod.physical_description,
                "brand_marks": prod.brand_marks,
                "color_palette": prod.color_palette,
                "hero_angle": prod.hero_angle,
            },
            "product_role": role,
        }
    return out


def _build_context(
    scenes: list[Scene],
    i: int,
    project: Any,
    characters: list[dict[str, Any]],
    prev_prompt: Optional[str],
    critique_feedback: Optional[dict[str, Any]],
    product_links: Optional[dict[UUID, dict[str, Any]]] = None,
) -> dict[str, Any]:
    scene = scenes[i]
    prev_scene = scenes[i - 1] if i > 0 else None
    next_scene = scenes[i + 1] if i < len(scenes) - 1 else None
    link = (product_links or {}).get(scene.id) or {}
    # Decide whether the video model gets a CURATED character image (portrait
    # or pre-generated action still). The last-frame chain provides continuity
    # but NOT identity — it's a prior video frame, not an anchor. If the
    # profile has no portrait + no still pre-gen (e.g. wan22_text_only), text
    # is the only identity signal, so the LLM must inject the full physical
    # description on every beat.
    profile = get_profile(project.pipeline_profile if project else None)
    has_char = bool(scene.characters)
    has_curated_image = profile.canonical_portrait_enabled or profile.image_pregen_enabled
    char_image_provided = has_char and has_curated_image
    episode = getattr(scene, "episode", None)
    story_summary = (getattr(episode, "story_summary", None) or project.story_summary or "")
    pacing_notes = (getattr(episode, "pacing_notes", None) or project.pacing_notes or "")
    style_lock = (getattr(episode, "style_lock", None) or project.style_lock or "")
    return {
        "story_summary": story_summary,
        "pacing_notes": pacing_notes,
        "style_lock": style_lock,
        "scene": {
            "order_index": scene.order_index,
            "duration_seconds": scene.duration_seconds,
            "scene_purpose": scene.scene_purpose,
            "visual_summary": scene.visual_summary,
            "source_excerpt": scene.source_excerpt,
            "continuity_from_previous": scene.continuity_from_previous,
            "continuity_to_next": scene.continuity_to_next,
            "location_name": scene.location.name if scene.location else "",
            "character_names": [c.canonical_name for c in scene.characters],
            "audio_alignment_notes": scene.audio_alignment_notes,
            # Computed above from the profile + scene_index. True when an
            # image will condition Wan22 for this scene (either scene-0
            # portrait or a chained last_frame).
            "character_image_provided": char_image_provided,
        },
        "characters": characters,
        "all_characters": characters,
        "previous_scene": {
            "visual_summary": prev_scene.visual_summary,
            "video_prompt": prev_prompt,
        } if prev_scene else None,
        "next_scene": {"visual_summary": next_scene.visual_summary} if next_scene else None,
        "critique_feedback": critique_feedback,
        "product": link.get("product"),
        "product_role": link.get("product_role"),
    }


_FALLBACK_NEGATIVE = (
    "text, subtitles, watermark, logo, title card, letters, words, "
    "fast motion, jitter, flickering, temporal inconsistency, blurry, distorted, "
    "mirror, reflection, double face, extra limbs, deformed"
)


def _apply_fallback_prompt(scene: Scene, project: Any, db: AsyncSession) -> None:
    """Never leave a scene without a prompt: a missing video_prompt makes the
    renderer skip the scene, which later fails stitching ('Missing scenes')."""
    if not scene.prompt:
        scene.prompt = ScenePrompt(scene_id=scene.id)
        db.add(scene.prompt)
    style = (project.style_lock or "").strip() or (
        "Semi-realistic Studio Ghibli style, painterly hand-drawn animation, "
        "soft warm cinematic lighting, lush detailed background"
    )
    summary = (scene.visual_summary or scene.scene_purpose
               or scene.source_excerpt or "a calm, gentle, tasteful scene").strip()
    scene.prompt.video_prompt = f"{style}. {summary}. Slow, deliberate, graceful motion; gentle camera drift."
    scene.prompt.negative_prompt = _FALLBACK_NEGATIVE
    scene.status = SceneStatus.prompted


def _apply_prompt_result(scene: Scene, result: Any, db: AsyncSession) -> None:
    if not scene.prompt:
        scene.prompt = ScenePrompt(scene_id=scene.id)
        db.add(scene.prompt)
    data = result.data
    scene.prompt.video_prompt = data.get("video_prompt")
    scene.prompt.negative_prompt = data.get("negative_prompt")
    scene.prompt.continuity_guardrails = data.get("continuity_guardrails")
    scene.prompt.style_notes = data.get("dim_style") or data.get("style_notes", "")
    scene.prompt.camera_plan = data.get("dim_camera") or data.get("camera_plan", "")
    scene.prompt.camera_angle = data.get("camera_angle", "")
    scene.prompt.subject_description = (
        data.get("dim_content") or data.get("subject_description", "")
    )
    scene.prompt.environment_description = (
        data.get("dim_input") or data.get("environment_description", "")
    )
    scene.prompt.action_description = (
        data.get("dim_content") or data.get("action_description", "")
    )
    scene.prompt.scene_breakdown = (
        data.get("scene_breakdown") or data.get("dim_structure", "")
    )
    # Nano-controlled continuity: it decides whether THIS scene should I2V-chain
    # from the previous scene's last frame. Default is True (no chain) unless
    # the nano explicitly opts in by setting continues_from_previous=true (tight
    # physical continuation: same location, same time of day, same pose).
    # Within-episode continuity is REQUIRED: every non-opening scene chains from
    # the previous scene's last frame so the episode reads as one continuous take.
    # We override the nano's per-scene opt-out on purpose. The last-frame resolver
    # only chains across scenes that SHARE a character, so cross-subject cuts won't
    # morph. Only engages when scenes render sequentially (not PARALLEL_SCENES).
    scene.skip_last_frame_chain = (scene.order_index == 0)
    scene.status = SceneStatus.prompted


async def _run_batched(
    agent: VisualDirectorAgent,
    scenes: list[Scene],
    characters: list[dict[str, Any]],
    project: Any,
    db: AsyncSession,
    critique_feedback: Optional[dict[str, Any]],
    product_links: dict[UUID, dict[str, Any]],
) -> None:
    """Prompt scenes in PARALLEL — up to `visual_prompt_concurrency` scenes at a
    time, each its own single-scene LLM call (settings.visual_prompt_max_retries
    re-prompt passes; over-cap prompts are truncated, not retried). LLM calls run
    concurrently; the DB writes that apply the results happen sequentially after."""
    import asyncio

    if critique_feedback:
        todo = list(enumerate(scenes))
    else:
        todo = [(i, s) for i, s in enumerate(scenes) if not (s.prompt and s.prompt.video_prompt)]

    if not todo:
        logger.info("All scenes already have prompts, skipping prompt generation")
        return

    conc = max(1, settings.visual_prompt_concurrency)
    logger.info(
        "Parallel prompt gen: %d scenes, %d at a time (max_retries=%d)",
        len(todo), conc, settings.visual_prompt_max_retries,
    )
    sem = asyncio.Semaphore(conc)

    async def _one(i: int, scene: Scene):
        prev = scenes[i - 1] if i > 0 else None
        prev_prompt = prev.prompt.video_prompt if (prev and prev.prompt) else None
        ctx = _build_context(scenes, i, project, characters,
                             prev_prompt, critique_feedback, product_links)
        async with sem:
            try:
                return scene, await agent.run(ctx)
            except Exception as exc:
                logger.warning("Scene %d prompt LLM call failed: %s", scene.order_index, exc)
                return scene, None

    results = await asyncio.gather(*[_one(i, s) for i, s in todo])
    for scene, result in results:
        if result and result.success:
            _apply_prompt_result(scene, result, db)
        else:
            logger.warning(
                "Scene %d returned no usable result — applying fallback prompt so "
                "the scene still renders", scene.order_index,
            )
            _apply_fallback_prompt(scene, project, db)
    await db.flush()


async def _assign_loras(scenes: list[Scene], db: AsyncSession) -> None:
    """After per-scene prompts exist, call the LoRA director to pick LoRA stacks
    + shot_type for each scene. Stores result on `ScenePrompt.lora_plan_json`.
    Failures here are non-fatal — the Wan22 provider falls back to keyword
    classification when the field is missing."""
    items: list[dict[str, Any]] = []
    for pos, scene in enumerate(scenes):
        if not (scene.prompt and scene.prompt.video_prompt):
            continue
        if scene.prompt.lora_plan_json:
            continue  # already assigned, idempotent
        items.append({
            "_pos": pos,
            "scene_index": scene.order_index,
            "video_prompt": scene.prompt.video_prompt,
            "scene_purpose": scene.scene_purpose or "",
        })
    if not items:
        return
    agent = LoRADirectorAgent(get_llm_provider())
    selections = await agent.run_batched(items)
    saved = 0
    for sel, item in zip(selections, items):
        if not sel:
            continue
        scene = scenes[item["_pos"]]
        if not scene.prompt:
            continue
        scene.prompt.lora_plan_json = json.dumps({
            "loras": sel.get("loras", []),
            "shot_type": sel.get("shot_type", "medium"),
            "rationale": sel.get("rationale", ""),
        })
        saved += 1
    await db.flush()
    logger.info("LoRA director: assigned plans to %d/%d scenes", saved, len(items))


async def run(project_id: str, critique_feedback: Optional[dict] = None,
              episode_id: str | None = None) -> None:
    async with async_session_factory() as db:
        project = await assert_project_active(db, project_id, "prompt_generation")
        episode = (await get_episode(db, episode_id)) if episode_id \
            else await resolve_active_episode(db, project_id)
        if episode is None:
            raise RuntimeError(f"No episode for project {project_id}")

        if not critique_feedback and await _all_scenes_have_prompts(db, episode.id):
            logger.info("All scenes already have prompts, skipping")
            episode.status = EpisodeStatus.audio_planning
            project.status = ProjectStatus.audio_planning
            await db.commit()
            return

        if critique_feedback:
            logger.info("Critique correction pass — bypassing idempotency, re-prompting all scenes")

        job = RenderJob(
            project_id=project.id, job_type=JobType.prompt_generation,
            status=JobStatus.running,
        )
        db.add(job)
        await db.flush()

        try:
            scenes = await _load_unlocked_scenes(db, episode.id)
            characters = await _load_characters(db, project.id)
            product_links = await _load_scene_product_links(db, episode.id)

            job.payload_json = json.dumps({
                "system_prompt_path": "app/prompts/visual_director.txt",
                "model": settings.llm_strong_model,
                "num_scenes": len(scenes),
                "scenes_with_product": len(product_links),
                "has_critique_feedback": bool(critique_feedback),
            })
            await db.flush()

            # Use the stronger model — visual_director output drives ~$2 of
            # GPU work per scene, so the better tokens are net-positive.
            agent = VisualDirectorAgent(get_strong_llm_provider())

            await _run_batched(agent, scenes, characters, project, db, critique_feedback,
                               product_links)

            if not any(s.prompt and s.prompt.video_prompt for s in scenes):
                raise RuntimeError("No prompts were generated — all scenes failed")

            try:
                await _assign_loras(scenes, db)
            except Exception:
                logger.exception("LoRA director failed — falling back to keyword classifier at render time")

            job.status = JobStatus.complete
            episode.status = EpisodeStatus.audio_planning
            project.status = ProjectStatus.audio_planning

        except Exception as e:
            logger.exception("Prompt generation failed")
            job.status = JobStatus.failed
            job.error_text = str(e)
            episode.status = EpisodeStatus.failed
            project.status = ProjectStatus.failed
            await db.commit()
            raise

        await db.commit()
