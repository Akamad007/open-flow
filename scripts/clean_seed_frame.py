#!/usr/bin/env python3
"""Clean a last-frame I2V seed before it conditions the next scene.

Degrains (ffmpeg hqdn3d) + sharpens (unsharp) to kill the compounding H.264
grain that turns a chained episode "bad to worse", then re-locks the face with
CodeFormer so identity doesn't drift down the chain. Writes <out>, leaving <in>
untouched; the caller treats failure as non-fatal and keeps the raw seed.

Usage: clean_seed_frame.py <in.png> <out.png> <fidelity 0-1>
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

# Pin the GPU before torch import — CodeFormer picks its device at import time.
_gpu = os.environ.get("WAN22_GPU_INDEX")
if _gpu is not None:
    os.environ["CUDA_VISIBLE_DEVICES"] = _gpu

import cv2
import torch
import torchvision.transforms.functional as _tvf

sys.modules["torchvision.transforms.functional_tensor"] = _tvf

from basicsr.utils import img2tensor, imwrite, tensor2img
from codeformer.app import codeformer_net, device, upsampler
from codeformer.facelib.utils.face_restoration_helper import FaceRestoreHelper
from torchvision.transforms.functional import normalize

# hqdn3d strips compression grain; unsharp makes the character edges pop without
# ringing. Tuned mild so the next scene's I2V doesn't inherit halos.
_DEGRAIN_VF = "hqdn3d=4:3:6:4,unsharp=5:5:0.8:5:5:0.0"


def degrain(src: Path, dst: Path) -> None:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src),
                    "-vf", _DEGRAIN_VF, str(dst)], check=True)


def relock_face(src: Path, dst: Path, fidelity: float) -> None:
    """CodeFormer face restore on a single frame, pasted back at source size."""
    helper = FaceRestoreHelper(2, face_size=512, crop_ratio=(1, 1),
                               det_model="retinaface_resnet50", save_ext="png",
                               use_parse=True, device=device)
    img = cv2.imread(str(src), cv2.IMREAD_COLOR)
    h, w = img.shape[:2]
    helper.read_image(img)
    helper.get_face_landmarks_5(only_center_face=False, resize=640, eye_dist_threshold=5)
    helper.align_warp_face()
    for face in helper.cropped_faces:
        t = img2tensor(face / 255.0, bgr2rgb=True, float32=True)
        normalize(t, (0.5, 0.5, 0.5), (0.5, 0.5, 0.5), inplace=True)
        t = t.unsqueeze(0).to(device)
        with torch.no_grad():
            out_t = codeformer_net(t, w=fidelity, adain=True)[0]
        helper.add_restored_face(tensor2img(out_t, rgb2bgr=True, min_max=(-1, 1)).astype("uint8"))
    bg = upsampler.enhance(img, outscale=2)[0]
    helper.get_inverse_affine(None)
    result = helper.paste_faces_to_input_image(upsample_img=bg, draw_box=False,
                                               face_upsampler=upsampler)
    # 2x internal upscale → back to source size so the seed dims are unchanged.
    imwrite(cv2.resize(result, (w, h), interpolation=cv2.INTER_LANCZOS4), str(dst))


def main() -> int:
    if len(sys.argv) != 4:
        print("usage: clean_seed_frame.py <in.png> <out.png> <fidelity 0-1>")
        return 2
    src, out, fidelity = Path(sys.argv[1]), Path(sys.argv[2]), float(sys.argv[3])
    if not src.exists():
        print(f"ERROR: missing {src}", file=sys.stderr)
        return 1
    tmp = out.with_name(out.stem + ".degrain.png")
    degrain(src, tmp)
    try:
        relock_face(tmp, out, fidelity)
    except Exception as exc:  # face detect/restore failed → keep the degrained frame
        print(f"face-relock skipped ({exc}) — degrain only", file=sys.stderr)
        shutil.copy(tmp, out)
    finally:
        if tmp.exists() and tmp != out:
            tmp.unlink()
    print(f"cleaned seed → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
