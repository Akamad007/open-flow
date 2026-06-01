#!/usr/bin/env python3
"""4-row comparison: 480p / 480p+GFPGAN / 576p / 576p+GFPGAN — runner scene face-from-afar test."""
from __future__ import annotations

import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

EVAL = Path("/home/akash/PycharmProjects/video-app/docs/runs/wan22-eval")
FRAMES = EVAL / "frames"

# Sample timestamps inside the first 5 s of each clip
TS = [1.0, 2.5, 3.5, 4.5]
W, H = 384, 216


def strip(video: Path, out: Path):
    if out.exists():
        return
    sel = "+".join(f"between(t,{t-0.04},{t+0.04})" for t in TS)
    vf = f"select='{sel}',scale={W}:{H},tile={len(TS)}x1"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(video),
                    "-vf", vf, "-frames:v", "1", "-q:v", "2", str(out)], check=True)


def main():
    rows = [
        ("480p original",     EVAL / "continuity/c_runner__none__w0.0.mp4"),
        ("480p + GFPGAN",     EVAL / "restored/c_runner__none__w0.0__gfpgan.mp4"),
        ("576p original",     EVAL / "restored/c_runner__none__576p.mp4"),
        ("576p + GFPGAN",     EVAL / "restored/c_runner__none__576p_gfpgan.mp4"),
    ]
    strips = []
    for label, vid in rows:
        out = FRAMES / f"resolutiontest__{label.replace(' ','_').replace('+','plus')}.jpg"
        strip(vid, out)
        strips.append((label, Image.open(out)))

    LABEL_W = 170
    HEADER_H = 32
    grid = Image.new("RGB", (LABEL_W + strips[0][1].width, HEADER_H + len(strips) * H), "black")
    draw = ImageDraw.Draw(grid)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 16)
    except Exception:
        font = ImageFont.load_default()
    col_w = strips[0][1].width // len(TS)
    for i, t in enumerate(TS):
        draw.text((LABEL_W + i * col_w + col_w // 2 - 18, 7), f"{t:.1f}s", fill="white", font=font)
    for i, (label, s) in enumerate(strips):
        grid.paste(s, (LABEL_W, HEADER_H + i * H))
        color = "lime" if "GFPGAN" in label else "white"
        draw.text((8, HEADER_H + i * H + H // 2 - 10), label, fill=color, font=font)
    out = FRAMES / "runner_resolution_compare.jpg"
    grid.save(out, quality=92)
    print(f"  -> {out}")


if __name__ == "__main__":
    main()
