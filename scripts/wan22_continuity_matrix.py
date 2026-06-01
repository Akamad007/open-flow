#!/usr/bin/env python3
"""Continuity matrix — every LoRA cell tested as a 2-clip chained sequence.

Per cell:
  clip_1: WanPipeline (text-only) with LoRA applied
  clip_2: WanImageToVideoPipeline (image=last_frame_of_clip_1) with SAME LoRA
  concat → continuity/<scene>__<lora>__w<weight>.mp4 (~10 sec)

Same settings as v1-v3 (832x480, 121f, 40 steps, seed 1234).
"""
from __future__ import annotations

import gc
import json
import os
import subprocess
import time
import traceback
from dataclasses import dataclass
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

# Scenes covering distinct content categories
SCENES = [
    ("c_runner", "A man in athletic gear running through a tree-lined park at golden hour, side view, full body visible, dynamic stride, autumn leaves on the ground, shallow depth of field, cinematic"),
    ("c_coffee", "A man in a knitted sweater sitting at a wooden cafe table, slowly lifting a ceramic coffee cup to his lips, soft window light from the left, steam rising from the cup, warm bokeh background"),
    ("c_crowd",  "A massive crowd of people chanting in unison at an outdoor rally, raised fists, banners and flags waving above heads, evening light, energetic atmosphere, wide shot, faces visible in the foreground, cinematic"),
]


@dataclass
class LoRACell:
    id: str
    path: str | None
    weight: float


LORA_CELLS = [
    LoRACell("none", None, 0.0),
    LoRACell("hstoric_color", str(LORA_DIR / "hstoric_color_5b.safetensors"), 0.5),
    LoRACell("hstoric_color", str(LORA_DIR / "hstoric_color_5b.safetensors"), 1.0),
    LoRACell("oil_painting",  str(LORA_DIR / "oil_painting_5b.safetensors"),  0.5),
    LoRACell("oil_painting",  str(LORA_DIR / "oil_painting_5b.safetensors"),  1.0),
    LoRACell("crush_it",      str(LORA_DIR / "crush_it_5b.safetensors"),      0.5),
    LoRACell("crush_it",      str(LORA_DIR / "crush_it_5b.safetensors"),      1.0),
    LoRACell("aether_punch",  str(LORA_DIR / "aether_punch_5b.safetensors"),  0.5),
    LoRACell("aether_punch",  str(LORA_DIR / "aether_punch_5b.safetensors"),  1.0),
    LoRACell("aether_splash", str(LORA_DIR / "aether_splash_5b.safetensors"), 0.5),
    LoRACell("aether_splash", str(LORA_DIR / "aether_splash_5b.safetensors"), 1.0),
    LoRACell("zackdfilms",    str(LORA_DIR / "zackdfilms_5b_fixed.safetensors"), 0.5),
    LoRACell("zackdfilms",    str(LORA_DIR / "zackdfilms_5b_fixed.safetensors"), 1.0),
    LoRACell("woven_fabric",  str(LORA_DIR / "woven_fabric_5b.safetensors"),  0.5),
    LoRACell("woven_fabric",  str(LORA_DIR / "woven_fabric_5b.safetensors"),  1.0),
]


def free_cuda():
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache(); torch.cuda.ipc_collect()


def apply_lora(pipe, cell: LoRACell):
    if cell.id == "none" or not cell.path:
        return True, None
    try:
        pipe.load_lora_weights(cell.path, adapter_name=cell.id)
        pipe.set_adapters([cell.id], adapter_weights=[cell.weight])
        return True, None
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def unload_lora(pipe):
    for fn_name in ("disable_lora", "unload_lora_weights"):
        try:
            fn = getattr(pipe, fn_name, None)
            if callable(fn): fn()
        except Exception:
            pass


def extract_last_frame(mp4_path: Path, out_png: Path):
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-sseof", "-0.1",
           "-i", str(mp4_path), "-vframes", "1", str(out_png)]
    subprocess.run(cmd, check=True)


def concat_clips(clips: list[Path], out_mp4: Path):
    list_file = out_mp4.with_suffix(".txt")
    list_file.write_text("\n".join(f"file '{c.absolute()}'" for c in clips))
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
           "-i", str(list_file), "-c", "copy", str(out_mp4)]
    subprocess.run(cmd, check=True)
    list_file.unlink()


def gen_t2v(pipe, prompt: str):
    gen = torch.Generator(device="cuda").manual_seed(SEED)
    out = pipe(prompt=prompt, negative_prompt=NEG, height=HEIGHT, width=WIDTH,
               num_frames=NUM_FRAMES, num_inference_steps=STEPS,
               guidance_scale=GUIDANCE, generator=gen)
    return out.frames[0]


def gen_i2v(pipe, prompt: str, first_frame_png: Path):
    image = Image.open(first_frame_png).convert("RGB").resize((WIDTH, HEIGHT))
    gen = torch.Generator(device="cuda").manual_seed(SEED)
    out = pipe(image=image, prompt=prompt, negative_prompt=NEG,
               height=HEIGHT, width=WIDTH, num_frames=NUM_FRAMES,
               num_inference_steps=STEPS, guidance_scale=GUIDANCE, generator=gen)
    return out.frames[0]


def run_cell(t2v_pipe, i2v_pipe, scene_id: str, prompt: str, cell: LoRACell):
    """Generate 2-clip continuity for one (scene, lora) cell."""
    tag = f"{scene_id}__{cell.id}__w{cell.weight}"
    work = OUT_DIR / "work" / tag
    work.mkdir(parents=True, exist_ok=True)
    final = OUT_DIR / f"{tag}.mp4"
    sidecar = OUT_DIR / f"{tag}.json"
    if final.exists():
        print(f"  skip (already done): {tag}")
        return {"tag": tag, "skipped": True}

    meta = {"tag": tag, "scene_id": scene_id, "prompt": prompt,
            "lora_id": cell.id, "lora_weight": cell.weight,
            "seed": SEED, "frames_per_clip": NUM_FRAMES, "fps": FPS,
            "h": HEIGHT, "w": WIDTH, "steps": STEPS, "guidance": GUIDANCE,
            "final": str(final)}

    # --- Clip 1 (T2V) ---
    ok, err = apply_lora(t2v_pipe, cell)
    meta["clip1_lora_ok"] = ok
    if not ok:
        meta["clip1_error"] = err
        sidecar.write_text(json.dumps(meta, indent=2))
        print(f"  SKIP clip1 lora load: {err}")
        return meta
    t0 = time.time()
    try:
        frames = gen_t2v(t2v_pipe, prompt)
        clip1 = work / "clip_1.mp4"
        export_to_video(frames, str(clip1), fps=FPS)
        meta["clip1_wall_s"] = round(time.time() - t0, 1)
    except Exception as e:
        meta["clip1_error"] = f"{type(e).__name__}: {e}"
        meta["clip1_tb"] = traceback.format_exc(limit=4)
        sidecar.write_text(json.dumps(meta, indent=2))
        print(f"  FAIL clip1: {meta['clip1_error']}")
        unload_lora(t2v_pipe); free_cuda()
        return meta
    finally:
        unload_lora(t2v_pipe); free_cuda()

    # --- Extract last frame of clip 1 ---
    last_png = work / "frame_last_1.png"
    extract_last_frame(clip1, last_png)

    # --- Clip 2 (I2V from clip 1 last frame) ---
    ok, err = apply_lora(i2v_pipe, cell)
    meta["clip2_lora_ok"] = ok
    if not ok:
        meta["clip2_error"] = err
        sidecar.write_text(json.dumps(meta, indent=2))
        print(f"  FAIL clip2 lora load: {err}")
        return meta
    t0 = time.time()
    try:
        frames = gen_i2v(i2v_pipe, prompt, last_png)
        clip2 = work / "clip_2.mp4"
        export_to_video(frames, str(clip2), fps=FPS)
        meta["clip2_wall_s"] = round(time.time() - t0, 1)
    except Exception as e:
        meta["clip2_error"] = f"{type(e).__name__}: {e}"
        meta["clip2_tb"] = traceback.format_exc(limit=4)
        sidecar.write_text(json.dumps(meta, indent=2))
        print(f"  FAIL clip2: {meta['clip2_error']}")
        unload_lora(i2v_pipe); free_cuda()
        return meta
    finally:
        unload_lora(i2v_pipe); free_cuda()

    # --- Concat ---
    concat_clips([clip1, clip2], final)
    meta["ok"] = True
    sidecar.write_text(json.dumps(meta, indent=2))
    print(f"  OK   {tag}  (clip1={meta['clip1_wall_s']}s  clip2={meta['clip2_wall_s']}s)")
    return meta


def main():
    for cell in LORA_CELLS:
        if cell.path and not Path(cell.path).exists():
            raise FileNotFoundError(f"missing LoRA: {cell.path}")

    print(f"[{time.strftime('%H:%M:%S')}] loading T2V WanPipeline")
    t2v_pipe = WanPipeline.from_pretrained(MODEL_DIR, torch_dtype=torch.bfloat16)
    t2v_pipe.enable_model_cpu_offload()

    print(f"[{time.strftime('%H:%M:%S')}] loading I2V WanImageToVideoPipeline (shares weights via diffusers)")
    i2v_pipe = WanImageToVideoPipeline.from_pretrained(MODEL_DIR, torch_dtype=torch.bfloat16)
    i2v_pipe.enable_model_cpu_offload()

    total = len(SCENES) * len(LORA_CELLS)
    n = 0
    results = []
    for scene_id, prompt in SCENES:
        for cell in LORA_CELLS:
            n += 1
            print(f"[{n}/{total}] {scene_id} × {cell.id} @ w={cell.weight}")
            r = run_cell(t2v_pipe, i2v_pipe, scene_id, prompt, cell)
            results.append(r)
    (OUT_DIR / "continuity_results.json").write_text(json.dumps(results, indent=2))
    print(f"[{time.strftime('%H:%M:%S')}] continuity matrix done -> {OUT_DIR}")


if __name__ == "__main__":
    main()
