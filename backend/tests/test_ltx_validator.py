"""Smoke tests for the LTX post-render validator (Stage 7).

Uses local ffmpeg/ffprobe binaries only (no network, no providers).
"""

from __future__ import annotations

import inspect
import shutil
import subprocess
from pathlib import Path

import pytest

from app.utils.ltx_validator import ValidationReport, validate_scene_video


def test_signature_and_dataclass():
    sig = inspect.signature(validate_scene_video)
    params = list(sig.parameters)
    assert params == ["path", "expected_frames", "expected_fps", "duration_tolerance_s"]
    assert sig.parameters["duration_tolerance_s"].default == 0.25
    rep = ValidationReport(ok=True)
    assert rep.errors == [] and rep.stats == {}


def test_missing_file_returns_failure(tmp_path: Path):
    rep = validate_scene_video(str(tmp_path / "nope.mp4"), 12, 12)
    assert rep.ok is False
    assert any("ffprobe" in e for e in rep.errors)


@pytest.mark.skipif(
    shutil.which("ffprobe") is None or shutil.which("ffmpeg") is None,
    reason="ffmpeg/ffprobe not installed",
)
def test_catches_all_black(tmp_path: Path):
    """An all-black 12-frame clip must fail validation on mean_luma."""
    out = tmp_path / "black.mp4"
    cmd = [
        "ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=black:s=64x64:r=12",
        "-frames:v", "12", str(out),
    ]
    subprocess.run(cmd, capture_output=True, check=True, timeout=30)
    assert out.exists()
    rep = validate_scene_video(str(out), expected_frames=12, expected_fps=12)
    assert rep.ok is False
    assert any("mean_luma" in e or "all-black" in e for e in rep.errors), rep.errors
    assert rep.stats["frames"] == 12
    assert rep.stats["fps"] == 12.0
    assert abs(rep.stats["duration"] - 1.0) < 0.05
    assert rep.stats["mean_luma"] < 20.0
