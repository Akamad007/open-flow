"""Isolate which GPU stage fails for the video pipeline.

Runs each subprocess (SD3.5 portrait → InstantID dual-CN → LTX-Video) one
at a time with a known good seed input. Each step is independent — if
InstantID OOMs but SD3.5 worked, we know the GPU pinning is wrong, not
the pipeline plumbing. If LTX OOMs after InstantID succeeded, we know the
balanced multi-GPU dispatch isn't kicking in.

Usage:
    python backend/test_pipeline_isolated.py [--skip-portrait] [--skip-still] [--skip-video]
"""

from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

OUT_DIR = ROOT / "storage" / "smoke_pipeline"
OUT_DIR.mkdir(parents=True, exist_ok=True)

PORTRAIT_PATH = OUT_DIR / "01_portrait.png"
POSE_REF_PATH = ROOT / "storage" / "pose_library" / "kneeling_one_knee.png"
ACTION_STILL_PATH = OUT_DIR / "02_action.png"
VIDEO_PATH = OUT_DIR / "03_video.mp4"

PORTRAIT_PROMPT = (
    "full-body portrait head to toe in frame, both feet visible on the ground, "
    "neutral standing pose, three-quarter front view, full body shot, "
    "wide framing with headroom above and floor below the feet, "
    "athletic young man, short dark brown hair, charcoal grey performance "
    "tee, dark technical shorts, white athletic trainers, plain neutral "
    "studio backdrop, soft even lighting, sharp focus, photorealistic"
)
PORTRAIT_NEG = (
    "bust shot, head-and-shoulders, waist-up, half body, torso shot, "
    "close-up, cropped feet, cropped legs, blurry, ugly, watermark"
)

ACTION_PROMPT = (
    "full-body, head to toe, both feet visible. The athletic young man, "
    "wearing a charcoal performance tee and dark shorts, kneels on parched "
    "cracked earth. Plain neutral studio backdrop, soft even lighting, "
    "sharp focus, photorealistic"
)


def _gpu_status() -> str:
    out = subprocess.run(
        ["nvidia-smi", "--query-gpu=index,name,memory.used,memory.total",
         "--format=csv,noheader"],
        capture_output=True, text=True, timeout=5,
    )
    return out.stdout.strip()


def step1_portrait() -> bool:
    """SD 3.5 portrait — single-GPU subprocess, should work on either GPU."""
    print("\n" + "="*70)
    print("STEP 1 — SD 3.5 portrait (single-GPU)")
    print("="*70)
    print(f"GPU before:\n  {_gpu_status().replace(chr(10), chr(10)+'  ')}")
    if PORTRAIT_PATH.exists():
        PORTRAIT_PATH.unlink()
    sd35 = Path.home() / "sd35-medium" / "generate_sd35.py"
    cmd = [
        sys.executable, str(sd35),
        "--prompt", PORTRAIT_PROMPT, "--negative", PORTRAIT_NEG,
        "--out", str(PORTRAIT_PATH),
        "--width", "768", "--height", "1280",
        "--steps", "40", "--guidance", "7.5", "--seed", "42",
    ]
    env = {**os.environ, "PYTORCH_CUDA_ALLOC_CONF": "expandable_segments:True",
           "CUDA_DEVICE_ORDER": "PCI_BUS_ID"}
    t0 = time.time()
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=300)
    elapsed = time.time() - t0
    print(f"\nRC={proc.returncode}  elapsed={elapsed:.1f}s  output exists={PORTRAIT_PATH.exists()}")
    if proc.returncode != 0:
        print(f"\nSTDERR:\n{proc.stderr[-1500:]}")
        return False
    print(f"OK → {PORTRAIT_PATH}")
    return True


def step2_action_still() -> bool:
    """InstantID dual-CN — currently pinned to cuda:1 (4070 Ti, 12 GB) by
    pin_image_gen_env. This is where we've been OOM'ing."""
    print("\n" + "="*70)
    print("STEP 2 — InstantID dual-CN action still (single-GPU subprocess)")
    print("="*70)
    print(f"GPU before:\n  {_gpu_status().replace(chr(10), chr(10)+'  ')}")
    if not PORTRAIT_PATH.exists():
        print(f"FAIL: portrait missing — run step1 first")
        return False
    if not POSE_REF_PATH.exists():
        print(f"FAIL: pose-library kneeling_one_knee.png missing at {POSE_REF_PATH}")
        return False
    if ACTION_STILL_PATH.exists():
        ACTION_STILL_PATH.unlink()
    instantid_pose = Path.home() / "instantid" / "generate_instantid_pose.py"
    cmd = [
        sys.executable, str(instantid_pose),
        "--prompt", ACTION_PROMPT, "--negative", PORTRAIT_NEG,
        "--out", str(ACTION_STILL_PATH),
        "--portrait", str(PORTRAIT_PATH),
        "--pose-image", str(POSE_REF_PATH),
        "--width", "768", "--height", "1280",
        "--steps", "40", "--guidance", "5.0",
        "--id-strength", "0.80", "--pose-strength", "0.65",
        "--seed", "42",
    ]
    env = {**os.environ, "PYTORCH_CUDA_ALLOC_CONF": "expandable_segments:True",
           "CUDA_DEVICE_ORDER": "PCI_BUS_ID"}
    # Mirror prod's pin_image_gen_env: this is what currently OOMs.
    env.setdefault("CUDA_VISIBLE_DEVICES", os.environ.get("CUDA_VISIBLE_DEVICES", "1"))
    print(f"CUDA_VISIBLE_DEVICES={env.get('CUDA_VISIBLE_DEVICES')!r}")
    t0 = time.time()
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=600)
    elapsed = time.time() - t0
    print(f"\nRC={proc.returncode}  elapsed={elapsed:.1f}s  output exists={ACTION_STILL_PATH.exists()}")
    if proc.returncode != 0:
        print(f"\nSTDERR:\n{proc.stderr[-2000:]}")
        return False
    print(f"OK → {ACTION_STILL_PATH}")
    return True


def step3_video() -> bool:
    """LTX-Video — multi-GPU via balanced dispatch. Should split layers
    across BOTH GPUs (RTX 5070 Ti 16 GB + RTX 4070 Ti 12 GB)."""
    print("\n" + "="*70)
    print("STEP 3 — LTX-Video (multi-GPU balanced dispatch)")
    print("="*70)
    print(f"GPU before:\n  {_gpu_status().replace(chr(10), chr(10)+'  ')}")
    if not ACTION_STILL_PATH.exists():
        print(f"FAIL: action still missing — run step2 first")
        return False
    if VIDEO_PATH.exists():
        VIDEO_PATH.unlink()
    ltx = ROOT.parent / "ltx_generate.py"
    cmd = [
        sys.executable, str(ltx),
        "--prompt", "A cinematic shot of an athletic young man kneeling on parched cracked earth.",
        "--negative-prompt", "blurry, watermark, text, deformed",
        "--output", str(VIDEO_PATH),
        "--model", "Lightricks/LTX-Video",
        "--model-file", "ltxv-13b-0.9.8-dev-fp8.safetensors",
        "--device", "cuda",
        "--height", "480", "--width", "704",
        "--num-frames", "73", "--fps", "12",
        "--num-inference-steps", "20",  # short for smoke
        "--guidance-scale", "3.5", "--seed", "42",
        "--character-image", str(PORTRAIT_PATH),
        "--scene-action-images", str(ACTION_STILL_PATH),
    ]
    env = {**os.environ, "PYTORCH_CUDA_ALLOC_CONF": "expandable_segments:True",
           "CUDA_DEVICE_ORDER": "PCI_BUS_ID"}
    # Pin to the 16 GB 5070 Ti (cuda:0 under PCI_BUS_ID order). Multi-GPU
    # dispatch keeps OOM'ing because LoRA fusion upcasts the FP8 weights
    # back to bf16, blowing past the 16 GiB transformer budget across
    # both GPUs. Single-GPU FP8 layerwise + sequential CPU offload is the
    # proven path on a 16 GB card.
    env["CUDA_VISIBLE_DEVICES"] = "0"
    t0 = time.time()
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=1800)
    elapsed = time.time() - t0
    print(f"\nRC={proc.returncode}  elapsed={elapsed:.1f}s  output exists={VIDEO_PATH.exists()}")
    if proc.returncode != 0:
        print(f"\nSTDERR (last 3000 chars):\n{proc.stderr[-3000:]}")
        print(f"\nSTDOUT (last 1500 chars — look for 'Balanced dispatch' or 'Single GPU'):\n{proc.stdout[-1500:]}")
        return False
    print(f"\nSTDOUT (last 1500 chars):\n{proc.stdout[-1500:]}")
    print(f"OK → {VIDEO_PATH}")
    return True


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--skip-portrait", action="store_true")
    p.add_argument("--skip-still", action="store_true")
    p.add_argument("--skip-video", action="store_true")
    args = p.parse_args()

    print(f"Output dir: {OUT_DIR}")
    print(f"GPU baseline:\n  {_gpu_status().replace(chr(10), chr(10)+'  ')}")
    results: dict[str, bool] = {}
    if not args.skip_portrait:
        results["portrait"] = step1_portrait()
    if not args.skip_still:
        results["action_still"] = step2_action_still()
    if not args.skip_video:
        results["video"] = step3_video()

    print("\n" + "="*70)
    print("RESULTS")
    print("="*70)
    for stage, ok in results.items():
        marker = "OK  " if ok else "FAIL"
        print(f"  [{marker}] {stage}")
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
