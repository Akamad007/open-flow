"""Stub video provider — generates colored placeholder videos using FFmpeg."""

import asyncio
import logging
import random
from pathlib import Path
from typing import Optional

from app.config import settings
from app.providers.video.base import VideoProvider, VideoResult, VideoSettings

logger = logging.getLogger(__name__)

# Cinematic color pairs (background, text) for placeholder videos
PLACEHOLDER_COLORS = [
    ("0x1a1a2e", "0xe94560"),
    ("0x16213e", "0x0f3460"),
    ("0x0f0e17", "0xff8906"),
    ("0x1b1b2f", "0x1f4068"),
    ("0x2d132c", "0xee4540"),
]


class StubVideoProvider(VideoProvider):
    """Generates placeholder videos using FFmpeg — no GPU required."""

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
        vs = video_settings or VideoSettings()
        output_path.parent.mkdir(parents=True, exist_ok=True)

        duration = vs.num_frames / vs.fps
        bg, fg = random.choice(PLACEHOLDER_COLORS)

        # Truncate prompt for display
        display_text = prompt[:60].replace("'", "").replace('"', '').replace(":", " ")

        cmd = [
            settings.ffmpeg_path,
            "-y",
            "-f", "lavfi",
            "-i", (
                f"color=c={bg}:s={vs.width}x{vs.height}:d={duration}:r={vs.fps},"
                f"drawtext=text='{display_text}':fontcolor={fg}:fontsize=20:"
                f"x=(w-text_w)/2:y=(h-text_h)/2:borderw=2:bordercolor=black"
            ),
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-preset", "ultrafast",
            str(output_path),
        ]

        logger.info("StubVideo: generating placeholder %s (%.1fs)", output_path.name, duration)

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()

            if proc.returncode != 0:
                error = stderr.decode()[-300:]
                logger.error("StubVideo FFmpeg error: %s", error)
                return VideoResult(success=False, error=error)

            return VideoResult(
                success=True,
                file_path=str(output_path),
                duration_seconds=duration,
                metadata={"provider": "stub", "placeholder": True},
            )
        except Exception as e:
            logger.exception("StubVideo error")
            return VideoResult(success=False, error=str(e))

    async def get_status(self, job_id: str) -> str:
        return "complete"

    async def cancel(self, job_id: str) -> None:
        pass
