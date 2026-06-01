"""Overlay an audio file onto an existing video file via ffmpeg.

Strips the video's original audio stream (`-map 0:v:0`) and mixes in the new
audio (`-map 1:a:0`). Re-encoding the audio to AAC is required; the video
stream is copied as-is so there's no re-encode cost.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)


async def _ffprobe_duration(path: Path) -> float:
    proc = await asyncio.create_subprocess_exec(
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(path),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    out, _ = await proc.communicate()
    try:
        return float((out or b"").decode().strip() or "0")
    except ValueError:
        return 0.0


async def overlay_audio_on_video(
    video_path: Path,
    audio_path: Path,
    output_path: Path,
    audio_codec: str = "aac",
    mode: str = "replace",
    background_volume: float = 0.35,
) -> Path:
    """Overlay `audio_path` onto `video_path`.

    mode='replace' (default): strip the video's existing audio and use only the
    new track — produces video.video + audio.audio.
    mode='mix': keep the video's existing audio (e.g. narration) and mix the
    new track UNDER it at `background_volume` (0.0-1.0). Used for "narration +
    YouTube background music" overlays.

    Returns the output path on success; raises RuntimeError on failure.
    """
    if mode not in ("replace", "mix"):
        raise ValueError(f"mode must be 'replace' or 'mix', got {mode!r}")
    if not video_path.exists():
        raise FileNotFoundError(f"video not found: {video_path}")
    if not audio_path.exists():
        raise FileNotFoundError(f"audio not found: {audio_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    video_duration = await _ffprobe_duration(video_path)
    if video_duration <= 0:
        raise RuntimeError(f"could not probe duration of {video_path}")

    base = [
        settings.ffmpeg_path, "-y",
        "-i", str(video_path),
        "-i", str(audio_path),
        "-c:v", "copy",
        "-c:a", audio_codec,
        "-b:a", "192k",
        "-t", str(video_duration),
    ]
    if mode == "replace":
        cmd = base + [
            "-map", "0:v:0",      # drop original audio
            "-map", "1:a:0",
            "-shortest",
            str(output_path),
        ]
    else:  # mix — narration foreground (input 0), YT background ducked (input 1)
        v = max(0.0, min(1.0, background_volume))
        filt = (
            f"[0:a]volume=1.0[a0];"
            f"[1:a]volume={v:.2f}[a1];"
            f"[a0][a1]amix=inputs=2:duration=first:dropout_transition=0[aout]"
        )
        cmd = base + [
            "-filter_complex", filt,
            "-map", "0:v:0",
            "-map", "[aout]",
            "-shortest",
            str(output_path),
        ]
    logger.info(
        "ffmpeg overlay (%s): %s + %s -> %s",
        mode, video_path.name, audio_path.name, output_path.name,
    )
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(
            f"ffmpeg overlay failed (rc={proc.returncode}, mode={mode}): "
            f"{(stderr or b'').decode(errors='replace')[-500:]}"
        )
    return output_path


async def mix_two_audio_tracks(
    foreground_path: Path,
    background_path: Path,
    output_path: Path,
    background_volume: float = 0.35,
    audio_codec: str = "mp3",
) -> Path:
    """Mix `foreground_path` (full volume) with `background_path` (ducked) into one audio file.

    Used by audio_generation to bake narration + YouTube background music into a
    single full_story_audio asset so the stitching stage doesn't need to know
    about the mix.
    """
    if not foreground_path.exists():
        raise FileNotFoundError(f"foreground audio not found: {foreground_path}")
    if not background_path.exists():
        raise FileNotFoundError(f"background audio not found: {background_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    v = max(0.0, min(1.0, background_volume))
    filt = (
        f"[0:a]volume=1.0[a0];"
        f"[1:a]volume={v:.2f}[a1];"
        f"[a0][a1]amix=inputs=2:duration=first:dropout_transition=0[aout]"
    )
    codec_args = ["-c:a", "libmp3lame", "-b:a", "192k"] if audio_codec == "mp3" else \
        ["-c:a", audio_codec, "-b:a", "192k"]
    cmd = [
        settings.ffmpeg_path, "-y",
        "-i", str(foreground_path),
        "-i", str(background_path),
        "-filter_complex", filt,
        "-map", "[aout]",
        *codec_args,
        str(output_path),
    ]
    logger.info(
        "ffmpeg audio mix: %s + %s (bg=%.2f) -> %s",
        foreground_path.name, background_path.name, v, output_path.name,
    )
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(
            f"ffmpeg audio mix failed (rc={proc.returncode}): "
            f"{(stderr or b'').decode(errors='replace')[-500:]}"
        )
    return output_path
