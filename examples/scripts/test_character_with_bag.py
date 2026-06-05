#!/usr/bin/env python3
"""Manual experiment: generate a model + a bag with SD3.5, composite them,
feed the composite to Wan22 I2V, see if Wan can intelligently animate the
character holding the bag.

WARNING: needs the GPU exclusively. Pause celery first OR accept contention
(both processes will fight for VRAM and probably OOM).

Usage:
    /home/akash/.pyenv/versions/video-app/bin/python scripts/test_character_with_bag.py

Output:
    /tmp/test_bag/model.png       — SD3.5 model render
    /tmp/test_bag/bag.png         — SD3.5 bag render
    /tmp/test_bag/composite.png   — naive PIL composite (bag pasted at hand area)
    /tmp/test_bag/final.mp4       — Wan22 I2V output
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PIL import Image

PY = "/home/akash/.pyenv/versions/video-app/bin/python"
SD35 = "/home/akash/sd35-medium/generate_sd35.py"
WAN = "/home/akash/PycharmProjects/video-app/engines/wan22_generate.py"
OUT = Path("/tmp/test_bag")
OUT.mkdir(parents=True, exist_ok=True)

W, H = 832, 480

MODEL_PROMPT = (
    "A tall slim woman in her late 20s, elegant face with sharp cheekbones, "
    "long dark hair pulled back in a low chignon, wearing a tailored cream silk "
    "blouse, fitted high-waisted black trousers, low pointed heels, neutral makeup. "
    "Standing in a soft neutral grey gradient studio with her right arm held slightly "
    "out at hip level (empty hand visible, palm in), full body visible, photorealistic, "
    "soft side key light, fashion editorial."
)

BAG_PROMPT = (
    "Iconic structured Hermes Birkin handbag in tan saddle leather with gold hardware, "
    "padlock and clochette visible, top handles, isolated on plain white background, "
    "product photography, soft even lighting, sharp focus, no shadow, three-quarter angle."
)

WAN_PROMPT = (
    "A tall slim woman in her late 20s, cream silk blouse and black trousers, low chignon, "
    "walks slowly toward camera holding a tan leather Hermes Birkin handbag in her right "
    "hand at hip level. The bag stays tan with gold hardware. Minimal grey studio. "
    "Confident neutral expression. Slow dolly back. Cinematic fashion editorial."
)

WAN_NEG = (
    "blurry face, distorted face, deformed body, extra limbs, missing limbs, "
    "warped bag, melted bag, bag changes color, text artifacts, low resolution"
)


def run(cmd: list[str], label: str) -> None:
    print(f"\n=== {label} ===")
    print(" ".join(str(c) for c in cmd))
    res = subprocess.run(cmd)
    if res.returncode != 0:
        sys.exit(f"FAIL: {label} exited {res.returncode}")


def gen_model() -> Path:
    out = OUT / "model.png"
    if out.exists():
        print(f"reuse {out}")
        return out
    run([
        PY, SD35,
        "--prompt", MODEL_PROMPT,
        "--negative", "blurry, deformed face, malformed body, extra limbs, watermark, text",
        "--out", str(out),
        "--width", str(W), "--height", str(H),
        "--steps", "60", "--guidance", "7.5", "--seed", "1234",
    ], "SD3.5 model")
    return out


def gen_bag() -> Path:
    out = OUT / "bag.png"
    if out.exists():
        print(f"reuse {out}")
        return out
    run([
        PY, SD35,
        "--prompt", BAG_PROMPT,
        "--negative", "blurry, distorted, multiple bags, hands, person, text",
        "--out", str(out),
        "--width", "512", "--height", "512",
        "--steps", "60", "--guidance", "7.5", "--seed", "5678",
    ], "SD3.5 bag")
    return out


def composite(model_path: Path, bag_path: Path) -> Path:
    """Paste bag at the model's right-hand area, scaled to plausible bag size."""
    out = OUT / "composite.png"
    model = Image.open(model_path).convert("RGB")
    bag = Image.open(bag_path).convert("RGBA")

    # Mask out white background of bag → transparency.
    bag_rgba = bag.copy()
    pixels = bag_rgba.load()
    for y in range(bag_rgba.height):
        for x in range(bag_rgba.width):
            r, g, b, _ = pixels[x, y]
            if r > 240 and g > 240 and b > 240:
                pixels[x, y] = (r, g, b, 0)

    # Scale bag to ~25% of frame height (plausible Birkin scale).
    bag_h = int(H * 0.28)
    bag_w = int(bag_rgba.width * bag_h / bag_rgba.height)
    bag_rgba = bag_rgba.resize((bag_w, bag_h), Image.LANCZOS)

    # Position: lower-right quadrant where the model's right hand should be.
    # Tweak these if model pose lands differently.
    pos_x = int(W * 0.62)
    pos_y = int(H * 0.55)
    model_rgba = model.convert("RGBA")
    model_rgba.alpha_composite(bag_rgba, (pos_x, pos_y))
    out_img = model_rgba.convert("RGB")
    out_img.save(out)
    print(f"composite -> {out}")
    return out


def gen_video(composite_path: Path) -> Path:
    out = OUT / "final.mp4"
    run([
        PY, WAN,
        "--prompt", WAN_PROMPT,
        "--negative-prompt", WAN_NEG,
        "--output", str(out),
        "--condition-image", str(composite_path),
        "--width", str(W), "--height", str(H),
        "--num-frames", "121",
        "--num-inference-steps", "60",
        "--guidance-scale", "5.5",
        "--fps", "24",
        "--seed", "1234",
    ], "Wan22 I2V")
    return out


def main() -> None:
    print(f"Output dir: {OUT}")
    model_path = gen_model()
    bag_path = gen_bag()
    composite_path = composite(model_path, bag_path)
    video_path = gen_video(composite_path)
    print(f"\n=== DONE ===")
    print(f"model:     {model_path}")
    print(f"bag:       {bag_path}")
    print(f"composite: {composite_path}")
    print(f"video:     {video_path}")


if __name__ == "__main__":
    main()
