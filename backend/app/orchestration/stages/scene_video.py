"""Per-scene video generation + chord finalization."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from pathlib import Path
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.agents.asset_orchestrator import AssetOrchestrator
from app.config import settings
from app.database import async_session_factory
from app.models.asset import Asset, AssetStatus, AssetType
from app.models.episode import Episode, EpisodeStatus
from app.models.location import Location
from app.models.project import Project, ProjectStatus
from app.models.render_job import JobStatus, JobType, RenderJob
from app.models.scene import Scene
from app.models.scene_prompt import ScenePrompt
from app.orchestration._common import get_audio_provider, get_video_provider
from app.orchestration.episode_helpers import previous_episode, resolve_active_episode
from app.orchestration.profiles import get_profile

logger = logging.getLogger(__name__)


async def _existing_complete_video(db: AsyncSession, scene_id: uuid.UUID) -> Optional[Asset]:
    result = await db.execute(
        select(Asset)
        .where(Asset.scene_id == scene_id)
        .where(Asset.asset_type == AssetType.scene_video)
        .where(Asset.status == AssetStatus.complete)
    )
    asset = result.scalars().first()
    if asset and asset.file_path and Path(asset.file_path).exists():
        return asset
    return None


async def _resolve_character_image(scene: Scene) -> Optional[str]:
    if scene.characters:
        char = scene.characters[0]
        if char.reference_image_path and Path(char.reference_image_path).exists():
            # Prefer the opaque sidecar — Wan22 I2V wants an opaque image,
            # not the bg-removed transparent canonical.
            from app.agents.image_pregen.character_portraits import opaque_sidecar_path
            opaque = opaque_sidecar_path(char.reference_image_path)
            if opaque.exists():
                return str(opaque)
            return char.reference_image_path
    return None


async def _resolve_background_image(db: AsyncSession, scene: Scene) -> Optional[str]:
    if not scene.location_id:
        return None
    result = await db.execute(select(Location).where(Location.id == scene.location_id))
    loc = result.scalar_one_or_none()
    if loc and loc.reference_image_path and Path(loc.reference_image_path).exists():
        return loc.reference_image_path
    return None


async def _resolve_action_images(db: AsyncSession, scene_id: uuid.UUID) -> list[str]:
    seq_result = await db.execute(
        select(Asset)
        .where(Asset.scene_id == scene_id)
        .where(Asset.asset_type == AssetType.scene_action_seq)
        .where(Asset.status == AssetStatus.complete)
        .order_by(Asset.created_at.asc())
    )
    images = [
        a.file_path for a in seq_result.scalars().all()
        if a.file_path and Path(a.file_path).exists()
    ]
    if images:
        return images

    for legacy_type in (AssetType.scene_action, AssetType.scene_action_2):
        legacy_result = await db.execute(
            select(Asset)
            .where(Asset.scene_id == scene_id)
            .where(Asset.asset_type == legacy_type)
            .where(Asset.status == AssetStatus.complete)
            .order_by(Asset.created_at.desc())
            .limit(1)
        )
        legacy = legacy_result.scalar_one_or_none()
        if legacy and legacy.file_path and Path(legacy.file_path).exists():
            images.append(legacy.file_path)
    return images


def _pick_seed_scene_index(
    current_char_ids: set,
    prior_scenes: list[tuple[int, set]],
) -> Optional[int]:
    """Pick which prior scene's last_frame should seed the current scene.

    `prior_scenes` is a list of (order_index, character_id_set) for every
    scene with order_index < current, ordered most-recent first.

    Rules:
      1. If no prior scenes exist → None (cold T2V).
      2. If the current scene has no characters → use the most recent prior
         (environmental continuity; can't pollute a face that isn't there).
      3. If the current scene has characters → walk back, return the first
         prior scene that shares ≥1 character. If none share, return None
         instead of polluting the I2V seed with a different character's face.

    Pure function so tests can verify without DB.
    """
    if not prior_scenes:
        return None
    if not current_char_ids:
        return prior_scenes[0][0]
    for order_idx, char_ids in prior_scenes:
        if char_ids & current_char_ids:
            return order_idx
    return None


def _episode_last_frame_dir(project_id: str, episode_id: str) -> Path:
    return settings.storage_root / "temp" / project_id / "episodes" / episode_id


async def _resolve_last_frame_from_prev_episode(
    db: AsyncSession, project_id: str, episode: Episode,
) -> Optional[str]:
    """When this is scene 0 of episode N≥1, chain off the previous episode's
    last completed scene's last_frame.png."""
    if not episode.continue_from_previous:
        return None
    prev = await previous_episode(db, episode)
    if prev is None:
        return None
    last_scene = (await db.execute(
        select(Scene)
        .where(Scene.episode_id == prev.id)
        .order_by(Scene.order_index.desc())
        .limit(1)
    )).scalar_one_or_none()
    if last_scene is None:
        return None
    candidate = (
        _episode_last_frame_dir(project_id, str(prev.id))
        / f"scene_{last_scene.order_index:03d}_last_frame.png"
    )
    legacy = (
        settings.storage_root / "temp" / project_id
        / f"scene_{last_scene.order_index:03d}_last_frame.png"
    )
    if candidate.exists():
        return str(candidate)
    if legacy.exists():
        return str(legacy)
    return None


def _last_frame_path(project_id: str, episode_id: str, order_index: int) -> Optional[str]:
    """Resolve an on-disk last_frame.png for a scene order_index (new + legacy layout)."""
    candidate = _episode_last_frame_dir(project_id, episode_id) / f"scene_{order_index:03d}_last_frame.png"
    legacy = settings.storage_root / "temp" / project_id / f"scene_{order_index:03d}_last_frame.png"
    if candidate.exists():
        return str(candidate)
    if legacy.exists():
        return str(legacy)
    return None


async def _explicit_prev_last_frame(
    db: AsyncSession, project_id: str, scene: Scene, episode: Episode,
) -> Optional[str]:
    """When the user pinned a continuity predecessor in the UI, seed from that
    scene's last frame (same episode only). Returns None if it isn't rendered yet."""
    prev = await db.get(Scene, scene.continuity_prev_scene_id)
    if prev is None or prev.episode_id != episode.id:
        return None
    return _last_frame_path(project_id, str(episode.id), prev.order_index)


async def _resolve_last_frame(
    db: AsyncSession, project_id: str, scene: Scene, episode: Episode,
) -> Optional[str]:
    """Smart I2V-seed picker. An explicit continuity_prev_scene_id (UI-pinned)
    wins over everything. Otherwise returns the most-recent prior scene's
    last_frame.png whose character set overlaps with the current scene's. For
    scene 0 of episode N≥1, chains off the previous episode's last frame when
    continue_from_previous=true."""
    if getattr(scene, "continuity_prev_scene_id", None):
        return await _explicit_prev_last_frame(db, project_id, scene, episode)
    if getattr(scene, "skip_last_frame_chain", False):
        logger.info("Scene %d: skip_last_frame_chain=True, rendering without I2V seed", scene.order_index)
        return None
    if scene.order_index == 0:
        return await _resolve_last_frame_from_prev_episode(db, project_id, episode)

    current_chars = {c.id for c in (scene.characters or [])}
    if getattr(episode, "anchor_first_frame", False) and current_chars:
        scene_0 = (await db.execute(
            select(Scene).where(Scene.episode_id == episode.id).where(Scene.order_index == 0)
            .options(selectinload(Scene.characters))
        )).scalar_one_or_none()
        if scene_0:
            s0_chars = {c.id for c in (scene_0.characters or [])}
            same_chars = bool(current_chars & s0_chars)
            same_bg = scene.location_id is not None and scene.location_id == scene_0.location_id
            if same_chars and same_bg:
                anchor = _episode_last_frame_dir(project_id, str(episode.id)) / "scene_000_first_frame.png"
                if anchor.exists():
                    logger.info("Scene %d: anchor mode — same characters + location as scene 0", scene.order_index)
                    return str(anchor)
    result = await db.execute(
        select(Scene)
        .where(Scene.episode_id == episode.id)
        .where(Scene.order_index < scene.order_index)
        .order_by(Scene.order_index.desc())
        .options(selectinload(Scene.characters))
    )
    priors = result.scalars().all()
    prior_tuples = [
        (p.order_index, {c.id for c in (p.characters or [])}) for p in priors
    ]
    chosen_idx = _pick_seed_scene_index(current_chars, prior_tuples)
    if chosen_idx is None:
        return None
    ep_dir = _episode_last_frame_dir(project_id, str(episode.id))
    candidate = ep_dir / f"scene_{chosen_idx:03d}_last_frame.png"
    legacy = (
        settings.storage_root / "temp" / project_id
        / f"scene_{chosen_idx:03d}_last_frame.png"
    )
    chosen = candidate if candidate.exists() else (legacy if legacy.exists() else None)
    if chosen is None:
        return None
    if chosen_idx != scene.order_index - 1:
        logger.info(
            "Scene %d: smart I2V seed -> scene_%03d (skipped %d intermediate scene(s) "
            "without character overlap)",
            scene.order_index, chosen_idx, scene.order_index - 1 - chosen_idx,
        )
    return str(chosen)


def _adjust_last_frame(
    profile,
    scene_order_index: int,
    last_frame: Optional[str],
    character: Optional[str],
    action_images: list[str],
) -> Optional[str]:
    """Decide whether to keep, drop, or null the cross-scene last_frame chain.

    Two reasons to drop:
      - tail-drop: LTX-style cumulative drift mitigation (scene >=3).
      - environmental-scene drop: profile *expects* char/stills but neither
        showed up — treat as bg-only environmental shot. Text-only profiles
        (e.g. wan22_text_only) where char/stills are disabled by design
        bypass this branch, because absence is the norm, not a signal.

    The chain is now kept all the way through the episode regardless of
    length — LoRA selection per scene + per-scene wan22 prompts keep
    drift in check.
    """
    if not last_frame:
        return None
    if profile.drop_last_frame_on_tail and scene_order_index >= 3:
        return None
    expects_char_or_stills = (
        profile.canonical_portrait_enabled or profile.image_pregen_enabled
    )
    if expects_char_or_stills and not character and not action_images:
        return None
    return last_frame


def _select_conditioning(
    last_frame: Optional[str],
    background: Optional[str],
    action_images: list[str],
    character: Optional[str],
    scene: Scene,
    use_action_still_as_condition: bool = False,
) -> tuple[Optional[str], Optional[str], Optional[str], list[str]]:
    """Returns (condition, character, background, action_images).

    Priority rules:
    1. If `use_action_still_as_condition` (Wan22 image-seeded profile) AND
       an action still exists, that still IS the I2V condition image — overrides
       last_frame. This is the lever that lets SD3.5/InstantID-rendered per-scene
       canvases drive Wan22 output instead of pure T2V drift.
    2. If this scene has its own action stills (LTX path), USE THEM — don't let
       last_frame silently override (that caused scenes 2-4 in the Save Soil
       run to all render the same Maya-walking shot).
    3. If no stills but we have background + character, condition on bg + char.
    4. last_frame is a fallback ONLY when nothing else is available — and it's
       still passed to LTX as `--condition-image` separately even when not
       returned here, so cross-scene continuity isn't fully lost.
    5. Final fallback: scene_ref image, then nothing.
    """
    # Scene 0: condition Wan22 I2V on the character portrait (uploaded /
    # canonical). Scenes N>0: condition on the previous scene's last_frame
    # so each scene literally picks up where the prior one ended. No
    # per-scene action stills.
    if scene.order_index == 0 and character:
        return character, character, background, action_images
    if last_frame:
        return last_frame, character, background, action_images
    if action_images or character:
        return last_frame, character, background, action_images
    if background:
        return background, character, background, action_images
    scene_ref = scene.scene_ref_image_path if (
        scene.scene_ref_image_path and Path(scene.scene_ref_image_path).exists()
    ) else None
    return scene_ref, character, background, action_images


async def _delete_existing_asset(db: AsyncSession, asset: Asset) -> None:
    logger.info("Scene %s force-regenerating, deleting old asset %s", asset.scene_id, asset.id)
    # Soft-delete: move the prior render aside so the new render doesn't overwrite
    # it (never destroy a user artifact). The .bak file is reversible.
    if asset.file_path:
        fp = (settings.storage_root.parent / asset.file_path).resolve()
        try:
            if fp.is_file():
                fp.rename(fp.with_name(f"{fp.name}.bak-{asset.id}"))
        except OSError as exc:
            logger.warning("force-regen: move-aside failed %s: %s", fp, exc)
    await db.delete(asset)
    await db.flush()


async def _assert_prev_scene_chain(
    db: AsyncSession, scene: Scene, episode: Episode, orchestrator, project_id: str,
) -> None:
    """Scene N>0 requires scene N-1's completed video + last_frame.png on disk.
    Re-extracts the PNG if the video exists but the frame file is missing.
    Raises RuntimeError when the previous video itself is missing so the caller
    can pause/requeue rather than render a chain-broken scene."""
    import os
    # Parallel mode: render every scene independently (no wait on the previous
    # scene's video) so all cards can render scenes of one episode at once.
    # Scenes lose their I2V last-frame seed but the chord fans out across GPUs.
    if os.environ.get("PARALLEL_SCENES") == "1":
        return
    explicit_id = getattr(scene, "continuity_prev_scene_id", None)
    if explicit_id is not None:
        prev = await db.get(Scene, explicit_id)
        if prev is None or prev.episode_id != episode.id:
            return
    else:
        if scene.order_index == 0:
            return
        if getattr(episode, "anchor_first_frame", False):
            return
        if getattr(scene, "skip_last_frame_chain", False):
            return
        prev = (await db.execute(
            select(Scene)
            .where(Scene.episode_id == episode.id)
            .where(Scene.order_index == scene.order_index - 1)
            .limit(1)
        )).scalar_one_or_none()
        if prev is None:
            return
    prev_asset = await _existing_complete_video(db, prev.id)
    if prev_asset is None:
        raise RuntimeError(
            f"Chain broken: scene {scene.order_index} cannot render — previous "
            f"scene {prev.order_index} ({prev.id}) has no completed video on disk. "
            f"Requeue that scene first."
        )
    ep_dir = _episode_last_frame_dir(project_id, str(episode.id))
    expected = ep_dir / f"scene_{prev.order_index:03d}_last_frame.png"
    legacy = (
        settings.storage_root / "temp" / project_id
        / f"scene_{prev.order_index:03d}_last_frame.png"
    )
    if expected.exists() or legacy.exists():
        return
    ep_dir.mkdir(parents=True, exist_ok=True)
    await orchestrator._extract_last_frame(prev_asset.file_path, str(expected))
    await _clean_seed_frame(str(expected))
    logger.info(
        "Recovered missing last_frame for scene %d -> %s",
        prev.order_index, expected,
    )


_CLEAN_SEED_SCRIPT = (
    Path(__file__).resolve().parents[4] / "scripts" / "clean_seed_frame.py"
)


async def _clean_seed_frame(frame_path: str) -> None:
    """Degrain + CodeFormer face-relock the last-frame I2V seed in place so grain
    and identity drift don't compound down the chain. Non-fatal: on any failure
    the raw extracted frame is left untouched."""
    if not settings.wan22_clean_seed_frame:
        return
    if not (_CLEAN_SEED_SCRIPT.exists() and Path(frame_path).exists()):
        return
    tmp = f"{frame_path}.clean.png"
    try:
        proc = await asyncio.create_subprocess_exec(
            settings.gpu_python_path, str(_CLEAN_SEED_SCRIPT),
            frame_path, tmp, str(settings.wan22_clean_seed_fidelity),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=240)
        if proc.returncode == 0 and Path(tmp).exists():
            os.replace(tmp, frame_path)
            logger.info("Cleaned seed frame (degrain + face-relock) → %s", frame_path)
        else:
            logger.warning("Seed-clean failed (rc=%s): %s — keeping raw seed",
                           proc.returncode, (stderr.decode()[-300:] if stderr else "?"))
            Path(tmp).unlink(missing_ok=True)
    except Exception as exc:
        logger.warning("Seed-clean error: %s — keeping raw seed", exc)
        Path(tmp).unlink(missing_ok=True)


async def _extract_last_frame_for_next(
    orchestrator: AssetOrchestrator, asset: Asset, scene: Scene, project_id: str,
    episode_id: str,
) -> None:
    if not (asset and asset.status == AssetStatus.complete and asset.file_path):
        return
    frame_dir = _episode_last_frame_dir(project_id, episode_id)
    frame_dir.mkdir(parents=True, exist_ok=True)
    frame_path = str(frame_dir / f"scene_{scene.order_index:03d}_last_frame.png")
    await orchestrator._extract_last_frame(asset.file_path, frame_path)
    await _clean_seed_frame(frame_path)
    logger.info("Extracted last frame for scene %d → %s", scene.order_index, frame_path)
    if scene.order_index == 0:
        first_path = str(frame_dir / "scene_000_first_frame.png")
        await orchestrator._extract_first_frame(asset.file_path, first_path)
        logger.info("Extracted first frame (identity anchor) → %s", first_path)


async def _record_payload(db: AsyncSession, project_id: str, scene: Scene) -> None:
    """Annotate the active video_generation RenderJob with this scene's params.

    Uses a SEPARATE committed transaction: the RenderJob is a single shared
    per-project row, so updating it on `db` (held open for the whole ~10-min
    render) serializes every scene of the project — the second GPU blocks on the
    first's row lock. Committing immediately releases it so both GPUs run free.
    """
    scene_id = str(scene.id)
    async with async_session_factory() as s:
        job = (await s.execute(
            select(RenderJob)
            .where(RenderJob.project_id == uuid.UUID(project_id))
            .where(RenderJob.job_type == JobType.video_generation)
            .where(RenderJob.status == JobStatus.running)
            .order_by(RenderJob.created_at.desc())
            .limit(1)
        )).scalar_one_or_none()
        if not job:
            return
        job.payload_json = json.dumps({
            "provider": settings.video_provider,
            "num_frames": settings.ltx_num_frames,
            "fps": settings.ltx_fps,
            "height": settings.ltx_height,
            "width": settings.ltx_width,
            "scene_id": scene_id,
        })
        await s.commit()


async def generate_single(project_id: str, scene_id: str, force: bool = False) -> dict:
    async with async_session_factory() as db:
        scene = await db.get(
            Scene, uuid.UUID(scene_id),
            options=[selectinload(Scene.prompt), selectinload(Scene.characters)],
        )
        if not scene:
            raise ValueError(f"Scene {scene_id} not found")

        existing = await _existing_complete_video(db, uuid.UUID(scene_id))
        if existing and not force:
            logger.info("Scene %s already has video at %s — skipping", scene_id, existing.file_path)
            return {"scene_id": scene_id, "status": "skipped", "file": existing.file_path}
        if existing and force:
            await _delete_existing_asset(db, existing)

        if not scene.prompt or not scene.prompt.video_prompt:
            raise ValueError(f"Scene {scene_id} has no video prompt")

        project = await db.get(Project, uuid.UUID(project_id))
        profile = get_profile(project.pipeline_profile if project else None)
        episode = await db.get(Episode, scene.episode_id) if scene.episode_id else None
        if episode is None:
            episode = await resolve_active_episode(db, project_id)
        if episode is None:
            raise ValueError(f"No episode for scene {scene_id}")

        # Bump project/episode status in a SEPARATE short transaction that commits
        # immediately. If we did this on `db`, the row locks would be held for the
        # whole render (~10 min), serializing concurrent scenes of the same project
        # across GPUs. Committing now releases the locks so both GPUs run in parallel.
        async with async_session_factory() as s2:
            p2 = await s2.get(Project, uuid.UUID(project_id))
            e2 = await s2.get(Episode, episode.id)
            if p2:
                p2.status = ProjectStatus.generating
            if e2:
                e2.status = EpisodeStatus.generating
            await s2.commit()

        character = await _resolve_character_image(scene)
        if not character and scene.order_index > 0:
            ep_dir = _episode_last_frame_dir(project_id, str(episode.id))
            anchor = ep_dir / "scene_000_first_frame.png"
            if not anchor.exists():
                anchor = ep_dir / "scene_000_last_frame.png"
            if anchor.exists():
                character = str(anchor)
                logger.info("Scene %d: no portrait — using %s as identity anchor", scene.order_index, anchor.name)
        background = await _resolve_background_image(db, scene)
        action_images = await _resolve_action_images(db, uuid.UUID(scene_id))
        last_frame = await _resolve_last_frame(db, project_id, scene, episode) \
            if profile.pin_last_frame_chain else None

        adjusted = _adjust_last_frame(
            profile, scene.order_index, last_frame, character, action_images,
        )
        if last_frame and not adjusted:
            logger.info("Scene %d: dropping last_frame (tail/environmental rule)",
                        scene.order_index)
        last_frame = adjusted

        if not profile.pin_action_stills:
            action_images = []

        # Wan22 image-seeded profile: use the per-scene SD3.5+InstantID action
        # still as the I2V condition image instead of last_frame chaining.
        use_action_still_as_condition = (
            profile.video_provider == "wan22" and profile.pin_action_stills
        )
        condition, character, background, action_images = _select_conditioning(
            last_frame, background, action_images, character, scene,
            use_action_still_as_condition=use_action_still_as_condition,
        )

        logger.info(
            "Scene %s: condition=%s char=%s bg=%s action_stills=%d",
            scene_id, condition or "none", character or "none",
            background or "none", len(action_images),
        )

        await _record_payload(db, project_id, scene)

        orchestrator = AssetOrchestrator(
            get_video_provider(profile.name),
            get_audio_provider(),
            provider_settings=profile.provider_settings,
        )
        await _assert_prev_scene_chain(db, scene, episode, orchestrator, project_id)
        asset = await orchestrator.generate_scene_video(
            scene=scene,
            project_id=uuid.UUID(project_id),
            db=db,
            condition_image_path=condition,
            character_image_path=character,
            background_image_path=background,
            scene_action_images=action_images,
        )
        if asset is not None:
            asset.episode_id = episode.id
        await db.commit()

        await _extract_last_frame_for_next(
            orchestrator, asset, scene, project_id, str(episode.id),
        )

    return {"scene_id": scene_id, "status": asset.status.value, "file": asset.file_path}


async def get_scene_ids_with_prompts(project_id: str) -> list[str]:
    """Scene IDs that have prompts, scoped to the active episode. Locked
    scenes are excluded — the lock flag is the user-controlled "don't touch
    this" gate that survives chord re-dispatch."""
    async with async_session_factory() as db:
        episode = await resolve_active_episode(db, project_id)
        if episode is None:
            return []
        result = await db.execute(
            select(Scene.id)
            .join(ScenePrompt, ScenePrompt.scene_id == Scene.id)
            .where(Scene.episode_id == episode.id)
            .where(Scene.locked == False)
            .where(ScenePrompt.video_prompt.isnot(None))
            .order_by(Scene.order_index)
        )
        return [str(row) for row in result.scalars().all()]


async def finalize_videos(project_id: str, results: list[dict]) -> None:
    # Chain dispatch doesn't aggregate per-task results, so trust the DB:
    # count scenes that actually have a completed video on disk.
    async with async_session_factory() as db:
        episode = await resolve_active_episode(db, project_id)
        n_complete = 0
        if episode:
            rows = (await db.execute(
                select(Scene.id).where(Scene.episode_id == episode.id)
            )).scalars().all()
            for sid in rows:
                if await _existing_complete_video(db, sid):
                    n_complete += 1

    logger.info(
        "[Pipeline] finalize_videos: %d scenes with completed video (project=%s)",
        n_complete, project_id,
    )

    if n_complete == 0:
        raise RuntimeError(
            f"No completed scene videos on disk for project {project_id}"
        )

    async with async_session_factory() as db:
        project = await db.get(Project, uuid.UUID(project_id))
        if project:
            project.status = ProjectStatus.generating
            await db.commit()
