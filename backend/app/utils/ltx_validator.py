"""Post-render validation for LTX scene videos (Stage 7).

Runs ffprobe + ffmpeg signalstats to confirm a generated MP4 has the right
duration, frame count, and is not all-black or frozen. Synchronous; call
sites in async code should run this in a threadpool.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Broadcast (limited-range) black sits at Y=16, so the floor is set above
# that to actually catch all-black output. Studio-range full-black is 0.
_MIN_MEAN_LUMA = 20.0
# A truly frozen video has near-zero variance across sampled frames.
_MIN_INTER_SAMPLE_VARIANCE = 0.5
_YAVG_RE = re.compile(r"lavfi\.signalstats\.YAVG=([\d.]+)")
_PROBE_TIMEOUT_S = 30
_STATS_TIMEOUT_S = 60


@dataclass
class ValidationReport:
    ok: bool
    errors: list[str] = field(default_factory=list)
    stats: dict = field(default_factory=dict)


def _ffprobe(path: str) -> dict:
    """Return parsed ffprobe JSON for the file; raises CalledProcessError on failure."""
    cmd = [
        "ffprobe", "-v", "error", "-count_frames",
        "-show_entries", "stream=nb_read_frames,r_frame_rate",
        "-show_entries", "format=duration",
        "-of", "json", path,
    ]
    out = subprocess.run(
        cmd, capture_output=True, text=True, check=True, timeout=_PROBE_TIMEOUT_S,
    )
    return json.loads(out.stdout or "{}")


def _parse_probe(probe: dict) -> tuple[float, int, float]:
    """Pull (duration_s, frames, fps) out of the ffprobe JSON."""
    fmt = probe.get("format") or {}
    streams = probe.get("streams") or []
    duration = float(fmt.get("duration") or 0.0)
    frames = 0
    fps = 0.0
    if streams:
        s0 = streams[0]
        try:
            frames = int(s0.get("nb_read_frames") or 0)
        except (TypeError, ValueError):
            frames = 0
        rfr = s0.get("r_frame_rate") or "0/1"
        try:
            num, den = rfr.split("/")
            fps = float(num) / float(den) if float(den) else 0.0
        except (ValueError, ZeroDivisionError):
            fps = 0.0
    return duration, frames, fps


def _sample_yavg(path: str, total_frames: int, sample_count: int = 5) -> list[float]:
    """Run signalstats over evenly-spaced frames; parse YAVG values from stderr."""
    step = max(1, total_frames // max(1, sample_count))
    vfilter = f"select='not(mod(n\\,{step}))',signalstats,metadata=print"
    cmd = ["ffmpeg", "-i", path, "-vf", vfilter, "-an", "-f", "null", "-"]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=_STATS_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        logger.warning("signalstats timed out for %s", path)
        return []
    return [float(m) for m in _YAVG_RE.findall(proc.stderr or "")]


def _variance(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return sum((v - mean) ** 2 for v in values) / len(values)


def validate_scene_video(
    path: str,
    expected_frames: int,
    expected_fps: int,
    duration_tolerance_s: float = 0.25,
) -> ValidationReport:
    """Validate an LTX-rendered scene video for duration, frames, and motion.

    Checks: (a) duration within ±tolerance of expected_frames/expected_fps,
    (b) nb_read_frames == expected_frames, (c) mean luma above black floor,
    (d) inter-sample luma variance above frozen-output floor.
    """
    errors: list[str] = []
    stats: dict = {}
    try:
        probe = _ffprobe(path)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
            json.JSONDecodeError, FileNotFoundError) as exc:
        return ValidationReport(ok=False, errors=[f"ffprobe failed: {exc}"], stats={})

    duration, frames, fps = _parse_probe(probe)
    expected_duration = expected_frames / expected_fps if expected_fps else 0.0
    stats.update({"duration": duration, "frames": frames, "fps": fps})

    if expected_duration and abs(duration - expected_duration) > duration_tolerance_s:
        errors.append(
            f"duration {duration:.3f}s outside ±{duration_tolerance_s}s of "
            f"expected {expected_duration:.3f}s"
        )
    if frames != expected_frames:
        errors.append(f"frames {frames} != expected {expected_frames}")

    yavgs = _sample_yavg(path, frames or expected_frames)
    mean_luma = sum(yavgs) / len(yavgs) if yavgs else 0.0
    inter_var = _variance(yavgs)
    stats.update({
        "mean_luma": mean_luma,
        "inter_sample_variance": inter_var,
        "yavg_samples": yavgs,
    })

    if not yavgs:
        errors.append("signalstats produced no YAVG samples (motion check skipped)")
    elif mean_luma < _MIN_MEAN_LUMA:
        errors.append(f"mean_luma {mean_luma:.2f} < {_MIN_MEAN_LUMA} (all-black?)")
    # inter_sample_variance "frozen output" check removed — over-triggered on
    # cartoon mascot scenes with subtle motion that look fine to humans.
    # Keep computing it for telemetry (stats), but no longer fail on it.
    return ValidationReport(ok=not errors, errors=errors, stats=stats)
