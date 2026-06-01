"""Stub audio provider — generates a silent audio file of the target duration."""

import asyncio
import logging
from pathlib import Path
from typing import Optional

from app.config import settings
from app.providers.audio.base import AudioProvider, AudioResult, AudioSettings

logger = logging.getLogger(__name__)


class StubAudioProvider(AudioProvider):
    """Generates a silent WAV file of the specified duration using FFmpeg."""

    async def generate_full_story_audio(
        self,
        narration_text: str,
        output_path: Path,
        target_duration: Optional[float] = None,
        audio_settings: Optional[AudioSettings] = None,
    ) -> AudioResult:
        audio_s = audio_settings or AudioSettings()
        duration = target_duration or 16.0  # Default to 16s if no target
        output_path.parent.mkdir(parents=True, exist_ok=True)

        cmd = [
            settings.ffmpeg_path,
            "-y",
            "-f", "lavfi",
            "-i", f"anullsrc=r={audio_s.sample_rate}:cl=stereo",
            "-t", str(duration),
            "-c:a", "pcm_s16le",
            str(output_path),
        ]

        logger.info("StubAudio: generating %ss silence -> %s", duration, output_path.name)

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()

            if proc.returncode != 0:
                error = stderr.decode()[-300:]
                return AudioResult(success=False, error=error)

            return AudioResult(
                success=True,
                file_path=str(output_path),
                duration_seconds=duration,
                metadata={"provider": "stub", "silent": True},
            )
        except Exception as e:
            logger.exception("StubAudio error")
            return AudioResult(success=False, error=str(e))

    async def get_status(self, job_id: str) -> str:
        return "complete"

    async def cancel(self, job_id: str) -> None:
        pass
