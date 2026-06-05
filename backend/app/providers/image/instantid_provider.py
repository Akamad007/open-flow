"""InstantID-XL image provider — identity-locked SDXL via subprocess.

InstantID conditions SDXL on a face-embedding + IdentityNet keypoints
extracted from a single portrait, producing the same identity across new
poses, expressions, and outfits with no per-character training. We use
SDXL (not FLUX) because the FLUX.1-dev license is non-commercial and
this app produces ad content; the small ID-quality gap vs PuLID-FLUX is
the price of commercial safety.

The heavy model loading lives in `~/instantid/generate_instantid.py`
(parallel to `~/sd35-medium/generate_sd35.py`) — a subprocess so VRAM is
fully released after each call. Embeddings are pre-extracted once via
`_identity.py` and passed as `--id-embed`; if missing, the script falls
back to extracting from the raw portrait (slower).
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import Optional

from app.config import settings as cfg
from app.providers.image.base import (
    IdentityRef, ImageProvider, ImageResult, ImageSettings,
)
from app.utils.daemon_pool import get_instantid_manager
from app.utils.gpu import apply_gpu_env, get_pool


def _gpu_python() -> str:
    p = cfg.gpu_python_path
    return sys.executable if p == "python" else p

logger = logging.getLogger(__name__)

INSTANTID_SCRIPT = Path(cfg.instantid_dir) / "generate_instantid.py"
INSTANTID_POSE_SCRIPT = Path(cfg.instantid_dir) / "generate_instantid_pose.py"


class InstantIDImageProvider(ImageProvider):
    """SDXL + InstantID. Use only via `generate_with_identity`; the plain
    `generate_image` path falls back to the project's SD3.5 provider for
    portraits/backgrounds/products (those don't need face-identity
    locking).

    Two backends, picked by whether ImageSettings.pose_image_path is set:
      - face-only InstantID  (no pose ref) → identity locked, body pose
        biased toward the portrait's body pose.
      - InstantID + OpenPose dual-ControlNet (pose ref present) → identity
        locked AND body pose locked to the pose reference. This is the
        production path for action stills."""

    supports_identity = True

    def __init__(self, fallback: Optional[ImageProvider] = None):
        self._fallback = fallback

    async def generate_image(
        self,
        prompt: str,
        negative_prompt: str,
        output_path: Path,
        settings: Optional[ImageSettings] = None,
    ) -> ImageResult:
        if self._fallback is None:
            return ImageResult(
                success=False,
                error="InstantID provider has no fallback for non-identity calls",
            )
        return await self._fallback.generate_image(
            prompt, negative_prompt, output_path, settings,
        )

    async def generate_with_identity(
        self,
        prompt: str,
        negative_prompt: str,
        output_path: Path,
        identity: IdentityRef,
        settings: Optional[ImageSettings] = None,
    ) -> ImageResult:
        s = settings or ImageSettings()
        output_path.parent.mkdir(parents=True, exist_ok=True)

        use_pose = bool(s.pose_image_path and Path(s.pose_image_path).exists())
        script = INSTANTID_POSE_SCRIPT if use_pose else INSTANTID_SCRIPT
        if not script.exists():
            return ImageResult(
                success=False,
                error=f"InstantID script not found: {script}",
            )

        # InstantID converges in ≤40 steps; 40 gives slightly cleaner outputs
        # than 30 at modest extra time.
        steps = min(s.num_inference_steps, 40)
        cmd = [
            _gpu_python(), str(script),
            "--prompt", prompt,
            "--negative", negative_prompt or "",
            "--out", str(output_path),
            "--portrait", identity.portrait_path,
            "--width", str(s.width),
            "--height", str(s.height),
            "--steps", str(steps),
            "--guidance", str(s.guidance_scale),
            "--id-strength", f"{s.identity_strength:.2f}",
            "--seed", str(s.seed),
        ]
        if use_pose:
            cmd += [
                "--pose-image", s.pose_image_path,
                "--pose-strength", f"{s.pose_strength:.2f}",
            ]
        elif identity.embedding_path:
            cmd += ["--id-embed", identity.embedding_path]

        env = {**os.environ, "PYTORCH_CUDA_ALLOC_CONF": "expandable_segments:True"}
        if cfg.hf_token:
            env["HF_TOKEN"] = cfg.hf_token
            env["HUGGING_FACE_HUB_TOKEN"] = cfg.hf_token

        logger.info(
            "InstantID-XL%s: %dx%d steps=%d id=%.2f%s → %s",
            "-pose" if use_pose else "",
            s.width, s.height, steps, s.identity_strength,
            f" pose={s.pose_strength:.2f}" if use_pose else "",
            output_path.name,
        )

        # Daemon path: only for dual-CN (the production flow). Face-only
        # mode keeps the subprocess path because it's rarely used and a
        # second daemon kind isn't worth maintaining.
        daemon = get_instantid_manager() if (
            use_pose and cfg.instantid_daemon_enabled
        ) else None

        try:
            async with get_pool().acquire() as gpu_idx:
                if daemon is not None:
                    payload = {
                        "prompt": prompt, "negative": negative_prompt or "",
                        "out": str(output_path),
                        "portrait": identity.portrait_path,
                        "pose_image": s.pose_image_path,
                        "width": s.width, "height": s.height,
                        "steps": steps, "guidance": s.guidance_scale,
                        "id_strength": s.identity_strength,
                        "pose_strength": s.pose_strength,
                        "seed": s.seed,
                    }
                    try:
                        logger.info("InstantID daemon → GPU %d", gpu_idx)
                        resp = await daemon.request(gpu_idx, payload)
                        if resp.get("success"):
                            logger.info(
                                "InstantID daemon complete → %s (%.1fs)",
                                output_path, resp.get("elapsed_s", 0.0),
                            )
                            return ImageResult(
                                success=True, file_path=str(output_path),
                                metadata={
                                    "provider": "instantid_xl_pose_daemon",
                                    "id_strength": s.identity_strength,
                                    "pose_strength": s.pose_strength,
                                    "pose_image": s.pose_image_path,
                                    "elapsed_s": resp.get("elapsed_s"),
                                },
                            )
                        logger.warning(
                            "InstantID daemon returned error, falling back to subprocess: %s",
                            resp.get("error"),
                        )
                    except Exception as de:
                        logger.warning(
                            "InstantID daemon failed (%s), falling back to subprocess",
                            de,
                        )

                apply_gpu_env(env, gpu_idx)
                logger.info("InstantID → GPU %d", gpu_idx)
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=env,
                )
                stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                err = (stderr.decode() if stderr else "")[-600:]
                logger.error("InstantID failed (rc=%d): %s", proc.returncode, err)
                return ImageResult(success=False, error=err or "Unknown error")

            if not output_path.exists():
                return ImageResult(success=False, error="InstantID produced no output file")

            logger.info("InstantID complete → %s", output_path)
            return ImageResult(
                success=True,
                file_path=str(output_path),
                metadata={
                    "provider": "instantid_xl_pose" if use_pose else "instantid_xl",
                    "id_strength": s.identity_strength,
                    "pose_strength": s.pose_strength if use_pose else None,
                    "pose_image": s.pose_image_path if use_pose else None,
                },
            )
        except Exception as e:
            logger.exception("InstantID generation error")
            return ImageResult(success=False, error=str(e))
