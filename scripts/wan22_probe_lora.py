#!/usr/bin/env python3
"""Probe each LoRA can be loaded on TI2V-5B. Records compatibility, no generation."""
import os, time, json, traceback
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
import torch
from diffusers import WanPipeline

MODEL = "/home/akash/Wan2.2-Models/TI2V-5B-Diffusers"
LORAS = [
    ("hstoric_color", "/home/akash/Wan2.2-Models/loras/5b/hstoric_color_5b.safetensors"),
    ("oil_painting",  "/home/akash/Wan2.2-Models/loras/5b/oil_painting_5b.safetensors"),
    ("lightning_a14b_high", "/home/akash/Wan2.2-Models/loras/lightning/Wan2.2-T2V-A14B-4steps-lora-rank64-Seko-V1.1/high_noise_model.safetensors"),
    ("lightning_a14b_low",  "/home/akash/Wan2.2-Models/loras/lightning/Wan2.2-T2V-A14B-4steps-lora-rank64-Seko-V1.1/low_noise_model.safetensors"),
]

pipe = WanPipeline.from_pretrained(MODEL, torch_dtype=torch.bfloat16)
pipe.enable_model_cpu_offload()
print("pipeline loaded")

report = []
for name, path in LORAS:
    print(f"\n--- {name} ---")
    rec = {"id": name, "path": path}
    try:
        pipe.load_lora_weights(path, adapter_name=name)
        pipe.set_adapters([name], adapter_weights=[1.0])
        rec["load_ok"] = True
        rec["error"] = None
        print(f"  OK")
    except Exception as e:
        rec["load_ok"] = False
        rec["error"] = f"{type(e).__name__}: {e}"
        rec["tb"] = traceback.format_exc(limit=6)
        print(f"  FAIL: {rec['error']}")
    finally:
        try: pipe.disable_lora()
        except Exception: pass
        try: pipe.unload_lora_weights()
        except Exception: pass
    report.append(rec)

import json
out = "/home/akash/PycharmProjects/video-app/docs/runs/wan22-eval/lora_probe.json"
with open(out, "w") as f:
    json.dump(report, f, indent=2)
print(f"\nreport -> {out}")
