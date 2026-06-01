#!/usr/bin/env python3
"""Build per-video frame strips + per-prompt comparison grids for wan22-eval."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

EVAL_DIR = Path("/home/akash/PycharmProjects/video-app/docs/runs/wan22-eval")
FRAMES_DIR = EVAL_DIR / "frames"
FRAMES_DIR.mkdir(parents=True, exist_ok=True)

# Per-video strip: 5 frames at 1s,2s,3s,4s,5s, scaled to 256x144 (16:9), side-by-side
STRIP_W, STRIP_H = 256, 144   # per frame
TIMESTAMPS = [1.0, 2.0, 3.0, 4.0, 5.0]

PROMPTS = ["p1_runner", "p2_coffee", "p3_purse", "p4_chef", "p5_dancer", "p6_crowd", "p7_war"]

# Determined dynamically from filenames present on disk
def cells_for_prompt(prompt_id: str) -> list[str]:
    """Return cell labels (lora__weight) found for this prompt, ordered."""
    pat = f"{prompt_id}__*__w*.mp4"
    files = sorted(EVAL_DIR.glob(pat))
    cells = []
    for f in files:
        # p1_runner__hstoric_color__w0.5.mp4 → "hstoric_color__w0.5"
        parts = f.stem.split("__")
        if len(parts) == 3:
            cells.append(f"{parts[1]}__{parts[2]}")
    # Order: none first, then by lora name then weight
    cells.sort(key=lambda c: (0 if c.startswith("none") else 1, c))
    return cells


def extract_strip(video_path: Path, out_jpg: Path) -> bool:
    """Extract 5 frames via ffmpeg + tile into one horizontal strip."""
    if out_jpg.exists():
        return True
    # Build select expr: eq(t,1)+eq(t,2)+...
    select = "+".join(f"between(t,{t-0.04},{t+0.04})" for t in TIMESTAMPS)
    vf = f"select='{select}',scale={STRIP_W}:{STRIP_H},tile=5x1"
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(video_path),
           "-vf", vf, "-frames:v", "1", "-q:v", "3", str(out_jpg)]
    try:
        subprocess.run(cmd, check=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"  ffmpeg fail: {video_path.name}  {e}")
        return False


def make_prompt_grid(prompt_id: str, cells: list[str]) -> Path:
    """Stack per-cell strips vertically with label gutter on the left."""
    LABEL_W = 180
    rows = []
    for cell in cells:
        strip_path = FRAMES_DIR / f"{prompt_id}__{cell}__strip.jpg"
        if not strip_path.exists():
            continue
        strip = Image.open(strip_path)
        # Add label gutter on the left
        row = Image.new("RGB", (LABEL_W + strip.width, strip.height), "black")
        row.paste(strip, (LABEL_W, 0))
        draw = ImageDraw.Draw(row)
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 16)
        except Exception:
            font = ImageFont.load_default()
        draw.text((10, strip.height // 2 - 10), cell, fill="white", font=font)
        rows.append(row)
    if not rows:
        return None
    W = rows[0].width
    H_per = rows[0].height
    HEADER_H = 30
    grid = Image.new("RGB", (W, HEADER_H + len(rows) * H_per), "black")
    draw = ImageDraw.Draw(grid)
    try:
        font_h = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 18)
    except Exception:
        font_h = ImageFont.load_default()
    # Column headers: 1s 2s 3s 4s 5s
    col_w = (W - 180) // 5
    for i, t in enumerate(TIMESTAMPS):
        draw.text((180 + i * col_w + col_w // 2 - 15, 5), f"{int(t)}s", fill="white", font=font_h)
    for i, row in enumerate(rows):
        grid.paste(row, (0, HEADER_H + i * H_per))
    out = FRAMES_DIR / f"{prompt_id}__grid.jpg"
    grid.save(out, quality=85)
    return out


def main():
    # 1. extract strips for every mp4 currently present
    mp4s = sorted(EVAL_DIR.glob("p*__*__w*.mp4"))
    print(f"found {len(mp4s)} mp4s")
    for mp4 in mp4s:
        out = FRAMES_DIR / (mp4.stem + "__strip.jpg")
        extract_strip(mp4, out)
    # 2. per-prompt grids
    for prompt in PROMPTS:
        cells = cells_for_prompt(prompt)
        if not cells:
            continue
        out = make_prompt_grid(prompt, cells)
        if out:
            print(f"  grid -> {out.name}  ({len(cells)} cells)")


if __name__ == "__main__":
    main()
