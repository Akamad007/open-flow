#!/usr/bin/env python3
"""Wan 2.2 TI2V-5B matrix v2 — new 5B LoRAs only.

Reuses settings from wan22_eval.py (832x480, 121f, 40 steps, same 5 prompts,
same seed 1234). Five new LoRAs swept at 0.5 and 1.0. Baseline cells are
already in matrix v1 so omitted here.
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
LORA_DIR = Path("/home/akash/Wan2.2-Models/loras/5b")
OUT_DIR = Path("/home/akash/PycharmProjects/video-app/docs/runs/wan22-eval")
OUT_DIR.mkdir(parents=True, exist_ok=True)

FPS, NUM_FRAMES, HEIGHT, WIDTH = 24, 121, 480, 832
STEPS, GUIDANCE, SEED = 40, 5.0, 1234

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
    id: str
    path: str
    weight: float


CELLS_PER_PROMPT: list[LoRACell] = [
    LoRACell("crush_it",      str(LORA_DIR / "crush_it_5b.safetensors"),      0.5),
    LoRACell("crush_it",      str(LORA_DIR / "crush_it_5b.safetensors"),      1.0),
    LoRACell("aether_punch",  str(LORA_DIR / "aether_punch_5b.safetensors"),  0.5),
    LoRACell("aether_punch",  str(LORA_DIR / "aether_punch_5b.safetensors"),  1.0),
    LoRACell("aether_splash", str(LORA_DIR / "aether_splash_5b.safetensors"), 0.5),
    LoRACell("aether_splash", str(LORA_DIR / "aether_splash_5b.safetensors"), 1.0),
    LoRACell("zackdfilms",    str(LORA_DIR / "zackdfilms_5b.safetensors"),    0.5),
    LoRACell("zackdfilms",    str(LORA_DIR / "zackdfilms_5b.safetensors"),    1.0),
    LoRACell("woven_fabric",  str(LORA_DIR / "woven_fabric_5b.safetensors"),  0.5),
    LoRACell("woven_fabric",  str(LORA_DIR / "woven_fabric_5b.safetensors"),  1.0),
]


def free_cuda():
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.ipc_collect()


def load_pipeline() -> WanPipeline:
    print(f"[{time.strftime('%H:%M:%S')}] loading WanPipeline (bf16 + model cpu offload)")
    pipe = WanPipeline.from_pretrained(MODEL_DIR, torch_dtype=torch.bfloat16)
    pipe.enable_model_cpu_offload()
    for fn_name in ("enable_vae_slicing", "enable_vae_tiling"):
        fn = getattr(pipe, fn_name, None)
        if callable(fn):
            try: fn()
            except Exception: pass
    return pipe


def apply_lora(pipe, cell):
    try:
        pipe.load_lora_weights(cell.path, adapter_name=cell.id)
        pipe.set_adapters([cell.id], adapter_weights=[cell.weight])
        return {"load_ok": True, "error": None}
    except Exception as e:
        return {"load_ok": False, "error": f"{type(e).__name__}: {e}",
                "tb": traceback.format_exc(limit=4)}


def unload_lora(pipe):
    for fn_name in ("disable_lora", "unload_lora_weights"):
        try:
            fn = getattr(pipe, fn_name, None)
            if callable(fn): fn()
        except Exception:
            pass


def generate_one(pipe, prompt_id, prompt, cell):
    fname = f"{prompt_id}__{cell.id}__w{cell.weight}.mp4"
    out_path = OUT_DIR / fname
    sidecar = OUT_DIR / (fname + ".json")
    meta = {
        "prompt_id": prompt_id, "prompt": prompt,
        "lora_id": cell.id, "lora_weight": cell.weight,
        "seed": SEED, "frames": NUM_FRAMES, "fps": FPS,
        "h": HEIGHT, "w": WIDTH, "steps": STEPS, "guidance": GUIDANCE,
        "out": str(out_path),
    }
    lora_meta = apply_lora(pipe, cell)
    meta.update(lora_meta)
    if not lora_meta["load_ok"]:
        sidecar.write_text(json.dumps(meta, indent=2))
        print(f"  SKIP {fname}: {lora_meta['error']}")
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
    # Sanity: all LoRA files exist
    for cell in CELLS_PER_PROMPT:
        if not Path(cell.path).exists():
            raise FileNotFoundError(f"missing LoRA: {cell.path}")
    pipe = load_pipeline()
    print(f"[{time.strftime('%H:%M:%S')}] pipeline ready — matrix v2")
    results = []
    total = len(PROMPTS) * len(CELLS_PER_PROMPT)
    n = 0
    for prompt_id, prompt in PROMPTS:
        for cell in CELLS_PER_PROMPT:
            n += 1
            print(f"[{n}/{total}] {prompt_id} × {cell.id} @ w={cell.weight}")
            r = generate_one(pipe, prompt_id, prompt, cell)
            results.append(r)
    (OUT_DIR / "results_v2.json").write_text(json.dumps(results, indent=2))
    print(f"[{time.strftime('%H:%M:%S')}] v2 done -> {OUT_DIR}/results_v2.json")


if __name__ == "__main__":
    main()
