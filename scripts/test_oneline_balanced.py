#!/usr/bin/env python3
import os
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
os.environ.setdefault("CUDA_DEVICE_ORDER", "PCI_BUS_ID")

import sys
import time
import torch
from pathlib import Path
from diffusers import LTXPipeline
from diffusers.utils import export_to_video
from huggingface_hub import hf_hub_download
from transformers import T5EncoderModel

MODEL = "Lightricks/LTX-Video"
MODEL_FILE = "ltxv-13b-0.9.8-dev-fp8.safetensors"
OUT = Path(__file__).parent.parent / "storage" / "oneline_balanced_13b_test.mp4"
OUT.parent.mkdir(parents=True, exist_ok=True)

PROMPT = (
    "A red panda eating bamboo on a tree branch, sharp focus, cinematic, "
    "locked-off camera, tripod stable, static shot"
)
NEG = "blurry, low quality, distorted, watermark, text, camera shake"


def vram_report(label):
    print(f"\n[{label}]")
    for i in range(torch.cuda.device_count()):
        free, total = torch.cuda.mem_get_info(i)
        used = (total - free) / 1024**3
        print(f"  cuda:{i}  used={used:5.2f} GiB / {total/1024**3:5.2f} GiB")


def main():
    if torch.cuda.device_count() < 2:
        print("Need 2 GPUs for balanced test")
        return 1

    vram_report("baseline (before load)")

    print(f"\nResolving FP8 checkpoint: {MODEL_FILE}")
    ckpt_path = hf_hub_download(repo_id=MODEL, filename=MODEL_FILE)
    print(f"  -> {ckpt_path}")

    print("Loading T5 text encoder (bf16)...")
    text_encoder = T5EncoderModel.from_pretrained(
        MODEL, subfolder="text_encoder", torch_dtype=torch.bfloat16
    )

    print("\nLoading LTXPipeline.from_single_file with device_map='balanced' (one-liner)...")
    t0 = time.time()
    try:
        pipe = LTXPipeline.from_single_file(
            ckpt_path,
            text_encoder=text_encoder,
            torch_dtype=torch.bfloat16,
            device_map="balanced",
        )
    except Exception as e:
        print(f"\nLOAD FAILED: {type(e).__name__}: {e}")
        vram_report("after failed load")
        return 2
    print(f"loaded in {time.time()-t0:.1f}s")

    pipe.vae.enable_tiling()
    pipe.vae.enable_slicing()
    vram_report("after load")

    print("\nGenerating 25-frame test (480x704, 30 steps)...")
    gen = torch.Generator(device="cpu").manual_seed(42)
    t0 = time.time()
    try:
        result = pipe(
            prompt=PROMPT,
            negative_prompt=NEG,
            height=480,
            width=704,
            num_frames=25,
            num_inference_steps=30,
            guidance_scale=3.5,
            decode_timestep=0.05,
            decode_noise_scale=0.025,
            generator=gen,
            max_sequence_length=512,
        )
    except Exception as e:
        print(f"\nGENERATE FAILED: {type(e).__name__}: {e}")
        vram_report("after failed generate")
        return 3

    print(f"generated in {time.time()-t0:.1f}s")
    vram_report("after generate")

    export_to_video(result.frames[0], str(OUT), fps=12)
    print(f"\nSaved: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
