#!/usr/bin/env python3
"""30-second continuity chain on top of test_character_with_bag.py output.

5 clips × 145 frames @ 24fps = 5 × 6.04s ≈ 30.2s.
Each clip at 100 inference steps, vanilla Wan22 TI2V-5B I2V.
Clip 0 canvas = composite.png (model+bag composite from earlier).
Clip N canvas = last frame of clip N-1.

Usage:
    /home/akash/.pyenv/versions/video-app/bin/python scripts/test_character_continuity.py
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

PY = "/home/akash/.pyenv/versions/video-app/bin/python"
WAN = "/home/akash/PycharmProjects/video-app/wan22_generate.py"
OUT = Path("/tmp/test_bag")
COMPOSITE = OUT / "composite.png"

if not COMPOSITE.is_file():
    sys.exit(f"missing canvas: {COMPOSITE} — run test_character_with_bag.py first")

W, H = 832, 480
NUM_FRAMES = 145
STEPS = 100

CLIPS = [
    {
        "name": "c00_intro_walk",
        "prompt": (
            "A tall slim woman in her late 20s, cream silk blouse and black trousers, "
            "low chignon, walks slowly toward camera holding a tan Hermes Birkin "
            "handbag with gold hardware in her right hand at hip level. Minimal grey "
            "studio. Confident neutral expression. Slow dolly back. Cinematic fashion editorial."
        ),
    },
    {
        "name": "c01_continue_walk",
        "prompt": (
            "The same tall slim woman in cream silk blouse and black trousers continues "
            "walking toward camera, the tan Hermes Birkin handbag still in her right hand "
            "at hip level, gold hardware catching the light. Subtle hip sway. Minimal grey "
            "studio. Slow camera dolly back. Refined fashion editorial."
        ),
    },
    {
        "name": "c02_turn_display",
        "prompt": (
            "The same tall slim woman stops walking, turns slightly to a three-quarter pose "
            "and raises the tan Hermes Birkin handbag to chest level to display it. The bag "
            "in clear focus showing its structured shape, top handles, padlock and clochette, "
            "and gold hardware. Slight camera push-in. Minimal grey studio. Refined elegance."
        ),
    },
    {
        "name": "c03_lower_pose",
        "prompt": (
            "The same tall slim woman holds her pose, slowly lowers the tan Hermes Birkin "
            "handbag back to hip level, keeping a serene confident expression. The bag stays "
            "tan with gold hardware. Minimal grey studio. Static camera. Cinematic editorial."
        ),
    },
    {
        "name": "c04_walk_off",
        "prompt": (
            "The same tall slim woman in cream silk blouse and black trousers turns and "
            "walks past the camera toward the right, the tan Hermes Birkin handbag visible "
            "at her side throughout. Minimal grey studio. Confident exit. Cinematic fashion editorial."
        ),
    },
]

NEG = (
    "blurry face, distorted face, deformed body, extra limbs, missing limbs, "
    "warped bag, melted bag, bag changes color, bag disappears, text artifacts, "
    "low resolution, jpeg artifacts"
)


def run(cmd: list[str], label: str) -> None:
    print(f"\n=== {label} ===", flush=True)
    res = subprocess.run(cmd)
    if res.returncode != 0:
        sys.exit(f"FAIL: {label} exited {res.returncode}")


def extract_last_frame(video: Path, out_png: Path) -> Path:
    subprocess.run(
        ["ffmpeg", "-y", "-sseof", "-0.5", "-i", str(video),
         "-vsync", "vfr", "-q:v", "2", "-update", "1", str(out_png)],
        check=True, capture_output=True,
    )
    return out_png


def gen_clip(canvas: Path, prompt: str, out_mp4: Path) -> Path:
    run([
        PY, WAN,
        "--prompt", prompt,
        "--negative-prompt", NEG,
        "--output", str(out_mp4),
        "--condition-image", str(canvas),
        "--width", str(W), "--height", str(H),
        "--num-frames", str(NUM_FRAMES),
        "--num-inference-steps", str(STEPS),
        "--guidance-scale", "5.5",
        "--fps", "24",
        "--seed", "1234",
    ], f"Wan I2V → {out_mp4.name} ({STEPS} steps, {NUM_FRAMES}f)")
    return out_mp4


def concat(clip_paths: list[Path], out_mp4: Path) -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        for cp in clip_paths:
            f.write(f"file '{cp.resolve()}'\n")
        list_file = f.name
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_file,
         "-c", "copy", str(out_mp4)],
        check=True, capture_output=True,
    )
    Path(list_file).unlink()


def main() -> None:
    clip_paths: list[Path] = []
    current_canvas = COMPOSITE

    for i, spec in enumerate(CLIPS):
        out_mp4 = OUT / f"{spec['name']}.mp4"
        gen_clip(current_canvas, spec["prompt"], out_mp4)
        clip_paths.append(out_mp4)
        current_canvas = OUT / f"lastframe_{i:02d}.png"
        extract_last_frame(out_mp4, current_canvas)
        print(f"  → last frame extracted: {current_canvas.name}", flush=True)

    final = OUT / "continuity_30s.mp4"
    concat(clip_paths, final)
    print(f"\n=== DONE ===", flush=True)
    print(f"clips: {[p.name for p in clip_paths]}", flush=True)
    print(f"final: {final}", flush=True)


if __name__ == "__main__":
    main()
