#!/usr/bin/env python3
"""One-shot smoke test for Wan 2.2 TI2V-5B: load + tiny gen."""
import os, time, sys
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
import torch
from diffusers import WanPipeline
from diffusers.utils import export_to_video

MODEL = "/home/akash/Wan2.2-Models/TI2V-5B-Diffusers"
OUT = "/home/akash/PycharmProjects/video-app/docs/runs/wan22-eval/_smoke.mp4"

t = time.time()
print(f"[{time.strftime('%H:%M:%S')}] load pipeline (bf16, model cpu offload)")
pipe = WanPipeline.from_pretrained(MODEL, torch_dtype=torch.bfloat16)
pipe.enable_model_cpu_offload()
print(f"  pipeline ready in {time.time()-t:.1f}s")

t = time.time()
print(f"[{time.strftime('%H:%M:%S')}] generating 21 frames @ 416x256, 20 steps")
gen = torch.Generator(device="cuda").manual_seed(0)
out = pipe(
    prompt="A red apple rolling on a wooden table, soft natural light",
    negative_prompt="blurry, low quality, distorted",
    height=256, width=416, num_frames=21,
    num_inference_steps=20, guidance_scale=5.0,
    generator=gen,
)
export_to_video(out.frames[0], OUT, fps=24)
print(f"  gen ok in {time.time()-t:.1f}s -> {OUT}")
print(f"GPU peak: {torch.cuda.max_memory_allocated()/1e9:.2f} GB")
