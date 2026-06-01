#!/usr/bin/env python3
"""Per-frame GFPGAN face restoration on a wan22 mp4.

Usage: wan22_face_restore.py <input.mp4> <output.mp4>
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import time
from pathlib import Path

import cv2
import torchvision.transforms.functional as _tvf
import sys as _sys
_sys.modules["torchvision.transforms.functional_tensor"] = _tvf
from gfpgan import GFPGANer

GFPGAN_WEIGHTS = "/home/akash/.cache/gfpgan/GFPGANv1.4.pth"
TMP_ROOT = Path("/tmp/wan22_face_restore")


def extract_frames(video: Path, frames_dir: Path) -> tuple[int, float]:
    frames_dir.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS)
    cap.release()
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(video),
                    "-q:v", "2", str(frames_dir / "f_%05d.png")], check=True)
    n = len(list(frames_dir.glob("f_*.png")))
    return n, fps


def restore_frames(in_dir: Path, out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    restorer = GFPGANer(model_path=GFPGAN_WEIGHTS, upscale=1,
                        arch="clean", channel_multiplier=2, bg_upsampler=None)
    frames = sorted(in_dir.glob("f_*.png"))
    t0 = time.time()
    for i, fp in enumerate(frames, 1):
        img = cv2.imread(str(fp), cv2.IMREAD_COLOR)
        _, _, restored = restorer.enhance(img, has_aligned=False,
                                          only_center_face=False, paste_back=True)
        cv2.imwrite(str(out_dir / fp.name), restored if restored is not None else img)
        if i % 12 == 0:
            print(f"  {i}/{len(frames)}  {(time.time()-t0)/i:.2f}s/frame")
    print(f"  restored {len(frames)} frames in {time.time()-t0:.1f}s")


def encode_video(frames_dir: Path, fps: float, out_mp4: Path):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", f"{fps}",
                    "-i", str(frames_dir / "f_%05d.png"),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18",
                    str(out_mp4)], check=True)


def main():
    if len(sys.argv) != 3:
        print("usage: wan22_face_restore.py <input.mp4> <output.mp4>")
        sys.exit(2)
    inp, out = Path(sys.argv[1]), Path(sys.argv[2])
    assert inp.exists(), f"missing input: {inp}"

    work = TMP_ROOT / inp.stem
    if work.exists():
        shutil.rmtree(work)
    raw, restored = work / "raw", work / "restored"

    print(f"[1/3] extract frames -> {raw}")
    n, fps = extract_frames(inp, raw)
    print(f"  {n} frames @ {fps:.2f} fps")

    print(f"[2/3] GFPGAN per frame")
    restore_frames(raw, restored)

    print(f"[3/3] encode -> {out}")
    encode_video(restored, fps, out)
    print(f"done.")


if __name__ == "__main__":
    main()
