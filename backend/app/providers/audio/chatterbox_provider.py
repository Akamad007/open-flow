"""
Chatterbox TTS audio provider — generates full-story narration using
the Chatterbox TurboTTS model with voice cloning from a reference clip.

Runs the model as a subprocess (like LTX-Video) to avoid loading it
into the web server or Celery worker process memory.
"""

import asyncio
import json
import logging
from pathlib import Path
from typing import Optional

from app.config import settings
from app.providers.audio.base import AudioProvider, AudioResult, AudioSettings
from app.utils.gpu import apply_gpu_env, non_largest_gpu_index

logger = logging.getLogger(__name__)


class ChatterboxAudioProvider(AudioProvider):
    """
    Generates narration audio using Chatterbox TurboTTS.

    Uses a reference voice clip for voice cloning — the reference should be
    a ~10-18s WAV of the desired narrator voice (deep anchor/commentator style).
    """

    def __init__(self):
        self._script_path = Path(__file__).parent.parent.parent.parent.parent / "chatterbox_generate.py"
        self._reference_path = settings.chatterbox_reference_audio
        self._active_jobs: dict[str, asyncio.subprocess.Process] = {}

    async def generate_full_story_audio(
        self,
        narration_text: str,
        output_path: Path,
        target_duration: Optional[float] = None,
        audio_settings: Optional[AudioSettings] = None,
    ) -> AudioResult:
        if not narration_text.strip():
            return AudioResult(success=False, error="Empty narration text")

        if not self._reference_path.exists():
            return AudioResult(
                success=False,
                error=f"Reference audio not found: {self._reference_path}",
            )

        output_path.parent.mkdir(parents=True, exist_ok=True)

        cmd = [
            settings.gpu_python_path, str(self._script_path),
            "--text", narration_text,
            "--reference", str(self._reference_path),
            "--output", str(output_path),
            "--max-chunk-chars", str(settings.chatterbox_max_chunk_chars),
        ]

        if target_duration:
            cmd += ["--max-duration", str(target_duration)]

        logger.info(
            "Chatterbox: generating narration (%d chars) -> %s",
            len(narration_text), output_path.name,
        )

        import os
        env = {**os.environ}

        # Pin Chatterbox to the smaller (non-largest) GPU so it doesn't
        # compete for VRAM with Wan22 video gen on the big card.
        gpu_idx = non_largest_gpu_index()
        apply_gpu_env(env, gpu_idx)
        logger.info("Chatterbox → GPU %d (non-largest)", gpu_idx)
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )

            import uuid
            job_id = str(uuid.uuid4())
            self._active_jobs[job_id] = proc

            stdout, stderr = await proc.communicate()

            del self._active_jobs[job_id]

            if proc.returncode != 0:
                error_msg = stderr.decode()[-500:] if stderr else "Unknown error"
                logger.error("Chatterbox failed: %s", error_msg)
                return AudioResult(success=False, error=error_msg)

            if not output_path.exists():
                return AudioResult(success=False, error="Output file not created")

            # Parse metadata from the last line of stdout
            stdout_text = stdout.decode().strip()
            duration = 0.0
            metadata = {"provider": "chatterbox"}

            # The script prints JSON on the last line
            for line in reversed(stdout_text.splitlines()):
                line = line.strip()
                if line.startswith("{"):
                    try:
                        parsed = json.loads(line)
                        duration = parsed.get("duration", 0.0)
                        metadata.update(parsed)
                        break
                    except json.JSONDecodeError:
                        pass

            # Fallback: get duration from ffprobe if not parsed
            if duration == 0.0:
                duration = await self._get_duration(output_path)

            logger.info("Chatterbox narration complete: %.1fs", duration)

            return AudioResult(
                success=True,
                file_path=str(output_path),
                duration_seconds=duration,
                metadata=metadata,
            )

        except Exception as e:
            logger.exception("Chatterbox generation error")
            return AudioResult(success=False, error=str(e))

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

    @staticmethod
    async def _get_duration(file_path: Path) -> float:
        """Fallback: get duration via ffprobe."""
        proc = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-show_format", str(file_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        try:
            data = json.loads(stdout.decode())
            return float(data.get("format", {}).get("duration", 0))
        except (json.JSONDecodeError, ValueError):
            return 0.0
