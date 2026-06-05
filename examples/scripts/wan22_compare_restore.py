#!/usr/bin/env python3
"""Side-by-side before/after comparison for face-restored wan22 videos."""
from __future__ import annotations

import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

EVAL_DIR = Path("/home/akash/PycharmProjects/video-app/docs/runs/wan22-eval")
RESTORED = EVAL_DIR / "restored"
OUT_DIR = EVAL_DIR / "frames"

TIMESTAMPS = [1.0, 3.0, 5.0, 7.0, 9.0]
W, H = 320, 180


def extract_strip(video: Path, out: Path):
    if out.exists():
        return
    sel = "+".join(f"between(t,{t-0.04},{t+0.04})" for t in TIMESTAMPS)
    vf = f"select='{sel}',scale={W}:{H},tile={len(TIMESTAMPS)}x1"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(video),
                    "-vf", vf, "-frames:v", "1", "-q:v", "2", str(out)], check=True)


def make_compare(tag: str, original: Path, restored: Path) -> Path:
    o_strip = OUT_DIR / f"{tag}__orig_strip.jpg"
    r_strip = OUT_DIR / f"{tag}__gfpgan_strip.jpg"
    extract_strip(original, o_strip)
    extract_strip(restored, r_strip)
    LABEL_W = 100
    HEADER_H = 30
    o = Image.open(o_strip); r = Image.open(r_strip)
    W_total = LABEL_W + o.width
    grid = Image.new("RGB", (W_total, HEADER_H + 2 * H), "black")
    draw = ImageDraw.Draw(grid)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 16)
    except Exception:
        font = ImageFont.load_default()
    col_w = o.width // len(TIMESTAMPS)
    for i, t in enumerate(TIMESTAMPS):
        draw.text((LABEL_W + i * col_w + col_w // 2 - 12, 5),
                  f"{int(t)}s", fill="white", font=font)
    grid.paste(o, (LABEL_W, HEADER_H))
    grid.paste(r, (LABEL_W, HEADER_H + H))
    draw.text((8, HEADER_H + H // 2 - 10), "original", fill="white", font=font)
    draw.text((8, HEADER_H + H + H // 2 - 10), "GFPGAN", fill="lime", font=font)
    out = OUT_DIR / f"{tag}__face_restore_compare.jpg"
    grid.save(out, quality=88)
    return out


def main():
    cases = [
        ("c_runner__none",
         EVAL_DIR / "continuity" / "c_runner__none__w0.0.mp4",
         RESTORED / "c_runner__none__w0.0__gfpgan.mp4"),
        ("c_coffee__none",
         EVAL_DIR / "continuity" / "c_coffee__none__w0.0.mp4",
         RESTORED / "c_coffee__none__w0.0__gfpgan.mp4"),
    ]
    for tag, o, r in cases:
        out = make_compare(tag, o, r)
        print(f"  compare -> {out.name}")


if __name__ == "__main__":
    main()
