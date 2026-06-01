"""Per-scene OpenPose reference image — library lookup first, SD3.5 t2i fallback.

Two-tier lookup:
  1. `pose_library.match(scene.action_description)` returns a curated
     pre-rendered photo from `storage/pose_library/` if the action's
     keywords match a library entry. Skips SD3.5 entirely.
  2. On miss, generate a per-scene SD3.5 t2i pose ref the old way.

Either result is consumed by the dual-CN InstantID generator (face from
portrait embedding, body pose from this image's OpenPose skeleton)."""

from __future__ import annotations

import logging
import shutil
import uuid
from pathlib import Path

from app.agents.image_pregen import pose_library
from app.config import settings as cfg
from app.models.scene import Scene
from app.providers.image.base import ImageSettings

logger = logging.getLogger(__name__)


_POSE_REF_NEG = (
    "cropped feet, cropped legs, head-and-shoulders, bust shot, close-up, "
    "macro, partial body, blurry, low quality, watermark, text, logo, "
    "extra limbs, deformed, mutated, multiple people, crowd"
)


def _scene_action_text(scene: Scene) -> str:
    p = getattr(scene, "prompt", None)
    return (
        (p.action_description if p and p.action_description else None)
        or (scene.visual_summary or "")
        or "standing in a neutral pose"
    )


def _pose_prompt_for_scene(scene: Scene) -> str:
    """Deterministic template — wraps the scene's action verb in a
    generic-person, full-body, neutral-backdrop pose-reference prompt.

    We deliberately do NOT mention the character's specific clothing or
    identity; those flow in via the dual-CN's prompt and embedding paths.
    """
    action = _scene_action_text(scene).strip().rstrip(".")
    return (
        f"Full-body side profile, head to toe in frame, both feet visible. "
        f"A generic athletic person {action}, captured in a single frozen "
        f"instant. Athletic build, neutral generic athletic wear "
        f"(plain tee, plain shorts, plain trainers — colors generic). "
        f"Plain neutral grey studio backdrop, soft even lighting, sharp "
        f"focus, photorealistic."
    )


async def generate_for_scene(
    image_provider,
    project_uuid: uuid.UUID,
    scene: Scene,
    llm=None,
    beat_idx: int | None = None,
    beat_text: str | None = None,
) -> Path | None:
    """Resolve the pose reference for `scene` (or for one of its beats).

    Three-tier lookup, applied per call:

      1. LLM-driven label match against the pose library (when `llm` is
         provided). When `beat_text` is set, the LLM sees the per-second
         beat description and can pick a different pose for each beat —
         this gives LTX kinetic targets to interpolate between rather
         than 6 clones of one frozen pose.
      2. Deterministic keyword match (`pose_library.match`) — fallback
         when no llm is wired or the LLM call fails.
      3. SD 3.5 t2i generation — final fallback when nothing in the
         library scores.

    `beat_idx`/`beat_text`: when both are provided, write the result as
    `scene_NNN_bMM.png` so each beat gets its own distinct pose-ref.
    When omitted (legacy callers), reverts to a single per-scene pose.
    Library hits are COPIED into the per-project pose_refs directory so
    the storage layout stays scene-indexed."""
    out_dir = cfg.storage_root / "pose_refs" / str(project_uuid)
    out_dir.mkdir(parents=True, exist_ok=True)
    suffix = f"_b{beat_idx:02d}" if beat_idx is not None else ""
    out_path = out_dir / f"scene_{scene.order_index:03d}{suffix}.png"
    if out_path.exists():
        return out_path

    action = (beat_text or "").strip() or _scene_action_text(scene)
    label_for_log = (
        f"scene {scene.order_index} beat {beat_idx}"
        if beat_idx is not None else f"scene {scene.order_index}"
    )
    hit = None
    if llm is not None:
        hit = await pose_library.match_with_llm(action, llm)
        if hit is not None:
            logger.info("Pose-library LLM-HIT for %s: %s", label_for_log, hit.label)
    if hit is None:
        hit = pose_library.match(action)
    if hit is not None:
        try:
            shutil.copy2(hit.photo_path, out_path)
            logger.info(
                "Pose-library HIT for %s: %s → %s",
                label_for_log, hit.label, out_path.name,
            )
            return out_path
        except OSError as e:
            logger.warning("Pose-library copy failed for %s: %s", label_for_log, e)
            return None

    prompt = _pose_prompt_for_scene(scene)
    logger.info(
        "Pose-library MISS for %s, falling back to SD3.5 t2i → %s",
        label_for_log, out_path.name,
    )
    res = await image_provider.generate_image(
        prompt=prompt,
        negative_prompt=_POSE_REF_NEG,
        output_path=out_path,
        settings=ImageSettings(
            width=cfg.sd35_char_width,
            height=cfg.sd35_char_height,
            num_inference_steps=cfg.sd35_steps,
            guidance_scale=cfg.sd35_guidance,
            seed=500 + scene.order_index * 100 + (beat_idx or 0),
        ),
    )
    if not res.success:
        logger.warning("Pose reference failed for %s: %s", label_for_log, res.error)
        return None
    return Path(res.file_path)
