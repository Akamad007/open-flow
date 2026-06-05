#!/usr/bin/env python3
"""Wan 2.2 TI2V-5B generation CLI — subprocess target for Wan22VideoProvider.

Mirrors ltx_generate.py's calling convention so the provider can invoke it cleanly.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

import torch
# cusolver fails inside UniPC scheduler's multistep_uni_c_bh_update on this
# RTX 5070 Ti / driver combo. Force MAGMA for linalg ops so the small
# in-scheduler solve doesn't blow up the whole run.
try:
    torch.backends.cuda.preferred_linalg_library("magma")
except Exception:
    pass
from PIL import Image
from diffusers import WanPipeline, WanImageToVideoPipeline
from diffusers.utils import export_to_video

DEFAULT_MODEL = "/home/akash/Wan2.2-Models/TI2V-5B-Diffusers"
DEFAULT_LORA_DIR = "/home/akash/Wan2.2-Models/loras/5b"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--prompt", required=True)
    p.add_argument("--negative-prompt", default="")
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--lora-id", default=None, help="LoRA name (matches catalog id, no path)")
    p.add_argument("--lora-file", default=None, help="LoRA filename (resolved under --lora-dir)")
    p.add_argument("--lora-weight", type=float, default=0.0)
    p.add_argument("--lora-dir", default=DEFAULT_LORA_DIR)
    # Repeatable stack on top of the primary --lora-* triple.
    # Each --lora is "id:file:weight" — e.g. "hstoric_color:hstoric_color_5b.safetensors:0.5".
    p.add_argument("--lora", action="append", default=[],
                   help="Additional LoRA as 'id:file:weight'. Repeatable.")
    p.add_argument("--height", type=int, default=480)
    p.add_argument("--width", type=int, default=832)
    p.add_argument("--num-frames", type=int, default=121)
    p.add_argument("--num-inference-steps", type=int, default=40)
    p.add_argument("--guidance-scale", type=float, default=5.0)
    p.add_argument("--fps", type=int, default=24)
    p.add_argument("--seed", type=int, default=1234)
    p.add_argument("--condition-image", default=None,
                   help="If set, run I2V seeded from this image instead of T2V")
    p.add_argument("--last-image", default=None,
                   help="Identity anchor image for the last frame (reduces face drift)")
    p.add_argument("--sequential-offload", action="store_true",
                   help="Use sequential CPU offload (lower VRAM, slower) for small GPUs")
    return p.parse_args()


def load_pipe(model_dir: str, i2v: bool, sequential_offload: bool = False):
    cls = WanImageToVideoPipeline if i2v else WanPipeline
    pipe = cls.from_pretrained(model_dir, torch_dtype=torch.bfloat16)
    # Keep the default UniPC bh2 scheduler — bh1 produces all-black/frozen
    # output on Wan22's flow_prediction schedule. The intermittent cusolver
    # error in multistep_uni_c_bh_update is mitigated by the MAGMA backend
    # override set at module import (top of this file).
    if sequential_offload:
        pipe.enable_sequential_cpu_offload()
        print("  using sequential CPU offload (low-VRAM mode)")
    else:
        pipe.enable_model_cpu_offload()
    # Lossless VRAM reductions — process VAE in tiles and attention in chunks
    # so the 832×480×121f peak doesn't OOM on the 16GB card.
    if hasattr(pipe, "vae"):
        if hasattr(pipe.vae, "enable_tiling"):
            pipe.vae.enable_tiling()
        if hasattr(pipe.vae, "enable_slicing"):
            pipe.vae.enable_slicing()
    if hasattr(pipe, "enable_attention_slicing"):
        pipe.enable_attention_slicing("max")
    return pipe


def apply_lora(pipe, lora_id: str, lora_file: str, lora_dir: str, weight: float,
               extras: list[str] | None = None):
    """Load primary + any --lora extras as a stacked adapter set."""
    stack: list[tuple[str, str, float]] = []
    if lora_id and lora_file and weight > 0:
        stack.append((lora_id, lora_file, weight))
    for spec in (extras or []):
        parts = spec.split(":")
        if len(parts) != 3:
            print(f"ERROR: bad --lora spec {spec!r}, expected id:file:weight", file=sys.stderr)
            sys.exit(2)
        eid, efile, ew = parts[0], parts[1], float(parts[2])
        if eid and efile and ew > 0:
            stack.append((eid, efile, ew))
    if not stack:
        return
    # De-dupe by id (last weight wins) so callers can't double-load the same adapter.
    by_id: dict[str, tuple[str, float]] = {}
    for eid, efile, ew in stack:
        by_id[eid] = (efile, ew)
    loaded: list[str] = []
    for eid, (efile, _) in by_id.items():
        path = Path(lora_dir) / efile
        if not path.exists():
            print(f"ERROR: LoRA not found: {path}", file=sys.stderr)
            sys.exit(2)
        try:
            pipe.load_lora_weights(str(path), adapter_name=eid)
            loaded.append(eid)
        except Exception as e:
            # A single incompatible LoRA (e.g. wrong base model / format) must not
            # sink the whole render — skip it and continue with the rest.
            print(f"WARN: skipping LoRA {eid!r} ({efile}): {e}", file=sys.stderr)
    if not loaded:
        return
    weights = [by_id[i][1] for i in loaded]
    pipe.set_adapters(loaded, adapter_weights=weights)
    print(f"  loaded LoRA stack: {list(zip(loaded, weights))}")


def main():
    args = parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    i2v = bool(args.condition_image and Path(args.condition_image).exists())
    print(f"[{time.strftime('%H:%M:%S')}] {'I2V' if i2v else 'T2V'} {args.width}x{args.height} "
          f"{args.num_frames}f @ {args.num_inference_steps} steps")
    pipe = load_pipe(args.model, i2v=i2v, sequential_offload=args.sequential_offload)
    apply_lora(pipe, args.lora_id, args.lora_file, args.lora_dir, args.lora_weight,
               extras=args.lora)

    gen = torch.Generator(device="cuda").manual_seed(args.seed)
    t0 = time.time()
    kwargs = dict(prompt=args.prompt, negative_prompt=args.negative_prompt,
                  height=args.height, width=args.width, num_frames=args.num_frames,
                  num_inference_steps=args.num_inference_steps,
                  guidance_scale=args.guidance_scale, generator=gen)
    if i2v:
        img = Image.open(args.condition_image).convert("RGB").resize((args.width, args.height))
        kwargs["image"] = img
    if i2v and args.last_image and Path(args.last_image).exists():
        last_img = Image.open(args.last_image).convert("RGB").resize((args.width, args.height))
        kwargs["last_image"] = last_img
        print(f"  last_image anchor: {args.last_image}")
    out = pipe(**kwargs)
    export_to_video(out.frames[0], str(args.output), fps=args.fps)
    print(f"[{time.strftime('%H:%M:%S')}] done in {time.time()-t0:.1f}s -> {args.output}")


if __name__ == "__main__":
    main()
