"""Wan 2.2 TI2V-5B provider with smart LoRA selection.

Classifies each scene prompt against the catalog at app/config/wan22_lora_catalog.yaml,
picks (lora_id, weight, shot_type), then invokes wan22_generate.py as a subprocess.
Post-process (CodeFormer+ESRGAN face restore) runs only on wide shots.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

import yaml

from app.config import settings
from app.providers.video.base import VideoProvider, VideoResult, VideoSettings

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).parent.parent.parent.parent.parent
_CATALOG_PATH = Path(__file__).parent.parent.parent / "config" / "wan22_lora_catalog.yaml"
_SCRIPT_PATH = _REPO_ROOT / "wan22_generate.py"
_FACE_RESTORE_SCRIPT = _REPO_ROOT / "scripts" / "wan22_face_restore_codeformer.py"

# Motion-heavy scene types — character locomotion or large body motion. These
# get more inference steps + higher CFG to combat the mid-clip identity drift
# observed in MOTION_FACE_PRESERVATION_OPTIONS.md (e.g. ad_02 scene 2 where
# the runner's face morphed within 5s). Source: empirical analysis of rendered
# motion clips.
MOTION_SCENE_TYPES = frozenset({
    "action_running",
    "walking_locomotion",
    "dancing_high_motion",
    "dramatic_cinematic_war",
})

# Per-clip step + CFG overrides for motion. As of 2026-05-27 the user
# requested a flat 140 inference steps for ALL scenes, so the motion step
# bump is 0 (base 140 == motion 140). CFG bump kept for tighter identity
# anchoring on motion clips.
_MOTION_STEP_BUMP = 0    # was 40 (base 100 → motion 140). Now base=140 directly.
_MOTION_CFG_DELTA = 1.0  # 5.0 -> 6.0, tighter prompt adherence keeps identity

# Default face/hand distortion guardrails. Appended to whatever the caller
# passes so existing per-scene negatives still take precedence.
_FACE_NEGATIVE_BASELINE = (
    "warped face, distorted features, melting face, asymmetric eyes, "
    "drifting identity, face morphing, plastic skin, smeared features, "
    "blurry face, double face, extra fingers, fused fingers, deformed hands, "
    "malformed wrist"
)


def _is_motion_scene(scene_type: str) -> bool:
    return scene_type in MOTION_SCENE_TYPES


def _tune_for_motion(
    scene_type: str, steps: int, guidance_scale: float, negative_prompt: str,
) -> tuple[int, float, str]:
    """Return (steps, guidance_scale, negative_prompt) with motion-aware
    overrides applied. Pure function so callers + tests can verify the math
    without invoking the subprocess."""
    neg = negative_prompt.strip()
    merged_neg = f"{neg}, {_FACE_NEGATIVE_BASELINE}" if neg else _FACE_NEGATIVE_BASELINE
    if not _is_motion_scene(scene_type):
        return steps, guidance_scale, merged_neg
    return steps + _MOTION_STEP_BUMP, guidance_scale + _MOTION_CFG_DELTA, merged_neg


@lru_cache(maxsize=1)
def _load_catalog() -> dict:
    return yaml.safe_load(_CATALOG_PATH.read_text())


_SUFFIXES = ("", "s", "es", "ed", "ing")


def _match_any(tags: list[str], prompt_lower: str, words: list[str]) -> bool:
    """Match a tag if any word in the prompt equals tag or tag+{s,es,ed,ing}.
    Avoids the over-greedy 'warm' matching 'war' that pure prefix-match produces."""
    for tag in tags:
        if " " in tag:
            if tag in prompt_lower:
                return True
            continue
        for w in words:
            for suf in _SUFFIXES:
                if w == tag + suf:
                    return True
    return False


def classify(prompt: str) -> tuple[str, str, list[tuple[str, float]]]:
    """Return (scene_type, shot_type, lora_stack).

    lora_stack is a list of (lora_id, weight) tuples, in load order:
      - [(primary, w)]                    when runner_up is "none" or absent
      - [(primary, w), (runner_up, w')]   when the catalog defines a meaningful
                                          companion (different id, weight > 0)

    Stacking uses the catalog's pre-validated sweet-spot weights — the catalog
    is the single source of truth for which pairings are safe.
    """
    cat = _load_catalog()
    pl = prompt.lower()
    words = re.findall(r"[a-z]+", pl)
    scene_type = "closeup_portrait"
    for st, tags in cat["tag_index"].items():
        if _match_any(tags, pl, words):
            scene_type = st
            break
    sm = cat["scene_map"][scene_type]
    shot_type = sm.get("default_shot", "medium")
    for st, tags in cat.get("shot_index", {}).items():
        if _match_any(tags, pl, words):
            shot_type = st
            break

    stack: list[tuple[str, float]] = []
    primary = sm["primary"]
    p_id, p_w = primary["lora"], float(primary["weight"])
    if p_id != "none" and p_w > 0:
        stack.append((p_id, p_w))
    runner = sm.get("runner_up")
    if runner:
        r_id, r_w = runner["lora"], float(runner["weight"])
        # Skip "none", duplicates, and zero-weight entries.
        if r_id != "none" and r_w > 0 and r_id != p_id:
            stack.append((r_id, r_w))
    if not stack:
        # Fall back to catalog default so we never render with zero adapters
        # when the chosen scene_type maps to "none@0".
        fb = cat.get("defaults", {}).get("fallback", {})
        fb_lora = fb.get("lora")
        fb_weight = float(fb.get("weight", 0.5))
        if fb_lora and fb_lora != "none" and fb_weight > 0:
            stack.append((fb_lora, fb_weight))
    return scene_type, shot_type, stack


def _resolve_plan(
    prompt: str, lora_plan_json: Optional[str],
) -> tuple[str, str, list[tuple[str, float]], str]:
    """Resolve (scene_type, shot_type, lora_stack, source).

    If `lora_plan_json` is present and parseable, use the LLM's pick. Otherwise
    fall back to the deterministic keyword classifier. The scene_type is only
    used for the motion-bump decision, so when the LLM picks we infer it from
    the prompt's keywords (cheaper than a second LLM call).
    """
    if lora_plan_json:
        try:
            plan = json.loads(lora_plan_json)
            shot = plan.get("shot_type") or "medium"
            stack: list[tuple[str, float]] = []
            cat = _load_catalog()
            for entry in plan.get("loras") or []:
                lid = entry.get("id")
                w = float(entry.get("weight", 0.0))
                if lid and lid != "none" and w > 0 and lid in cat["loras"]:
                    stack.append((lid, w))
            # Scene type still needed for motion bump — use the keyword
            # classifier just for that signal (we override shot+stack).
            scene_type, _shot_kw, _stack_kw = classify(prompt)
            if not stack:
                # LLM emitted an empty stack — accept it (zero-LoRA baseline)
                pass
            return scene_type, shot, stack, "llm"
        except (ValueError, TypeError, KeyError) as e:
            logger.warning("Bad lora_plan_json (%s); falling back to keyword classify", e)
    st, sh, stack = classify(prompt)
    return st, sh, stack, "keyword"


def _cuda_device_index() -> int:
    """Wan22 GPU selection. Respects WAN22_GPU_INDEX env var override for
    multi-GPU parallel rendering; defaults to the largest GPU."""
    override = os.environ.get("WAN22_GPU_INDEX")
    if override is not None:
        return int(override)
    from app.utils.gpu import largest_gpu_index
    return largest_gpu_index()


async def _post_process_face_restore(in_mp4: Path, env: dict) -> None:
    """Run CodeFormer+ESRGAN restoration on the rendered mp4, overwriting in place.
    Restoration failure is non-fatal — we keep the unrestored video."""
    if not _FACE_RESTORE_SCRIPT.exists():
        logger.warning("Face restore script missing at %s — skipping", _FACE_RESTORE_SCRIPT)
        return
    tmp = in_mp4.with_suffix(".restored.mp4")
    cmd = [settings.gpu_python_path, str(_FACE_RESTORE_SCRIPT),
           str(in_mp4), str(tmp), "0.5"]
    logger.info("Wan22 face-restore: %s", in_mp4.name)
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, env=env,
        )
        _, stderr = await proc.communicate()
        if proc.returncode == 0 and tmp.exists():
            tmp.replace(in_mp4)
            logger.info("✓ Face restoration applied")
        else:
            err = (stderr.decode()[-400:] if stderr else "?").strip()
            logger.warning("Face restoration failed (rc=%s): %s — keeping raw video",
                           proc.returncode, err)
            if tmp.exists():
                tmp.unlink()
    except Exception as e:
        logger.warning("Face restoration error: %s — keeping raw video", e)


class Wan22VideoProvider(VideoProvider):
    """Generates video using Wan 2.2 TI2V-5B with smart LoRA picking."""

    def __init__(self):
        self._active_jobs: dict[str, asyncio.subprocess.Process] = {}

    async def generate_video(
        self,
        prompt: str,
        negative_prompt: str,
        output_path: Path,
        video_settings: Optional[VideoSettings] = None,
        condition_image_path: Optional[str] = None,
        character_image_path: Optional[str] = None,    # used as last_image anchor
        background_image_path: Optional[str] = None,   # unused — no frame pins
        scene_action_images: Optional[list[str]] = None,  # unused
        lora_plan_json: Optional[str] = None,
    ) -> VideoResult:
        vs = VideoSettings(
            height=int(os.environ.get("WAN22_HEIGHT", settings.wan22_height)),
            width=int(os.environ.get("WAN22_WIDTH", settings.wan22_width)),
            num_frames=settings.wan22_num_frames,
            num_inference_steps=settings.wan22_inference_steps,
            guidance_scale=settings.wan22_guidance_scale,
            fps=settings.wan22_fps,
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)

        scene_type, shot_type, lora_stack, plan_source = _resolve_plan(prompt, lora_plan_json)
        cat = _load_catalog()
        # Resolve filenames once. Drop entries that have no `file` (e.g. "none"),
        # zero weight, or whose .safetensors isn't on disk yet — newly-added
        # catalog entries may have pending downloads.
        resolved: list[tuple[str, str, float]] = []
        lora_dir = Path(settings.wan22_lora_dir)
        for lid, lw in lora_stack:
            lfile = cat["loras"].get(lid, {}).get("file")
            if not lfile or lw <= 0:
                continue
            if not (lora_dir / lfile).exists():
                logger.warning("LoRA %s file missing on disk (%s) — skipping", lid, lfile)
                continue
            resolved.append((lid, lfile, lw))
        # User-pref 2026-05-27: face-restore on every scene (was: only wide
        # shots). Tradeoff is closeup faces may look slightly over-processed,
        # but consistency across the cut is more important.
        do_post_process = True

        # Read steps + CFG from settings (not vs.*) so config bumps take effect
        # immediately on already-prompted projects without re-running the
        # prompting stage. VideoSpec values are snapshots from prompt-gen time
        # and lag behind config edits.
        tuned_steps, tuned_cfg, tuned_neg = _tune_for_motion(
            scene_type, settings.wan22_inference_steps, settings.wan22_guidance_scale,
            negative_prompt or "",
        )
        motion_flag = _is_motion_scene(scene_type)
        stack_str = " + ".join(f"{lid}@{lw}" for lid, _, lw in resolved) or "none"
        # Motion scenes go through FrameINO (motion-specialized 5B fine-tune)
        # when its weights are present; non-motion scenes use the vanilla
        # TI2V-5B base. Falls back to the base if FrameINO isn't downloaded.
        # FrameINO was investigated as a motion-specialized base model but
        # turns out to be architecturally incompatible (in_channels=96 vs
        # TI2V-5B's 48; requires custom FrameINOPipeline, not WanPipeline).
        # All scenes use vanilla TI2V-5B; motion is handled via
        # _tune_for_motion (steps + CFG bump).
        model_path = settings.wan22_model_path
        model_label = "ti2v-5b"
        logger.info(
            "Wan22 select [%s]: scene=%s shot=%s loras=[%s] postproc=%s motion=%s steps=%d cfg=%.1f model=%s",
            plan_source, scene_type, shot_type, stack_str, do_post_process,
            motion_flag, tuned_steps, tuned_cfg, model_label,
        )

        cmd = [
            settings.gpu_python_path, str(_SCRIPT_PATH),
            "--prompt", prompt,
            "--negative-prompt", tuned_neg,
            "--output", str(output_path),
            "--model", model_path,
            "--height", str(vs.height), "--width", str(vs.width),
            "--num-frames", str(vs.num_frames),
            "--num-inference-steps", str(tuned_steps),
            "--guidance-scale", str(tuned_cfg),
            "--fps", str(vs.fps), "--seed", str(vs.seed),
            "--lora-dir", settings.wan22_lora_dir,
        ]
        if resolved:
            # First entry goes through --lora-id/--lora-file/--lora-weight (legacy
            # primary slot); any further entries stack via repeatable --lora.
            p_id, p_file, p_w = resolved[0]
            cmd += ["--lora-id", p_id, "--lora-file", p_file, "--lora-weight", str(p_w)]
            for lid, lfile, lw in resolved[1:]:
                cmd += ["--lora", f"{lid}:{lfile}:{lw}"]
        # I2V chaining: only if a previous-scene last frame exists. character/bg pins
        # explicitly skipped per the no-frame-pin rule from earlier evals.
        if condition_image_path and Path(condition_image_path).exists():
            cmd += ["--condition-image", condition_image_path]
            logger.info("Wan22 I2V condition: %s", condition_image_path)
        if character_image_path and Path(character_image_path).exists():
            cmd += ["--last-image", character_image_path]
            logger.info("Wan22 last_image anchor: %s", character_image_path)

        gpu_idx = _cuda_device_index()
        from app.utils.gpu import largest_gpu_index
        if gpu_idx != largest_gpu_index():
            cmd += ["--sequential-offload"]
            logger.info("Wan22: small GPU %d — enabling sequential CPU offload", gpu_idx)

        env = os.environ.copy()
        env["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"
        env.setdefault("CUDA_DEVICE_ORDER", "PCI_BUS_ID")
        env["CUDA_VISIBLE_DEVICES"] = str(gpu_idx)

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE, env=env,
            )
            job_id = str(uuid.uuid4())
            self._active_jobs[job_id] = proc
            _, stderr = await proc.communicate()
            del self._active_jobs[job_id]

            if proc.returncode != 0:
                # tqdm spams stderr with progress bars that consume the tail
                # window. Strip them so the real error (Python traceback)
                # survives the 2000-char truncate.
                import re as _re
                raw = stderr.decode() if stderr else ""
                # tqdm formats: " 12%|███   | 3/40 [00:19<03:40,  5.96s/it]"
                # also pure step counts:        " 3/40 [00:19<03:40,  5.96s/it]"
                tqdm_re = _re.compile(r"\s*\d+%?\|?[^\|]*\|?\s*\d+/\d+\s*\[[^\]]*\][^\n\r]*")
                cleaned = tqdm_re.sub("", raw)
                # Collapse leftover blank/\r-only segments
                cleaned = _re.sub(r"[\r ]+\n", "\n", cleaned)
                cleaned = _re.sub(r"\n{3,}", "\n\n", cleaned).strip()
                err = cleaned[-2000:] or "Unknown error"
                logger.error("Wan22 failed: %s", err)
                return VideoResult(success=False, error=err)
            if not output_path.exists():
                return VideoResult(success=False, error="Output file not created")

            if do_post_process:
                await _post_process_face_restore(output_path, env)

            return VideoResult(
                success=True,
                file_path=str(output_path),
                duration_seconds=vs.num_frames / vs.fps,
                metadata={"provider": "wan22", "scene_type": scene_type,
                          "shot_type": shot_type,
                          "plan_source": plan_source,
                          "base_model": model_label,
                          "loras": [{"id": lid, "weight": lw}
                                    for lid, _, lw in resolved],
                          "post_process": do_post_process,
                          "height": vs.height, "width": vs.width,
                          "num_frames": vs.num_frames, "fps": vs.fps,
                          "motion": motion_flag, "steps": tuned_steps,
                          "guidance_scale": tuned_cfg},
            )
        except Exception as e:
            logger.exception("Wan22 generation error")
            return VideoResult(success=False, error=str(e))

    async def get_status(self, job_id: str) -> str:
        if job_id in self._active_jobs:
            proc = self._active_jobs[job_id]
            if proc.returncode is None:
                return "running"
            return "complete" if proc.returncode == 0 else "failed"
        return "unknown"

    async def cancel(self, job_id: str) -> None:
        if job_id in self._active_jobs:
            self._active_jobs[job_id].terminate()
