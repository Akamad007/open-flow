#!/usr/bin/env python3
"""Extend an existing 2-clip continuity to 3 clips — measure drift compounding.

Reuses clip_1 + clip_2 from the existing matrix output. Generates clip_3 via I2V
seeded from clip_2's last frame. Concatenates all three.
"""
from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

import torch
from PIL import Image
from diffusers import WanImageToVideoPipeline
from diffusers.utils import export_to_video

MODEL_DIR = "/home/akash/Wan2.2-Models/TI2V-5B-Diffusers"
CONT_DIR = Path("/home/akash/PycharmProjects/video-app/docs/runs/wan22-eval/continuity")
WORK = CONT_DIR / "work" / "c_runner__none__w0.0"
OUT = CONT_DIR / "c_runner__none__w0.0__3clip.mp4"

FPS, NUM_FRAMES, HEIGHT, WIDTH = 24, 121, 480, 832
STEPS, GUIDANCE, SEED = 40, 5.0, 1234
NEG = "blurry, low quality, distorted, oversaturated, watermark, text, logo, deformed hands, extra limbs"
PROMPT = ("A man in athletic gear running through a tree-lined park at golden hour, "
          "side view, full body visible, dynamic stride, autumn leaves on the ground, "
          "shallow depth of field, cinematic")


def extract_last_frame(mp4: Path, png: Path):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-sseof", "-0.1",
                    "-i", str(mp4), "-vframes", "1", str(png)], check=True)


def concat(clips: list[Path], out: Path):
    listf = out.with_suffix(".txt")
    listf.write_text("\n".join(f"file '{c.absolute()}'" for c in clips))
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                    "-i", str(listf), "-c", "copy", str(out)], check=True)
    listf.unlink()


def main():
    clip1, clip2 = WORK / "clip_1.mp4", WORK / "clip_2.mp4"
    assert clip1.exists() and clip2.exists(), f"missing prior clips in {WORK}"

    last2 = WORK / "frame_last_2.png"
    extract_last_frame(clip2, last2)
    print(f"[{time.strftime('%H:%M:%S')}] last frame of clip_2 -> {last2.name}")

    print(f"[{time.strftime('%H:%M:%S')}] loading I2V pipeline")
    pipe = WanImageToVideoPipeline.from_pretrained(MODEL_DIR, torch_dtype=torch.bfloat16)
    pipe.enable_model_cpu_offload()

    image = Image.open(last2).convert("RGB").resize((WIDTH, HEIGHT))
    gen = torch.Generator(device="cuda").manual_seed(SEED)
    t0 = time.time()
    print(f"[{time.strftime('%H:%M:%S')}] generating clip_3 (I2V from clip_2 last frame)")
    out = pipe(image=image, prompt=PROMPT, negative_prompt=NEG,
               height=HEIGHT, width=WIDTH, num_frames=NUM_FRAMES,
               num_inference_steps=STEPS, guidance_scale=GUIDANCE, generator=gen)
    clip3 = WORK / "clip_3.mp4"
    export_to_video(out.frames[0], str(clip3), fps=FPS)
    print(f"[{time.strftime('%H:%M:%S')}] clip_3 done in {time.time()-t0:.1f}s")

    concat([clip1, clip2, clip3], OUT)
    print(f"3-clip continuity -> {OUT}")


if __name__ == "__main__":
    main()
