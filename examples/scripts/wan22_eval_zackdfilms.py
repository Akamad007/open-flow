#!/usr/bin/env python3
"""Recovery run for zackdfilms LoRA (key-remapped). 10 cells."""
from __future__ import annotations
import gc, json, os, time, traceback
from pathlib import Path
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
import torch
from diffusers import WanPipeline
from diffusers.utils import export_to_video

MODEL_DIR = "/home/akash/Wan2.2-Models/TI2V-5B-Diffusers"
LORA_PATH = "/home/akash/Wan2.2-Models/loras/5b/zackdfilms_5b_fixed.safetensors"
OUT_DIR = Path("/home/akash/PycharmProjects/video-app/docs/runs/wan22-eval")
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

pipe = WanPipeline.from_pretrained(MODEL_DIR, torch_dtype=torch.bfloat16)
pipe.enable_model_cpu_offload()
print(f"[{time.strftime('%H:%M:%S')}] pipeline ready — zackdfilms recovery")

n = 0
for prompt_id, prompt in PROMPTS:
    for weight in [0.5, 1.0]:
        n += 1
        fname = f"{prompt_id}__zackdfilms__w{weight}.mp4"
        out_path = OUT_DIR / fname
        sidecar = OUT_DIR / (fname + ".json")
        meta = {"prompt_id": prompt_id, "prompt": prompt, "lora_id": "zackdfilms",
                "lora_weight": weight, "seed": SEED, "frames": NUM_FRAMES, "fps": FPS,
                "h": HEIGHT, "w": WIDTH, "steps": STEPS, "guidance": GUIDANCE,
                "out": str(out_path), "lora_source": "fixed-keys"}
        print(f"[{n}/10] {prompt_id} × zackdfilms @ w={weight}")
        try:
            pipe.load_lora_weights(LORA_PATH, adapter_name="zackdfilms")
            pipe.set_adapters(["zackdfilms"], adapter_weights=[weight])
            meta["load_ok"] = True
        except Exception as e:
            meta["load_ok"] = False
            meta["error"] = f"{type(e).__name__}: {e}"
            meta["tb"] = traceback.format_exc(limit=4)
            sidecar.write_text(json.dumps(meta, indent=2))
            print(f"  SKIP load fail: {meta['error']}")
            continue
        t0 = time.time()
        try:
            gen = torch.Generator(device="cuda").manual_seed(SEED)
            out = pipe(prompt=prompt, negative_prompt=NEG, height=HEIGHT, width=WIDTH,
                       num_frames=NUM_FRAMES, num_inference_steps=STEPS, guidance_scale=GUIDANCE,
                       generator=gen)
            export_to_video(out.frames[0], str(out_path), fps=FPS)
            meta["wall_clock_s"] = round(time.time() - t0, 1)
            meta["gen_ok"] = True
            print(f"  OK {fname} ({meta['wall_clock_s']}s)")
        except Exception as e:
            meta["wall_clock_s"] = round(time.time() - t0, 1)
            meta["gen_ok"] = False
            meta["gen_error"] = f"{type(e).__name__}: {e}"
            meta["gen_traceback"] = traceback.format_exc(limit=4)
            print(f"  FAIL {fname}: {meta['gen_error']}")
        finally:
            try: pipe.disable_lora()
            except Exception: pass
            try: pipe.unload_lora_weights()
            except Exception: pass
            gc.collect()
            if torch.cuda.is_available(): torch.cuda.empty_cache()
        sidecar.write_text(json.dumps(meta, indent=2))
print(f"[{time.strftime('%H:%M:%S')}] zackdfilms recovery done")
