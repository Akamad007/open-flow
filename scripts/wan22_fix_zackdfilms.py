#!/usr/bin/env python3
"""Remap zackdfilms LoRA keys to the diffusers Wan convention.

Source format:  blocks.0.cross_attn.k.lora_A.default.weight
Target format:  diffusion_model.blocks.0.cross_attn.k.lora_A.weight
"""
import os

from safetensors.torch import load_file, save_file

SRC = os.getenv("LORA_SRC", os.path.expanduser("~/models/wan22/loras/5b/zackdfilms_5b.safetensors"))
DST = os.getenv("LORA_DST", os.path.expanduser("~/models/wan22/loras/5b/zackdfilms_5b_fixed.safetensors"))

state = load_file(SRC)
fixed = {}
for k, v in state.items():
    nk = "diffusion_model." + k
    nk = nk.replace(".lora_A.default.weight", ".lora_A.weight")
    nk = nk.replace(".lora_B.default.weight", ".lora_B.weight")
    fixed[nk] = v
save_file(fixed, DST)
print(f"remapped {len(state)} keys -> {DST}")
print(f"sample: {next(iter(state))} -> {next(iter(fixed))}")
