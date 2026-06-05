#!/usr/bin/env python3
"""End-to-end driver: prompt → catalog lookup → generate → optional post-process.

Validates the LoRA dictionary in docs/runs/wan22-eval/lora_catalog.yaml.

Usage: wan22_smart_generate.py "<prompt>" [output_name]
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from pathlib import Path

os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

import torch
import yaml
from diffusers import WanPipeline
from diffusers.utils import export_to_video

REPO = Path("/home/akash/PycharmProjects/video-app")
CATALOG_PATH = REPO / "docs/runs/wan22-eval/lora_catalog.yaml"
MODEL_DIR = "/home/akash/Wan2.2-Models/TI2V-5B-Diffusers"
LORA_DIR = Path("/home/akash/Wan2.2-Models/loras/5b")
OUT_DIR = REPO / "docs/runs/wan22-eval/smart_gen"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def load_catalog() -> dict:
    return yaml.safe_load(CATALOG_PATH.read_text())


_SUFFIXES = ("", "s", "es", "ed", "ing")


def _match_any(tags: list[str], prompt_lower: str, words: list[str]) -> bool:
    """Match if any word equals tag or tag+{s,es,ed,ing}. Avoids 'warm' matching 'war'."""
    for tag in tags:
        if " " in tag:
            if tag in prompt_lower:
                return True
            continue
        for w in words:
            for suf in _SUFFIXES:
                if w == tag + suf:
                    return True
    return False


def classify(prompt: str, cat: dict) -> tuple[str, str]:
    """Return (scene_type, shot_type). Shot defaults to scene_type's default_shot."""
    pl = prompt.lower()
    words = re.findall(r"[a-z]+", pl)
    scene_type = "closeup_portrait"
    for st, tags in cat["tag_index"].items():
        if _match_any(tags, pl, words):
            scene_type = st
            break
    shot_type = cat["scene_map"][scene_type].get("default_shot", "medium")
    for st, tags in cat.get("shot_index", {}).items():
        if _match_any(tags, pl, words):
            shot_type = st
            break
    return scene_type, shot_type


def run_post_process(in_mp4: Path, out_mp4: Path, fidelity: float = 0.5):
    """Run CodeFormer+ESRGAN post-process. Used for wide shots."""
    script = REPO / "scripts/wan22_face_restore_codeformer.py"
    subprocess.run(["/home/akash/.pyenv/versions/video-app/bin/python", str(script),
                    str(in_mp4), str(out_mp4), str(fidelity)], check=True)


def main():
    if len(sys.argv) < 2:
        print('usage: wan22_smart_generate.py "<prompt>" [output_name]')
        sys.exit(2)
    prompt = sys.argv[1]
    name = sys.argv[2] if len(sys.argv) > 2 else f"gen_{int(time.time())}"

    cat = load_catalog()
    scene_type, shot_type = classify(prompt, cat)
    sm = cat["scene_map"][scene_type]
    lora_id = sm["primary"]["lora"]
    weight = sm["primary"]["weight"]
    lora_file = cat["loras"][lora_id]["file"]
    do_post_process = shot_type == "wide"  # only wide shots get face restoration

    gd = cat["generation_defaults"]
    print(f"prompt: {prompt}")
    print(f"  -> scene_type:  {scene_type}")
    print(f"  -> shot_type:   {shot_type}")
    print(f"  -> lora:        {lora_id} @ {weight}")
    print(f"  -> file:        {lora_file}")
    print(f"  -> post-process: {'codeformer_esrgan' if do_post_process else 'none'}")

    out_mp4 = OUT_DIR / f"{name}__{scene_type}__{shot_type}__{lora_id}__w{weight}.mp4"
    print(f"  -> output:      {out_mp4.name}")

    print(f"[{time.strftime('%H:%M:%S')}] loading WanPipeline")
    pipe = WanPipeline.from_pretrained(MODEL_DIR, torch_dtype=torch.bfloat16)
    pipe.enable_model_cpu_offload()
    if lora_file:
        pipe.load_lora_weights(str(LORA_DIR / lora_file), adapter_name=lora_id)
        pipe.set_adapters([lora_id], adapter_weights=[weight])

    t0 = time.time()
    print(f"[{time.strftime('%H:%M:%S')}] generating {gd['width']}x{gd['height']} {gd['num_frames']}f @ {gd['steps']} steps")
    gen = torch.Generator(device="cuda").manual_seed(1234)
    res = pipe(prompt=prompt, negative_prompt=gd["negative_prompt"],
               height=gd["height"], width=gd["width"], num_frames=gd["num_frames"],
               num_inference_steps=gd["steps"], guidance_scale=gd["guidance_scale"],
               generator=gen)
    export_to_video(res.frames[0], str(out_mp4), fps=gd["fps"])
    print(f"[{time.strftime('%H:%M:%S')}] generation done in {time.time()-t0:.1f}s")

    if do_post_process:
        # Release GPU memory before post-process loads its models
        del pipe
        import gc, torch as _t
        gc.collect()
        if _t.cuda.is_available():
            _t.cuda.empty_cache()
        pp_out = out_mp4.with_name(out_mp4.stem + "__postproc.mp4")
        print(f"[{time.strftime('%H:%M:%S')}] post-process -> {pp_out.name}")
        run_post_process(out_mp4, pp_out)
        print(f"[{time.strftime('%H:%M:%S')}] all done -> {pp_out}")
    else:
        print(f"[{time.strftime('%H:%M:%S')}] all done -> {out_mp4}")


if __name__ == "__main__":
    main()
