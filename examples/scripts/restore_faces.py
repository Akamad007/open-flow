#!/usr/bin/env python
"""Post-render face restoration for video clips.

Takes an MP4, runs GFPGAN per-frame on detected faces, re-encodes the
result with the original audio (if any). Generic restoration — not
identity-anchored. For identity lock against a portrait, swap to
InSwapper / insightface face_swap after running this.

Usage
  restore_faces.py INPUT.mp4 OUTPUT.mp4 [--upscale 1] [--bg-tile 400] [--device cuda]
"""
from __future__ import annotations

# Shim before any gfpgan/basicsr import — torchvision dropped functional_tensor.
import sys
import torchvision.transforms.functional as _tvf
sys.modules.setdefault('torchvision.transforms.functional_tensor', _tvf)

import argparse
import logging
import subprocess
from pathlib import Path

import cv2
import numpy as np
from gfpgan import GFPGANer

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(message)s")
log = logging.getLogger("restore_faces")

GFPGAN_MODEL_URL = (
    "https://github.com/TencentARC/GFPGAN/releases/download/v1.3.0/GFPGANv1.4.pth"
)


def _build_restorer(device: str, upscale: int) -> GFPGANer:
    model_path = Path.home() / ".cache" / "gfpgan" / "GFPGANv1.4.pth"
    model_path.parent.mkdir(parents=True, exist_ok=True)
    if not model_path.exists():
        log.info("Downloading GFPGANv1.4 weights → %s", model_path)
        subprocess.run(["wget", "-qO", str(model_path), GFPGAN_MODEL_URL], check=True)
    return GFPGANer(
        model_path=str(model_path),
        upscale=upscale,
        arch="clean",
        channel_multiplier=2,
        bg_upsampler=None,
        device=device,
    )


def restore(video_in: Path, video_out: Path, upscale: int, device: str) -> None:
    cap = cv2.VideoCapture(str(video_in))
    fps = cap.get(cv2.CAP_PROP_FPS) or 24
    n_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) * upscale
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) * upscale
    log.info("Input: %s (%dx%d @ %.2f fps, %d frames)", video_in, w // upscale, h // upscale, fps, n_frames)

    tmp = video_out.with_suffix(".silent.mp4")
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out = cv2.VideoWriter(str(tmp), fourcc, fps, (w, h))

    restorer = _build_restorer(device, upscale)
    log.info("Restoring faces on %d frames (device=%s, upscale=%dx)…", n_frames, device, upscale)

    i = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        _cropped, _restored, restored_frame = restorer.enhance(
            frame, has_aligned=False, only_center_face=False, paste_back=True,
        )
        if restored_frame is None:
            restored_frame = cv2.resize(frame, (w, h)) if upscale != 1 else frame
        out.write(restored_frame)
        i += 1
        if i % 12 == 0:
            log.info("  frame %d/%d", i, n_frames)

    cap.release()
    out.release()

    # Re-mux original audio if present.
    has_audio = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
         "stream=index", "-of", "csv=p=0", str(video_in)],
        capture_output=True, text=True,
    ).stdout.strip()
    if has_audio:
        log.info("Re-muxing original audio track")
        subprocess.run([
            "ffmpeg", "-y", "-i", str(tmp), "-i", str(video_in),
            "-c:v", "copy", "-c:a", "aac", "-map", "0:v:0", "-map", "1:a:0",
            "-shortest", str(video_out),
        ], check=True, capture_output=True)
        tmp.unlink()
    else:
        tmp.rename(video_out)
    log.info("✓ Wrote %s", video_out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", type=Path)
    ap.add_argument("output", type=Path)
    ap.add_argument("--upscale", type=int, default=1, choices=[1, 2, 4])
    ap.add_argument("--device", default="cuda", choices=["cuda", "cpu"])
    args = ap.parse_args()
    restore(args.input, args.output, args.upscale, args.device)
    return 0


if __name__ == "__main__":
    sys.exit(main())
