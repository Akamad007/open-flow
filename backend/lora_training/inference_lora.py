"""Inference smoke test for the trained SDXL DreamBooth-LoRA.

Loads SDXL base + the LoRA weights from `lora_runner_man/`, then renders
4 images of the trained character in different poses using the unique
token "ohwx man". Compares visually to the InstantID dual-CN outputs to
see whether the LoRA captured identity well enough to skip the
dual-ControlNet pipeline at inference time.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import torch
from diffusers import StableDiffusionXLPipeline

OUT_DIR = Path(__file__).parent / "lora_inference_smoke"
LORA_DIR = Path(__file__).parent / "lora_runner_man"

PROMPTS = [
    ("standing_neutral",
     "ohwx man, full-body photo, athletic young man with short dark brown "
     "hair wearing a charcoal grey performance tee, dark technical shorts, "
     "and white athletic trainers, standing in a neutral upright pose, "
     "three-quarter front view, plain neutral grey studio backdrop, soft "
     "even lighting, sharp focus, photorealistic"),
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
     "bent, arms raised, side profile, feet clearly off ground, plain "
     "neutral grey studio backdrop, soft even lighting, sharp focus, "
     "photorealistic"),
]
NEG = (
    "lowres, low quality, worst quality, cropped feet, cropped legs, "
    "head-and-shoulders, bust shot, close-up, partial body, deformed, "
    "mutated, ugly, watermark, text, logo, multiple people"
)


def main() -> None:
    if not LORA_DIR.exists():
        sys.exit(f"LoRA dir missing: {LORA_DIR}. Run train_lora.sh first.")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

    print("Loading SDXL base …")
    pipe = StableDiffusionXLPipeline.from_pretrained(
        "stabilityai/stable-diffusion-xl-base-1.0",
        torch_dtype=torch.float16,
    )
    print(f"Loading LoRA weights from {LORA_DIR}")
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
        out = OUT_DIR / f"0{i+1}_{label}.png"
        print(f"\n→ {out.name}")
        gen = torch.Generator(device="cpu").manual_seed(1000 + i)
        image = pipe(
            prompt=prompt, negative_prompt=NEG,
            num_inference_steps=40, guidance_scale=6.5,
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
