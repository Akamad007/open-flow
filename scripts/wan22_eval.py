#!/usr/bin/env python3
"""Wan 2.2 TI2V-5B evaluation harness — throwaway.

Sweeps (prompt × lora × weight) and writes mp4 + json sidecar per cell.
Not production code; lives in scripts/ for one-shot evaluation only.
"""
from __future__ import annotations

import gc
import json
import os
import time
import traceback
from dataclasses import dataclass
from pathlib import Path

os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

import torch
from diffusers import WanPipeline
from diffusers.utils import export_to_video

MODEL_DIR = "/home/akash/Wan2.2-Models/TI2V-5B-Diffusers"
LORA_DIR = Path("/home/akash/Wan2.2-Models/loras")
OUT_DIR = Path("/home/akash/PycharmProjects/video-app/docs/runs/wan22-eval")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# 5-second clips. Wan needs 4n+1 frames at native fps=24 → 121 frames = ~5.04 s.
# 832x480 keeps 16:9 and is divisible by 16; native-res 1280x704 would push
# per-video runtime over budget on a 16 GB GPU with model_cpu_offload.
FPS = 24
NUM_FRAMES = 121
HEIGHT = 480
WIDTH = 832
STEPS = 40
GUIDANCE = 5.0
SEED = 1234

PROMPTS = [
    ("p1_runner",  "A man in athletic gear running through a tree-lined park at golden hour, side view, full body visible, dynamic stride, autumn leaves on the ground, shallow depth of field, cinematic"),
    ("p2_coffee",  "A man in a knitted sweater sitting at a wooden cafe table, slowly lifting a ceramic coffee cup to his lips, soft window light from the left, steam rising from the cup, warm bokeh background"),
    ("p3_purse",   "A young fashion model in a beige trench coat walking down a city sidewalk holding a brown leather purse over her shoulder, side view, full body, golden hour light, elegant pace"),
    ("p4_chef",    "A chef in a white apron tossing fresh vegetables in a black pan over a gas flame, kitchen with stainless steel surfaces, dramatic side light, sparks of fire, motion blur on the vegetables"),
    ("p5_dancer",  "A woman in a flowing red dress dancing and twirling in a sunlit ballroom, full body visible, evening light through tall windows, hair and fabric in motion, cinematic"),
]

NEG = "blurry, low quality, distorted, oversaturated, watermark, text, logo, deformed hands, extra limbs"


@dataclass
class LoRACell:
    id: str           # "none" | "hstoric_color" | "oil_painting" | "lightning_a14b"
    path: str | None  # absolute path to .safetensors, or None for baseline
    weight: float


# Lightning A14B LoRAs probe-confirmed incompatible (A14B hidden=5120, TI2V-5B=3072) — excluded.
# Baseline cell ("none") serves as weight=0 for ALL LoRAs (output identical).
CELLS_PER_PROMPT: list[LoRACell] = [
    LoRACell("none", None, 0.0),
    LoRACell("hstoric_color", str(LORA_DIR / "5b" / "hstoric_color_5b.safetensors"), 0.5),
    LoRACell("hstoric_color", str(LORA_DIR / "5b" / "hstoric_color_5b.safetensors"), 1.0),
    LoRACell("oil_painting",  str(LORA_DIR / "5b" / "oil_painting_5b.safetensors"), 0.5),
    LoRACell("oil_painting",  str(LORA_DIR / "5b" / "oil_painting_5b.safetensors"), 1.0),
]


def free_cuda():
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.ipc_collect()


def load_pipeline() -> WanPipeline:
    print(f"[{time.strftime('%H:%M:%S')}] loading WanPipeline from {MODEL_DIR} (bf16 + model cpu offload)")
    pipe = WanPipeline.from_pretrained(MODEL_DIR, torch_dtype=torch.bfloat16)
    # 16 GB GPU can't hold transformer (10G) + text_encoder (5.5G) + vae (1.4G) bf16 simultaneously.
    pipe.enable_model_cpu_offload()
    for fn_name in ("enable_vae_slicing", "enable_vae_tiling"):
        fn = getattr(pipe, fn_name, None)
        if callable(fn):
            try: fn()
            except Exception: pass
    return pipe


def apply_lora(pipe: WanPipeline, cell: LoRACell) -> dict:
    """Returns metadata dict with load_ok + error (if any)."""
    if cell.id == "none" or not cell.path:
        return {"load_ok": True, "error": None}
    try:
        adapter_name = cell.id
        pipe.load_lora_weights(cell.path, adapter_name=adapter_name)
        pipe.set_adapters([adapter_name], adapter_weights=[cell.weight])
        return {"load_ok": True, "error": None, "adapter_name": adapter_name}
    except Exception as e:
        tb = traceback.format_exc(limit=4)
        return {"load_ok": False, "error": f"{type(e).__name__}: {e}", "traceback": tb}


def unload_lora(pipe: WanPipeline) -> None:
    for fn_name in ("disable_lora", "unload_lora_weights"):
        try:
            fn = getattr(pipe, fn_name, None)
            if callable(fn): fn()
        except Exception:
            pass


def generate_one(pipe: WanPipeline, prompt_id: str, prompt: str, cell: LoRACell) -> dict:
    fname = f"{prompt_id}__{cell.id}__w{cell.weight}.mp4"
    out_path = OUT_DIR / fname
    sidecar = OUT_DIR / (fname + ".json")
    meta = {
        "prompt_id": prompt_id,
        "prompt": prompt,
        "lora_id": cell.id,
        "lora_weight": cell.weight,
        "seed": SEED,
        "frames": NUM_FRAMES,
        "fps": FPS,
        "h": HEIGHT, "w": WIDTH,
        "steps": STEPS, "guidance": GUIDANCE,
        "out": str(out_path),
    }

    lora_meta = apply_lora(pipe, cell)
    meta.update(lora_meta)
    if not lora_meta["load_ok"]:
        sidecar.write_text(json.dumps(meta, indent=2))
        print(f"  SKIP {fname}: LoRA load failed — {lora_meta['error']}")
        return meta

    t0 = time.time()
    try:
        gen = torch.Generator(device="cuda").manual_seed(SEED)
        out = pipe(
            prompt=prompt, negative_prompt=NEG,
            height=HEIGHT, width=WIDTH, num_frames=NUM_FRAMES,
            num_inference_steps=STEPS, guidance_scale=GUIDANCE,
            generator=gen,
        )
        export_to_video(out.frames[0], str(out_path), fps=FPS)
        meta["wall_clock_s"] = round(time.time() - t0, 1)
        meta["gen_ok"] = True
        print(f"  OK   {fname}  ({meta['wall_clock_s']}s)")
    except Exception as e:
        meta["wall_clock_s"] = round(time.time() - t0, 1)
        meta["gen_ok"] = False
        meta["gen_error"] = f"{type(e).__name__}: {e}"
        meta["gen_traceback"] = traceback.format_exc(limit=4)
        print(f"  FAIL {fname}: {meta['gen_error']}")
    finally:
        unload_lora(pipe)
        free_cuda()
    sidecar.write_text(json.dumps(meta, indent=2))
    return meta


def main():
    pipe = load_pipeline()
    print(f"[{time.strftime('%H:%M:%S')}] pipeline ready — starting matrix")
    results = []
    total = len(PROMPTS) * len(CELLS_PER_PROMPT)
    n = 0
    for prompt_id, prompt in PROMPTS:
        for cell in CELLS_PER_PROMPT:
            n += 1
            print(f"[{n}/{total}] {prompt_id} × {cell.id} @ w={cell.weight}")
            r = generate_one(pipe, prompt_id, prompt, cell)
            results.append(r)
    (OUT_DIR / "results.json").write_text(json.dumps(results, indent=2))
    print(f"[{time.strftime('%H:%M:%S')}] done. results -> {OUT_DIR}/results.json")


if __name__ == "__main__":
    main()
