#!/usr/bin/env python3
"""Chain 2-3 5s clips into a continuity sequence.

Clip 1: text-only generation (WanPipeline)
Clip N>1: image-to-video using last frame of clip N-1 (WanImageToVideoPipeline)
Final: ffmpeg concat → continuity_<scene>.mp4

Usage: wan22_continuity.py <scene_id> "<prompt>" <lora_id> <weight> <num_clips>
"""
from __future__ import annotations

import gc
import json
import os
import subprocess
import sys
import time
from pathlib import Path

os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

import torch
from PIL import Image
from diffusers import WanPipeline, WanImageToVideoPipeline
from diffusers.utils import export_to_video

MODEL_DIR = "/home/akash/Wan2.2-Models/TI2V-5B-Diffusers"
LORA_DIR = Path("/home/akash/Wan2.2-Models/loras/5b")
OUT_DIR = Path("/home/akash/PycharmProjects/video-app/docs/runs/wan22-eval/continuity")
OUT_DIR.mkdir(parents=True, exist_ok=True)

FPS, NUM_FRAMES, HEIGHT, WIDTH = 24, 121, 480, 832
STEPS, GUIDANCE, SEED = 40, 5.0, 1234
NEG = "blurry, low quality, distorted, oversaturated, watermark, text, logo, deformed hands, extra limbs"

LORA_FILES = {
    "none": None,
    "hstoric_color": LORA_DIR / "hstoric_color_5b.safetensors",
    "oil_painting":  LORA_DIR / "oil_painting_5b.safetensors",
    "crush_it":      LORA_DIR / "crush_it_5b.safetensors",
    "aether_punch":  LORA_DIR / "aether_punch_5b.safetensors",
    "aether_splash": LORA_DIR / "aether_splash_5b.safetensors",
    "zackdfilms":    LORA_DIR / "zackdfilms_5b_fixed.safetensors",
    "woven_fabric":  LORA_DIR / "woven_fabric_5b.safetensors",
}


def free_cuda():
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache(); torch.cuda.ipc_collect()


def apply_lora(pipe, lora_id: str, weight: float):
    if lora_id == "none" or LORA_FILES[lora_id] is None:
        return
    pipe.load_lora_weights(str(LORA_FILES[lora_id]), adapter_name=lora_id)
    pipe.set_adapters([lora_id], adapter_weights=[weight])


def unload_lora(pipe):
    for fn_name in ("disable_lora", "unload_lora_weights"):
        try:
            fn = getattr(pipe, fn_name, None)
            if callable(fn): fn()
        except Exception:
            pass


def extract_last_frame(mp4_path: Path, out_png: Path):
    """Use ffmpeg to extract the final frame of an mp4."""
    # Get exact duration first, then seek to end-epsilon
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-sseof", "-0.1",
           "-i", str(mp4_path), "-vframes", "1", str(out_png)]
    subprocess.run(cmd, check=True)


def gen_clip_t2v(prompt: str, lora_id: str, weight: float, out_mp4: Path):
    """First clip: text-to-video."""
    pipe = WanPipeline.from_pretrained(MODEL_DIR, torch_dtype=torch.bfloat16)
    pipe.enable_model_cpu_offload()
    apply_lora(pipe, lora_id, weight)
    gen = torch.Generator(device="cuda").manual_seed(SEED)
    out = pipe(prompt=prompt, negative_prompt=NEG, height=HEIGHT, width=WIDTH,
               num_frames=NUM_FRAMES, num_inference_steps=STEPS,
               guidance_scale=GUIDANCE, generator=gen)
    export_to_video(out.frames[0], str(out_mp4), fps=FPS)
    unload_lora(pipe); del pipe; free_cuda()


def gen_clip_i2v(prompt: str, lora_id: str, weight: float,
                 first_frame_png: Path, out_mp4: Path):
    """Subsequent clip: image-to-video, conditioned on previous clip's last frame."""
    pipe = WanImageToVideoPipeline.from_pretrained(MODEL_DIR, torch_dtype=torch.bfloat16)
    pipe.enable_model_cpu_offload()
    apply_lora(pipe, lora_id, weight)
    image = Image.open(first_frame_png).convert("RGB").resize((WIDTH, HEIGHT))
    gen = torch.Generator(device="cuda").manual_seed(SEED)
    out = pipe(image=image, prompt=prompt, negative_prompt=NEG,
               height=HEIGHT, width=WIDTH, num_frames=NUM_FRAMES,
               num_inference_steps=STEPS, guidance_scale=GUIDANCE,
               generator=gen)
    export_to_video(out.frames[0], str(out_mp4), fps=FPS)
    unload_lora(pipe); del pipe; free_cuda()


def concat_clips(clips: list[Path], out_mp4: Path):
    """Concat with ffmpeg concat demuxer."""
    list_file = out_mp4.with_suffix(".txt")
    list_file.write_text("\n".join(f"file '{c.absolute()}'" for c in clips))
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
           "-i", str(list_file), "-c", "copy", str(out_mp4)]
    subprocess.run(cmd, check=True)
    list_file.unlink()


def main():
    if len(sys.argv) != 6:
        print("usage: wan22_continuity.py <scene_id> <prompt> <lora_id> <weight> <num_clips>")
        sys.exit(2)
    scene_id, prompt, lora_id, weight, num_clips = sys.argv[1:]
    weight = float(weight); num_clips = int(num_clips)
    assert lora_id in LORA_FILES, f"unknown lora_id {lora_id}"
    assert 2 <= num_clips <= 4

    scene_dir = OUT_DIR / scene_id
    scene_dir.mkdir(exist_ok=True)

    clips = []
    # Clip 1 — text only
    t0 = time.time()
    clip1 = scene_dir / "clip_1.mp4"
    print(f"[{time.strftime('%H:%M:%S')}] clip 1/{num_clips} T2V — {lora_id} @ w={weight}")
    gen_clip_t2v(prompt, lora_id, weight, clip1)
    print(f"  done {time.time()-t0:.1f}s -> {clip1.name}")
    clips.append(clip1)

    # Subsequent clips — I2V chained on last frame
    for i in range(2, num_clips + 1):
        prev = clips[-1]
        last_png = scene_dir / f"last_frame_{i-1}.png"
        extract_last_frame(prev, last_png)
        out = scene_dir / f"clip_{i}.mp4"
        t0 = time.time()
        print(f"[{time.strftime('%H:%M:%S')}] clip {i}/{num_clips} I2V — seeding from clip {i-1} last frame")
        gen_clip_i2v(prompt, lora_id, weight, last_png, out)
        print(f"  done {time.time()-t0:.1f}s -> {out.name}")
        clips.append(out)

    # Concat
    final = OUT_DIR / f"continuity_{scene_id}.mp4"
    concat_clips(clips, final)
    print(f"final continuity video -> {final}")

    # Sidecar
    (scene_dir / "meta.json").write_text(json.dumps({
        "scene_id": scene_id, "prompt": prompt, "lora_id": lora_id, "weight": weight,
        "num_clips": num_clips, "seed": SEED, "clips": [str(c) for c in clips],
        "final": str(final),
    }, indent=2))


if __name__ == "__main__":
    main()
