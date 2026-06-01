"""Download / probe audio from a public YouTube URL via yt-dlp.

Used by the episode pipeline to:
  1. Probe the audio duration at episode creation time so the scene planner
     can target the same length as the source audio.
  2. Download the audio at audio-generation time and stash it as a normal
     `full_story_audio` asset so the stitching stage can overlay it without
     special-casing.

Pure module: no DB, no celery. Callers pass the URL and the desired output
location; the helper returns the file path and probed metadata.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional

from yt_dlp import YoutubeDL

logger = logging.getLogger(__name__)

_URL_RE = re.compile(r"^https?://(?:www\.|m\.)?(youtube\.com|youtu\.be)/", re.I)

# yt-dlp's default player_client list starts with `android_vr` which YouTube
# now serves UNPLAYABLE for many videos. Listing real clients first makes
# yt-dlp fall through to a working one. Keep this list in sync between probe
# + download paths.
_YT_PLAYER_CLIENTS = ["web", "android", "ios", "mweb", "tv_embedded"]
_YT_EXTRACTOR_ARGS = {"youtube": {"player_client": _YT_PLAYER_CLIENTS}}


class YouTubeAudioError(RuntimeError):
    pass


def is_youtube_url(url: str | None) -> bool:
    return bool(url and _URL_RE.match(url.strip()))


def probe_duration(url: str) -> float:
    """Fetch the duration in seconds without downloading the audio."""
    from yt_dlp.utils import DownloadError

    if not is_youtube_url(url):
        raise YouTubeAudioError(f"Not a YouTube URL: {url!r}")
    opts = {
        "quiet": True, "no_warnings": True, "skip_download": True,
        "noplaylist": True, "extractor_args": _YT_EXTRACTOR_ARGS,
    }
    try:
        with YoutubeDL(opts) as y:
            info = y.extract_info(url, download=False)
    except DownloadError as e:
        msg = str(e)
        # YouTube returns "not available" for deleted, private, region-locked
        # and age-gated videos. Surface a friendlier client-facing message.
        if "not available" in msg.lower():
            raise YouTubeAudioError(
                "YouTube says this video is not available — it may have been "
                "deleted, made private, region-locked, or age-restricted. "
                "Open the URL in a private browser to confirm."
            ) from e
        raise YouTubeAudioError(f"yt-dlp probe failed: {msg}") from e
    duration = info.get("duration") if info else None
    if not duration:
        raise YouTubeAudioError(f"No duration metadata returned for {url}")
    return float(duration)


def download_audio(url: str, output_path: Path) -> Path:
    """Download the URL's audio to `output_path` (mp3). Returns the final path.

    output_path's suffix decides the post-process target (.mp3 / .m4a / .aac).
    Parent dir is created if missing.
    """
    if not is_youtube_url(url):
        raise YouTubeAudioError(f"Not a YouTube URL: {url!r}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    codec = output_path.suffix.lstrip(".").lower() or "mp3"
    # yt-dlp picks the extension from the postprocessor, not the outtmpl,
    # so strip our suffix from the template and let it append.
    outtmpl_stem = str(output_path.with_suffix(""))
    opts = {
        "format": "bestaudio/best",
        "outtmpl": outtmpl_stem + ".%(ext)s",
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "extractor_args": _YT_EXTRACTOR_ARGS,
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": codec,
            "preferredquality": "192",
        }],
    }
    with YoutubeDL(opts) as y:
        info = y.extract_info(url, download=True)
    final = Path(outtmpl_stem + f".{codec}")
    if not final.exists():
        # yt-dlp sometimes lands a different extension when the postproc fails;
        # find the produced file by stem.
        produced: Optional[Path] = next(
            (p for p in output_path.parent.iterdir()
             if p.stem == output_path.stem),
            None,
        )
        if produced is None:
            raise YouTubeAudioError(
                f"yt-dlp finished but no output file found near {output_path}"
            )
        final = produced
    logger.info("YouTube audio downloaded: %s (%.1fs)", final, info.get("duration") or 0.0)
    return final
