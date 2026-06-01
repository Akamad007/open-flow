"""SD 3.5 Medium image provider — wraps ~/sd35-medium/generate_sd35.py."""

import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import Optional

from app.config import settings as cfg
from app.providers.image.base import ImageProvider, ImageResult, ImageSettings
from app.utils.gpu import apply_gpu_env, get_pool

logger = logging.getLogger(__name__)

SD35_SCRIPT = Path.home() / "sd35-medium" / "generate_sd35.py"


def _gpu_python() -> str:
    """Resolve the python interpreter for GPU subprocess scripts.

    Default config value `"python"` is unsafe — system python rarely has
    torch installed. When the value is the bare default, fall back to the
    interpreter currently running this process (i.e. the project venv)."""
    p = cfg.gpu_python_path
    return sys.executable if p == "python" else p

# Indian folk art negative prompt — used for all SD 3.5 generations
FOLK_ART_NEGATIVE = (
    "photo, realistic, photograph, 3d render, CGI, anime, manga, western cartoon, "
    "blurry, ugly, watermark, text, logo, extra limbs, deformed, mutated, "
    "low quality, bad quality, out of focus"
)


class SD35ImageProvider(ImageProvider):
    """
    Generates images using Stable Diffusion 3.5 Medium via the existing
    ~/sd35-medium/generate_sd35.py script.
    Runs as a subprocess to avoid loading the model into the web server process.
    VRAM is fully released after each call via sequential CPU offload inside the script.
    """

    async def generate_image(
        self,
        prompt: str,
        negative_prompt: str,
        output_path: Path,
        settings: Optional[ImageSettings] = None,
    ) -> ImageResult:
        s = settings or ImageSettings(
            width=cfg.sd35_char_width,
            height=cfg.sd35_char_height,
            num_inference_steps=cfg.sd35_steps,
            guidance_scale=cfg.sd35_guidance,
        )

        output_path.parent.mkdir(parents=True, exist_ok=True)

        if not SD35_SCRIPT.exists():
            return ImageResult(
                success=False,
                error=f"SD 3.5 script not found: {SD35_SCRIPT}. "
                      "Please ensure ~/sd35-medium/generate_sd35.py exists.",
            )

        cmd = [
            _gpu_python(),
            str(SD35_SCRIPT),
            "--prompt", prompt,
            "--negative", negative_prompt or FOLK_ART_NEGATIVE,
            "--out", str(output_path),
            "--width", str(s.width),
            "--height", str(s.height),
            "--steps", str(s.num_inference_steps),
            "--guidance", str(s.guidance_scale),
            "--seed", str(s.seed),
        ]

        if s.no_t5:
            cmd.append("--no-t5")

        # Img2img mode: pass reference image for character identity consistency
        if s.init_image_path and Path(s.init_image_path).exists():
            cmd += ["--init-image", str(s.init_image_path), "--strength", str(s.strength)]
            logger.info("SD 3.5 img2img: reference=%s strength=%.2f", s.init_image_path, s.strength)

        env = {
            **os.environ,
            "PYTORCH_CUDA_ALLOC_CONF": "expandable_segments:True",
        }
        if cfg.hf_token:
            env["HF_TOKEN"] = cfg.hf_token
            env["HUGGING_FACE_HUB_TOKEN"] = cfg.hf_token  # legacy key

        logger.info(
            "SD 3.5: %dx%d, %d steps, guidance=%.1f → %s",
            s.width, s.height, s.num_inference_steps, s.guidance_scale, output_path.name,
        )

        try:
            async with get_pool().acquire() as gpu_idx:
                apply_gpu_env(env, gpu_idx)
                logger.info("SD 3.5 → GPU %d", gpu_idx)
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=env,
                )
                stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                error = stderr.decode()[-600:] if stderr else "Unknown error"
                logger.error("SD 3.5 failed (rc=%d): %s", proc.returncode, error)
                return ImageResult(success=False, error=error)

            if not output_path.exists():
                return ImageResult(success=False, error="Output file not created by SD 3.5")

            logger.info("SD 3.5 complete → %s", output_path)
            return ImageResult(
                success=True,
                file_path=str(output_path),
                metadata={"provider": "sd35", "width": s.width, "height": s.height,
                          "steps": s.num_inference_steps, "guidance": s.guidance_scale},
            )

        except Exception as e:
            logger.exception("SD 3.5 generation error")
            return ImageResult(success=False, error=str(e))
