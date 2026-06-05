#!/usr/bin/env python3
"""One full-settings generation to measure actual per-cell time."""
import os, time, sys
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
import torch
from diffusers import WanPipeline
from diffusers.utils import export_to_video

MODEL = "/home/akash/Wan2.2-Models/TI2V-5B-Diffusers"
OUT = "/home/akash/PycharmProjects/video-app/docs/runs/wan22-eval/_time1.mp4"

t = time.time()
pipe = WanPipeline.from_pretrained(MODEL, torch_dtype=torch.bfloat16)
pipe.enable_model_cpu_offload()
print(f"load {time.time()-t:.1f}s")

t = time.time()
gen = torch.Generator(device="cuda").manual_seed(1234)
out = pipe(
    prompt="A glass perfume bottle on a polished wooden table, soft window light from the left, warm afternoon glow, cinematic",
    negative_prompt="blurry, low quality, distorted, oversaturated, watermark, text, logo, deformed hands, extra limbs",
    height=480, width=832, num_frames=121,
    num_inference_steps=25, guidance_scale=5.0,
    generator=gen,
)
elapsed = time.time() - t
export_to_video(out.frames[0], OUT, fps=24)
print(f"gen {elapsed:.1f}s  ({elapsed/60:.1f} min)")
print(f"GPU peak: {torch.cuda.max_memory_allocated()/1e9:.2f} GB")
print(f"out: {OUT}")
