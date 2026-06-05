"""Phantom-Wan 14B video provider — wraps wan_generate.py via subprocess.

Phantom is a subject-driven video model: pass 1-4 reference images and the
generated video preserves identity at the model level (no frame pinning,
unlike LTX). This avoids the morph failure mode that wrecked F-CANON-PORTRAIT.

Conditioning translation:
  - character_image_path   → first --ref-image (always passed; canonical portrait)
  - scene_action_images    → additional --ref-image (up to 3 more; subject in different poses)
  - condition_image_path   → trailing --ref-image (prev-scene last frame for continuity;
                              capped by the 4-ref limit, lowest priority)
  - background_image_path  → IGNORED (Phantom does not consume backgrounds as conditions)

The script handles FP8 layerwise casting + CPU offload to fit on 16 GB.
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from pathlib import Path
from typing import Optional

from app.config import settings
from app.providers.video.base import VideoProvider, VideoResult, VideoSettings

logger = logging.getLogger(__name__)


class WanPhantomVideoProvider(VideoProvider):
    """Phantom-Wan 14B via wan_generate.py subprocess."""

    def __init__(self):
        self._script_path = Path(__file__).parent.parent.parent.parent.parent / "engines" / "wan_generate.py"
        self._active_jobs: dict[str, asyncio.subprocess.Process] = {}

    async def generate_video(
        self,
        prompt: str,
        negative_prompt: str,
        output_path: Path,
        video_settings: Optional[VideoSettings] = None,
        condition_image_path: Optional[str] = None,
        character_image_path: Optional[str] = None,
        background_image_path: Optional[str] = None,
        scene_action_images: Optional[list[str]] = None,
        lora_plan_json: Optional[str] = None,
    ) -> VideoResult:
        vs = video_settings or VideoSettings(
            height=480, width=832, num_frames=65, fps=16,
            num_inference_steps=50, guidance_scale=7.5, seed=42,
        )

        ref_images: list[str] = []
        if character_image_path and Path(character_image_path).exists():
            ref_images.append(character_image_path)
        if scene_action_images:
            for p in scene_action_images:
                if p and Path(p).exists() and len(ref_images) < 4:
                    ref_images.append(p)
        if (condition_image_path
                and Path(condition_image_path).exists()
                and len(ref_images) < 4):
            logger.info("Phantom: appending prev-scene last frame as extra ref → %s",
                        condition_image_path)
            ref_images.append(condition_image_path)
        if not ref_images:
            return VideoResult(
                success=False,
                error="Phantom-Wan requires at least one reference image "
                      "(set character_image_path or scene_action_images).",
            )

        output_path.parent.mkdir(parents=True, exist_ok=True)

        cmd = [
            settings.gpu_python_path, str(self._script_path),
            "--task", "s2v-14B",
            "--prompt", prompt,
            "--output", str(output_path),
            "--width", str(vs.width),
            "--height", str(vs.height),
            "--num-frames", str(vs.num_frames),
            "--fps", str(vs.fps),
            "--steps", str(vs.num_inference_steps),
            "--guidance-text", str(vs.guidance_scale),
            "--seed", str(vs.seed),
        ]
        for ref in ref_images:
            cmd += ["--ref-image", ref]

        from app.utils.gpu import largest_gpu_index
        env = os.environ.copy()
        env["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"
        env.setdefault("CUDA_DEVICE_ORDER", "PCI_BUS_ID")
        env["CUDA_VISIBLE_DEVICES"] = str(largest_gpu_index())  # largest GPU, FP8 layerwise (quantized)
        env["WAN_FP8"] = "1"                  # see FIXES_LOG F-WAN-PHANTOM iter8

        logger.info("Phantom-Wan: %s, refs=%d", " ".join(cmd[:8]) + "...", len(ref_images))

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            job_id = str(uuid.uuid4())
            self._active_jobs[job_id] = proc
            stdout, stderr = await proc.communicate()
            del self._active_jobs[job_id]

            if proc.returncode != 0:
                err = (stderr.decode()[-500:] if stderr else "Unknown error")
                logger.error("Phantom-Wan failed: %s", err)
                return VideoResult(success=False, error=err)
            if not output_path.exists():
                return VideoResult(success=False, error="Output mp4 not written")

            duration = vs.num_frames / vs.fps
            return VideoResult(
                success=True,
                file_path=str(output_path),
                duration_seconds=duration,
                metadata={
                    "provider": "wan_phantom",
                    "task": "s2v-14B",
                    "num_ref_images": len(ref_images),
                    "height": vs.height, "width": vs.width,
                    "num_frames": vs.num_frames, "fps": vs.fps,
                },
            )
        except Exception as e:
            logger.exception("Phantom-Wan generation error")
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
