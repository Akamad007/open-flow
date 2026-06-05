"""Burn subtitles into a video via ffmpeg's libass `subtitles` filter.

Burn-in re-encodes the video stream (it cannot be copied); audio is copied as-is.
Mirrors utils/audio_overlay.py. Raises on failure — callers decide whether to
fail soft (keep the un-burned render) or surface the error.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)


def _force_style(font: str, font_size: int, margin_v: int) -> str:
    # Matches FFmpegStitchingProvider._burn_captions so backfilled renders look
    # identical to ones the stitch pipeline produces.
    return (
        f"FontName={font},FontSize={font_size},"
        "PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,"
        f"BorderStyle=1,Outline=2,Shadow=1,Alignment=2,MarginV={margin_v}"
    )


def _escape_filter_path(path: Path) -> str:
    """Escape a path for use inside an ffmpeg filtergraph value."""
    return str(path).replace("\\", "\\\\").replace(":", r"\:").replace("'", r"\'")


async def burn_subtitles_into_video(
    video_path: Path,
    srt_path: Path,
    output_path: Path,
    font: str = "DejaVu Sans",
    font_size: int = 16,
    margin_v: int = 28,
    crf: int = 18,
    preset: str = "medium",
) -> Path:
    """Re-encode `video_path` with the cues in `srt_path` burned in; copy audio.

    Returns the output path on success; raises RuntimeError/FileNotFoundError
    on failure.
    """
    if not video_path.exists():
        raise FileNotFoundError(f"video not found: {video_path}")
    if not srt_path.exists():
        raise FileNotFoundError(f"subtitle file not found: {srt_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    vf = (
        f"subtitles=filename='{_escape_filter_path(srt_path)}':"
        f"force_style='{_force_style(font, font_size, margin_v)}'"
    )
    cmd = [
        settings.ffmpeg_path, "-y",
        "-i", str(video_path),
        "-vf", vf,
        "-c:v", "libx264", "-crf", str(crf), "-preset", preset, "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        str(output_path),
    ]
    logger.info(
        "ffmpeg burn subtitles: %s + %s -> %s",
        video_path.name, srt_path.name, output_path.name,
    )
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(
            f"ffmpeg burn failed (rc={proc.returncode}): "
            f"{(stderr or b'').decode(errors='replace')[-500:]}"
        )
    return output_path
