#!/usr/bin/env python3
"""Extend an existing 2-clip continuity with a LoRA to 3 clips."""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

import torch
from PIL import Image
from diffusers import WanImageToVideoPipeline
from diffusers.utils import export_to_video

MODEL_DIR = "/home/akash/Wan2.2-Models/TI2V-5B-Diffusers"
LORA_DIR = Path("/home/akash/Wan2.2-Models/loras/5b")
CONT_DIR = Path("/home/akash/PycharmProjects/video-app/docs/runs/wan22-eval/continuity")

FPS, NUM_FRAMES, HEIGHT, WIDTH = 24, 121, 480, 832
STEPS, GUIDANCE, SEED = 40, 5.0, 1234
NEG = "blurry, low quality, distorted, oversaturated, watermark, text, logo, deformed hands, extra limbs"
PROMPT = ("A man in athletic gear running through a tree-lined park at golden hour, "
          "side view, full body visible, dynamic stride, autumn leaves on the ground, "
          "shallow depth of field, cinematic")

LORAS = {
    "crush_it":      LORA_DIR / "crush_it_5b.safetensors",
    "hstoric_color": LORA_DIR / "hstoric_color_5b.safetensors",
    "zackdfilms":    LORA_DIR / "zackdfilms_5b_fixed.safetensors",
}


def extract_last(mp4: Path, png: Path):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-sseof", "-0.1",
                    "-i", str(mp4), "-vframes", "1", str(png)], check=True)


def concat(clips, out):
    listf = out.with_suffix(".txt")
    listf.write_text("\n".join(f"file '{c.absolute()}'" for c in clips))
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                    "-i", str(listf), "-c", "copy", str(out)], check=True)
    listf.unlink()


def main():
    if len(sys.argv) != 3:
        print("usage: wan22_continuity_3clip_lora.py <lora_id> <weight>")
        sys.exit(2)
    lora_id, weight = sys.argv[1], float(sys.argv[2])
    assert lora_id in LORAS, f"unknown lora: {lora_id}"

    tag = f"c_runner__{lora_id}__w{weight}"
    work = CONT_DIR / "work" / tag
    clip1, clip2 = work / "clip_1.mp4", work / "clip_2.mp4"
    assert clip1.exists() and clip2.exists(), f"missing prior clips in {work}"
    out = CONT_DIR / f"{tag}__3clip.mp4"

    last2 = work / "frame_last_2.png"
    extract_last(clip2, last2)
    print(f"[{time.strftime('%H:%M:%S')}] last2 -> {last2.name}")

    print(f"[{time.strftime('%H:%M:%S')}] loading I2V pipeline + {lora_id}@{weight}")
    pipe = WanImageToVideoPipeline.from_pretrained(MODEL_DIR, torch_dtype=torch.bfloat16)
    pipe.enable_model_cpu_offload()
    pipe.load_lora_weights(str(LORAS[lora_id]), adapter_name=lora_id)
    pipe.set_adapters([lora_id], adapter_weights=[weight])

    image = Image.open(last2).convert("RGB").resize((WIDTH, HEIGHT))
    gen = torch.Generator(device="cuda").manual_seed(SEED)
    t0 = time.time()
    print(f"[{time.strftime('%H:%M:%S')}] generating clip_3")
    res = pipe(image=image, prompt=PROMPT, negative_prompt=NEG,
               height=HEIGHT, width=WIDTH, num_frames=NUM_FRAMES,
               num_inference_steps=STEPS, guidance_scale=GUIDANCE, generator=gen)
    clip3 = work / "clip_3.mp4"
    export_to_video(res.frames[0], str(clip3), fps=FPS)
    print(f"[{time.strftime('%H:%M:%S')}] clip_3 done in {time.time()-t0:.1f}s")

    concat([clip1, clip2, clip3], out)
    print(f"3-clip -> {out}")


if __name__ == "__main__":
    main()
