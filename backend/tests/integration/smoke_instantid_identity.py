"""Smoke test: same character → multiple action poses via InstantID.

Drives ~/instantid/generate_instantid.py three times with the same
portrait but different action prompts. Output goes to
storage/smoke_instantid/. Compare each output to the input portrait —
the FACE should read as the same person across all three.
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import sys
from pathlib import Path

GPU_PYTHON = "/home/akash/.pyenv/versions/video-app/bin/python"
INSTANTID_SCRIPT = Path.home() / "instantid" / "generate_instantid.py"

OUT_DIR = Path(__file__).parent / "storage" / "smoke_instantid"
PORTRAIT = (
    Path(__file__).parent / "storage" / "smoke_img2img" / "01_character.png"
)

ACTIONS = [
    (
        "running",
        "Full-body portrait, head to toe in frame, both feet visible. "
        "Mid-stride run, side profile, both feet off ground in athletic gait. "
        "A man in his early 30s wearing a charcoal grey performance tee and "
        "dark technical shorts and white athletic trainers. Plain neutral "
        "studio backdrop, soft even lighting, sharp focus.",
    ),
    (
        "sitting_lacing",
        "Full-body portrait, head to toe in frame, both feet visible. Seated "
        "low on a stoop, leaning forward, both hands tying the laces of one "
        "trainer. A man in his early 30s wearing a charcoal grey performance "
        "tee and dark technical shorts and white athletic trainers. Plain "
        "neutral studio backdrop, soft even lighting, sharp focus.",
    ),
    (
        "jumping",
        "Full-body portrait, head to toe in frame, both feet visible. Mid-air "
        "jump in full extension, arms raised, knees slightly bent, side "
        "profile. A man in his early 30s wearing a charcoal grey performance "
        "tee and dark technical shorts and white athletic trainers. Plain "
        "neutral studio backdrop, soft even lighting, sharp focus.",
    ),
]
NEG = (
    "cropped feet, cropped legs, head-and-shoulders, bust shot, close-up, "
    "macro, partial body, lowres, low quality, worst quality, text, watermark, "
    "logo, painting, drawing, illustration, glitch, deformed, mutated, "
    "cross-eyed, ugly, disfigured"
)


def run_one(prompt: str, output_path: Path, seed: int) -> None:
    cmd = [
        GPU_PYTHON, str(INSTANTID_SCRIPT),
        "--prompt", prompt,
        "--negative", NEG,
        "--out", str(output_path),
        "--portrait", str(PORTRAIT),
        "--width", "768", "--height", "1024",
        "--steps", "30", "--guidance", "5.0",
        "--id-strength", "0.85",
        "--seed", str(seed),
    ]
    print(f"\n→ Running InstantID for {output_path.name} (seed={seed})")
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        print("STDERR:", proc.stderr[-2000:])
        raise RuntimeError(f"InstantID failed for {output_path.name}")
    print(proc.stdout[-400:])


def main() -> None:
    if not PORTRAIT.exists():
        sys.exit(f"Portrait missing: {PORTRAIT}. Run test_img2img_product.py first.")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(PORTRAIT, OUT_DIR / "00_input_portrait.png")
    print(f"Input portrait: {PORTRAIT}")
    print(f"Output dir    : {OUT_DIR}")

    for i, (label, prompt) in enumerate(ACTIONS):
        out = OUT_DIR / f"0{i+1}_{label}.png"
        run_one(prompt, out, seed=200 + i)

    print("\nOutputs:")
    for f in sorted(OUT_DIR.iterdir()):
        size_kb = f.stat().st_size // 1024
        print(f"  {f.name}  ({size_kb} KB)")


if __name__ == "__main__":
    main()
