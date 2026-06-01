#!/usr/bin/env python3
"""Generate the c_runner scene at 1280x720 to test face-from-afar recoverability."""
from __future__ import annotations

import os
import time
from pathlib import Path

os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

import torch
from diffusers import WanPipeline
from diffusers.utils import export_to_video

MODEL_DIR = "/home/akash/Wan2.2-Models/TI2V-5B-Diffusers"
OUT = Path("/home/akash/PycharmProjects/video-app/docs/runs/wan22-eval/restored/c_runner__none__576p.mp4")
OUT.parent.mkdir(parents=True, exist_ok=True)

FPS, NUM_FRAMES = 24, 121
HEIGHT, WIDTH = 576, 1024
STEPS, GUIDANCE, SEED = 40, 5.0, 1234
NEG = "blurry, low quality, distorted, oversaturated, watermark, text, logo, deformed hands, extra limbs"
PROMPT = ("A man in athletic gear running through a tree-lined park at golden hour, "
          "side view, full body visible, dynamic stride, autumn leaves on the ground, "
          "shallow depth of field, cinematic")


def main():
    if OUT.exists():
        print(f"already exists: {OUT}")
        return
    print(f"[{time.strftime('%H:%M:%S')}] loading WanPipeline (bf16 + offload)")
    pipe = WanPipeline.from_pretrained(MODEL_DIR, torch_dtype=torch.bfloat16)
    pipe.enable_model_cpu_offload()
    gen = torch.Generator(device="cuda").manual_seed(SEED)
    t0 = time.time()
    print(f"[{time.strftime('%H:%M:%S')}] generate {WIDTH}x{HEIGHT} {NUM_FRAMES}f @ {STEPS} steps")
    out = pipe(prompt=PROMPT, negative_prompt=NEG,
               height=HEIGHT, width=WIDTH, num_frames=NUM_FRAMES,
               num_inference_steps=STEPS, guidance_scale=GUIDANCE, generator=gen)
    export_to_video(out.frames[0], str(OUT), fps=FPS)
    print(f"[{time.strftime('%H:%M:%S')}] done in {time.time()-t0:.1f}s -> {OUT}")


if __name__ == "__main__":
    main()
