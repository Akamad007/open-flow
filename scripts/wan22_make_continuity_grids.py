#!/usr/bin/env python3
"""Per-scene continuity grids — frames bracketing the clip seam at 5s."""
from __future__ import annotations

import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

EVAL_DIR = Path("/home/akash/PycharmProjects/video-app/docs/runs/wan22-eval")
CONT_DIR = EVAL_DIR / "continuity"
FRAMES_DIR = EVAL_DIR / "frames"

STRIP_W, STRIP_H = 256, 144
# 6 timestamps — pre-seam, seam boundary, post-seam
# Each continuity is 2x 5.04s = ~10.08s total
TIMESTAMPS = [1.0, 3.0, 4.8, 5.2, 7.0, 9.0]
SCENES = ["c_runner", "c_coffee", "c_crowd"]


def extract_strip(video_path: Path, out_jpg: Path):
    if out_jpg.exists():
        return
    select = "+".join(f"between(t,{t-0.04},{t+0.04})" for t in TIMESTAMPS)
    vf = f"select='{select}',scale={STRIP_W}:{STRIP_H},tile={len(TIMESTAMPS)}x1"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(video_path),
         "-vf", vf, "-frames:v", "1", "-q:v", "3", str(out_jpg)],
        check=True)


def make_scene_grid(scene_id: str):
    mp4s = sorted(CONT_DIR.glob(f"{scene_id}__*__w*.mp4"))
    if not mp4s:
        return None
    LABEL_W = 180
    rows = []
    for mp4 in mp4s:
        strip_path = FRAMES_DIR / (mp4.stem + "__cont_strip.jpg")
        extract_strip(mp4, strip_path)
        strip = Image.open(strip_path)
        row = Image.new("RGB", (LABEL_W + strip.width, strip.height), "black")
        row.paste(strip, (LABEL_W, 0))
        draw = ImageDraw.Draw(row)
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 16)
        except Exception:
            font = ImageFont.load_default()
        # Label = "lora__weight" extracted from filename
        parts = mp4.stem.split("__")
        label = f"{parts[1]}__{parts[2]}" if len(parts) == 3 else mp4.stem
        draw.text((10, strip.height // 2 - 10), label, fill="white", font=font)
        # Vertical line at seam boundary (between frames 3 and 4 = pre and post seam)
        seam_x = LABEL_W + 3 * STRIP_W
        draw.line([(seam_x, 0), (seam_x, strip.height)], fill="yellow", width=2)
        rows.append(row)
    W = rows[0].width
    H_per = rows[0].height
    HEADER_H = 30
    grid = Image.new("RGB", (W, HEADER_H + len(rows) * H_per), "black")
    draw = ImageDraw.Draw(grid)
    try:
        font_h = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 16)
    except Exception:
        font_h = ImageFont.load_default()
    headers = ["1s", "3s", "4.8s│seam", "5.2s seam│", "7s", "9s"]
    col_w = (W - 180) // len(TIMESTAMPS)
    for i, h in enumerate(headers):
        draw.text((180 + i * col_w + 5, 5), h, fill="yellow" if "seam" in h else "white", font=font_h)
    for i, row in enumerate(rows):
        grid.paste(row, (0, HEADER_H + i * H_per))
    out = FRAMES_DIR / f"{scene_id}__continuity_grid.jpg"
    grid.save(out, quality=85)
    return out


def main():
    for scene in SCENES:
        out = make_scene_grid(scene)
        if out:
            n = len(list(CONT_DIR.glob(f"{scene}__*__w*.mp4")))
            print(f"  grid -> {out.name}  ({n} cells)")


if __name__ == "__main__":
    main()
