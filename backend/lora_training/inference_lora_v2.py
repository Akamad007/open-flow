"""Inference test for LoRA v2 — loads SDXL + lora_runner_man_v2/.

Renders the same 4 poses as v1 (standing / running / sitting / jumping)
plus 4 NEW poses the v2 dataset added (presenting, gesturing, throwing,
dancing) so we can see whether the larger dataset captured movement
diversity better."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import torch
from diffusers import StableDiffusionXLPipeline

OUT_DIR = Path(__file__).parent / "lora_v2_inference_smoke"
LORA_DIR = Path(__file__).parent / "lora_runner_man_v2"

PROMPTS = [
    # Same 4 as v1 — direct comparison
    ("standing_neutral",
     "ohwx man, full-body photo, athletic young man with short dark brown "
     "hair wearing a charcoal grey performance tee, dark technical shorts, "
     "and white athletic trainers, standing in a neutral upright pose, "
     "three-quarter front view, plain neutral grey studio backdrop, "
     "soft even lighting, sharp focus, photorealistic"),
    ("running_side",
     "ohwx man, full-body photo, athletic young man with short dark brown "
     "hair wearing a charcoal grey performance tee, dark technical shorts, "
     "and white athletic trainers, mid-stride running pose, side profile, "
     "both feet briefly off ground, plain neutral grey studio backdrop, "
     "soft even lighting, sharp focus, photorealistic"),
    ("sitting_lacing",
     "ohwx man, full-body photo, athletic young man with short dark brown "
     "hair wearing a charcoal grey performance tee, dark technical shorts, "
     "and white athletic trainers, sitting on a low concrete bench leaning "
     "forward to tie his shoelaces, side profile, plain neutral grey "
     "studio backdrop, soft even lighting, sharp focus, photorealistic"),
    ("jumping",
     "ohwx man, full-body photo, athletic young man with short dark brown "
     "hair wearing a charcoal grey performance tee, dark technical shorts, "
     "and white athletic trainers, mid-air vertical jump, knees slightly "
     "bent, arms raised, side profile, plain neutral grey studio backdrop, "
     "soft even lighting, sharp focus, photorealistic"),

    # v2-only poses
    ("presenting_to_camera",
     "ohwx man, full-body photo, athletic young man with short dark brown "
     "hair wearing a charcoal grey performance tee, dark technical shorts, "
     "and white athletic trainers, standing facing the camera, one arm "
     "extended forward presenting an open palm, three-quarter front view, "
     "plain neutral grey studio backdrop, soft even lighting, sharp focus, "
     "photorealistic"),
    ("gesturing_explaining",
     "ohwx man, full-body photo, athletic young man with short dark brown "
     "hair wearing a charcoal grey performance tee, dark technical shorts, "
     "and white athletic trainers, standing facing the camera with both "
     "hands open at chest height as if explaining something, plain neutral "
     "grey studio backdrop, soft even lighting, sharp focus, photorealistic"),
    ("throwing_overhand",
     "ohwx man, full-body photo, athletic young man with short dark brown "
     "hair wearing a charcoal grey performance tee, dark technical shorts, "
     "and white athletic trainers, mid-throw overhand pitching motion, arm "
     "cocked back, body twisted, side profile, plain neutral grey studio "
     "backdrop, soft even lighting, sharp focus, photorealistic"),
    ("dancing_pose",
     "ohwx man, full-body photo, athletic young man with short dark brown "
     "hair wearing a charcoal grey performance tee, dark technical shorts, "
     "and white athletic trainers, dynamic dance pose with one arm raised "
     "up and one knee bent, body twisted in motion, three-quarter front "
     "view, plain neutral grey studio backdrop, soft even lighting, sharp "
     "focus, photorealistic"),
]
NEG = (
    "lowres, low quality, worst quality, cropped feet, cropped legs, "
    "head-and-shoulders, bust shot, close-up, partial body, deformed, "
    "mutated, ugly, watermark, text, logo, multiple people, illustrative, "
    "painting, drawing, cartoon"
)


def main() -> None:
    if not LORA_DIR.exists():
        sys.exit(f"LoRA v2 dir missing: {LORA_DIR}. Run train_lora_v2.sh first.")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

    print("Loading SDXL base …")
    pipe = StableDiffusionXLPipeline.from_pretrained(
        "stabilityai/stable-diffusion-xl-base-1.0",
        torch_dtype=torch.float16,
    )
    print(f"Loading LoRA v2 weights from {LORA_DIR}")
    pipe.load_lora_weights(str(LORA_DIR))
    try:
        pipe.enable_model_cpu_offload()
    except Exception:
        pipe.to("cuda")
    try:
        pipe.vae.enable_slicing()
        pipe.vae.enable_tiling()
    except Exception:
        pass

    for i, (label, prompt) in enumerate(PROMPTS):
        out = OUT_DIR / f"{i+1:02d}_{label}.png"
        print(f"\n→ {out.name}")
        gen = torch.Generator(device="cpu").manual_seed(2000 + i)
        image = pipe(
            prompt=prompt, negative_prompt=NEG,
            num_inference_steps=50, guidance_scale=7.0,
            height=1024, width=768, generator=gen,
        ).images[0]
        image.save(out)
        print(f"  saved → {out}")

    print("\nOutputs:")
    for f in sorted(OUT_DIR.iterdir()):
        size_kb = f.stat().st_size // 1024
        print(f"  {f.name}  ({size_kb} KB)")


if __name__ == "__main__":
    main()
