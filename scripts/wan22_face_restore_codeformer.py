#!/usr/bin/env python3
"""Per-frame CodeFormer face restoration + Real-ESRGAN 2x bg upsample.

Reuses helpers across frames (codeformer-pip's inference_app re-instantiates them per call).
Fidelity knob: 0.0 = max quality (free reconstruction), 1.0 = max fidelity (conservative).

Usage: wan22_face_restore_codeformer.py <input.mp4> <output.mp4> <fidelity>
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

from basicsr.utils import img2tensor, tensor2img, imwrite
from codeformer.facelib.utils.face_restoration_helper import FaceRestoreHelper
from torchvision.transforms.functional import normalize

from codeformer.app import codeformer_net, device, upsampler

TMP_ROOT = Path("/tmp/wan22_face_restore_codeformer")
UPSCALE = 2


def extract(video: Path, frames_dir: Path) -> tuple[int, float, int, int]:
    frames_dir.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS)
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(video),
                    "-q:v", "2", str(frames_dir / "f_%05d.png")], check=True)
    return len(list(frames_dir.glob("f_*.png"))), fps, w, h


def restore(in_dir: Path, out_dir: Path, fidelity: float):
    out_dir.mkdir(parents=True, exist_ok=True)
    helper = FaceRestoreHelper(UPSCALE, face_size=512, crop_ratio=(1, 1),
                               det_model="retinaface_resnet50", save_ext="png",
                               use_parse=True, device=device)
    frames = sorted(in_dir.glob("f_*.png"))
    t0 = time.time()
    for i, fp in enumerate(frames, 1):
        img = cv2.imread(str(fp), cv2.IMREAD_COLOR)
        helper.clean_all()
        helper.read_image(img)
        n = helper.get_face_landmarks_5(only_center_face=False, resize=640, eye_dist_threshold=5)
        helper.align_warp_face()
        for face in helper.cropped_faces:
            t = img2tensor(face / 255.0, bgr2rgb=True, float32=True)
            normalize(t, (0.5, 0.5, 0.5), (0.5, 0.5, 0.5), inplace=True)
            t = t.unsqueeze(0).to(device)
            with torch.no_grad():
                out_t = codeformer_net(t, w=fidelity, adain=True)[0]
                restored = tensor2img(out_t, rgb2bgr=True, min_max=(-1, 1)).astype("uint8")
            helper.add_restored_face(restored)
        bg = upsampler.enhance(img, outscale=UPSCALE)[0]
        helper.get_inverse_affine(None)
        result = helper.paste_faces_to_input_image(upsample_img=bg, draw_box=False,
                                                   face_upsampler=upsampler)
        imwrite(result, str(out_dir / fp.name))
        if i % 12 == 0:
            print(f"  {i}/{len(frames)}  faces={n}  {(time.time()-t0)/i:.2f}s/frame")
    print(f"  restored {len(frames)} frames in {time.time()-t0:.1f}s")


def encode(frames_dir: Path, fps: float, out: Path, target_w: int, target_h: int):
    # Scale restored frames back to the input video's dimensions so downstream
    # stitching can xfade against unprocessed (non-postproc) scenes without
    # size-mismatch errors. The 2x upscale stays internal for face quality.
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", f"{fps}",
                    "-i", str(frames_dir / "f_%05d.png"),
                    "-vf", f"scale={target_w}:{target_h}:flags=lanczos",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18",
                    str(out)], check=True)


def main():
    if len(sys.argv) != 4:
        print("usage: wan22_face_restore_codeformer.py <in.mp4> <out.mp4> <fidelity 0-1>")
        sys.exit(2)
    inp, out, fidelity = Path(sys.argv[1]), Path(sys.argv[2]), float(sys.argv[3])
    assert inp.exists()
    work = TMP_ROOT / inp.stem
    if work.exists():
        shutil.rmtree(work)
    raw, fixed = work / "raw", work / "fixed"
    print(f"[1/3] extract frames")
    n, fps, w, h = extract(inp, raw)
    print(f"  {n} frames @ {fps:.2f} fps  src={w}x{h}")
    print(f"[2/3] CodeFormer (fidelity={fidelity}) + RealESRGAN x{UPSCALE}")
    restore(raw, fixed, fidelity)
    print(f"[3/3] encode -> {w}x{h}")
    encode(fixed, fps, out, w, h)
    print("done.")


if __name__ == "__main__":
    main()
