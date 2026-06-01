#!/usr/bin/env python3
"""Per-frame Real-ESRGAN 2x upscale + GFPGAN face restore — face-from-afar test.

Usage: wan22_face_restore_v2.py <input.mp4> <output.mp4>
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import time
from pathlib import Path

import cv2
import torch
import torchvision.transforms.functional as _tvf
sys.modules["torchvision.transforms.functional_tensor"] = _tvf

from basicsr.archs.rrdbnet_arch import RRDBNet
from gfpgan import GFPGANer
from realesrgan import RealESRGANer

GFPGAN_W = "/home/akash/.cache/gfpgan/GFPGANv1.4.pth"
ESRGAN_W = "/home/akash/.cache/realesrgan/RealESRGAN_x4plus.pth"
TMP_ROOT = Path("/tmp/wan22_face_restore_v2")


def extract_frames(video: Path, frames_dir: Path) -> tuple[int, float]:
    frames_dir.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS)
    cap.release()
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(video),
                    "-q:v", "2", str(frames_dir / "f_%05d.png")], check=True)
    return len(list(frames_dir.glob("f_*.png"))), fps


def restore_frames(in_dir: Path, out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    rrdb = RRDBNet(num_in_ch=3, num_out_ch=3, num_feat=64, num_block=23, num_grow_ch=32, scale=4)
    upsampler = RealESRGANer(scale=4, model_path=ESRGAN_W, model=rrdb,
                             tile=400, tile_pad=10, pre_pad=0, half=True, device="cuda")
    restorer = GFPGANer(model_path=GFPGAN_W, upscale=2, arch="clean",
                        channel_multiplier=2, bg_upsampler=upsampler)
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


def encode(frames_dir: Path, fps: float, out: Path):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", f"{fps}",
                    "-i", str(frames_dir / "f_%05d.png"),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18",
                    str(out)], check=True)


def main():
    if len(sys.argv) != 3:
        print("usage: wan22_face_restore_v2.py <in.mp4> <out.mp4>")
        sys.exit(2)
    inp, out = Path(sys.argv[1]), Path(sys.argv[2])
    assert inp.exists()
    work = TMP_ROOT / inp.stem
    if work.exists():
        shutil.rmtree(work)
    raw, fixed = work / "raw", work / "fixed"
    print("[1/3] extract frames")
    n, fps = extract_frames(inp, raw)
    print(f"  {n} frames @ {fps:.2f} fps")
    print("[2/3] Real-ESRGAN 2x + GFPGAN")
    restore_frames(raw, fixed)
    print("[3/3] encode")
    encode(fixed, fps, out)
    print("done.")


if __name__ == "__main__":
    main()
