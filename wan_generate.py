#!/usr/bin/env python3
"""Phantom-Wan 14B video generation — in-process runner with FP8 layerwise
casting + CPU offload, designed to fit on a single 16 GB GPU.

Mirrors the LTX FP8 path:
  - Load Phantom WanModel weights to CPU first (avoids 30 GB GPU OOM at load).
  - Apply diffusers' apply_layerwise_casting(storage=fp8_e4m3fn, compute=bf16)
    → ~14 GB resident on GPU instead of ~28 GB.
  - Keep T5 text encoder on CPU (~5 GB freed).
  - VAE is small (~1 GB) — stays on GPU.

The class subclasses upstream Phantom_Wan_S2V and replaces the model-load
section. generate() is inherited unchanged.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

# Lock GPU env BEFORE torch import (so PCI bus order is honored).
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
os.environ.setdefault("CUDA_DEVICE_ORDER", "PCI_BUS_ID")

import torch  # noqa: E402

PHANTOM_REPO = Path(os.environ.get("PHANTOM_REPO", str(Path.home() / "Phantom")))
WAN_BASE_CKPT = Path(os.environ.get("WAN_BASE_CKPT", str(Path.home() / "Wan2.1-T2V-1.3B")))
PHANTOM_CKPT = Path(os.environ.get("PHANTOM_CKPT", str(Path.home() / "Phantom-Wan-Models")))

if str(PHANTOM_REPO) not in sys.path:
    sys.path.insert(0, str(PHANTOM_REPO))


def _load_state_to_cpu(phantom_ckpt: str) -> dict:
    """Load Phantom checkpoint to CPU (NOT GPU) to avoid OOM at load.
    Handles both .pth (1.3B) and sharded safetensors (14B)."""
    from safetensors.torch import load_file
    if phantom_ckpt.endswith(".pth"):
        return torch.load(phantom_ckpt, map_location="cpu")
    # 14B sharded safetensors — read index, load each shard to CPU.
    p = Path(phantom_ckpt)
    base = "Phantom_Wan_14B"
    idx = p / f"{base}.safetensors.index.json"
    with open(idx) as f:
        weight_map = json.load(f)["weight_map"]
    shards = sorted(set(weight_map.values()))
    state = {}
    for shard in shards:
        logging.info(f"  loading shard {shard} to CPU...")
        shard_state = load_file(str(p / shard), device="cpu")
        state.update(shard_state)
    return state


def _build_phantom(args, device_id: int):
    """Build Phantom_Wan_S2V — multi-GPU dispatch if multiple visible, else
    single-GPU FP8 layerwise.

    Multi-GPU mode (preferred when 2+ GPUs available):
      - bf16 weights split across cuda:0 + cuda:1 via accelerate.dispatch_model
      - More headroom (combined VRAM), simpler mental model, faster per-step
    Single-GPU mode (fallback):
      - FP8 layerwise storage + bf16 compute (LTX recipe)
      - DiT kept on CPU until upstream's offload_model swaps it in for sampling
      - VAE pre-encoded then offloaded to free GPU room for DiT activations
    """
    import phantom_wan
    from phantom_wan.configs import WAN_CONFIGS
    from phantom_wan.modules.model import WanModel
    from phantom_wan.modules.t5 import T5EncoderModel
    from phantom_wan.modules.vae import WanVAE

    cfg = WAN_CONFIGS[args.task]
    if args.fps:
        cfg.sample_fps = args.fps

    n_gpus = torch.cuda.device_count()
    multi_gpu = n_gpus >= 2 and not args.single_gpu
    logging.info(f"Visible GPUs: {n_gpus} → mode={'multi-GPU dispatch (bf16)' if multi_gpu else 'single-GPU FP8'}")

    device = torch.device(f"cuda:{device_id}")
    obj = phantom_wan.Phantom_Wan_S2V.__new__(phantom_wan.Phantom_Wan_S2V)
    obj.device = device
    obj.config = cfg
    obj.rank = 0
    obj.t5_cpu = True       # always offload T5 — saves ~5 GB
    obj.num_train_timesteps = cfg.num_train_timesteps
    obj.param_dtype = cfg.param_dtype
    obj.sp_size = 1
    obj.sample_neg_prompt = cfg.sample_neg_prompt
    obj.vae_stride = cfg.vae_stride
    obj.patch_size = cfg.patch_size

    logging.info("Loading T5 text encoder (kept on CPU)...")
    obj.text_encoder = T5EncoderModel(
        text_len=cfg.text_len,
        dtype=cfg.t5_dtype,
        device=torch.device("cpu"),
        checkpoint_path=os.path.join(args.ckpt_dir, cfg.t5_checkpoint),
        tokenizer_path=os.path.join(args.ckpt_dir, cfg.t5_tokenizer),
        shard_fn=None,
    )

    logging.info("Loading VAE on GPU (small, stays resident)...")
    obj.vae = WanVAE(
        vae_pth=os.path.join(args.ckpt_dir, cfg.vae_checkpoint),
        device=device,
    )

    logging.info("Building WanModel (uninitialized, on CPU)...")
    obj.model = WanModel(
        dim=cfg.dim, ffn_dim=cfg.ffn_dim, freq_dim=cfg.freq_dim,
        num_heads=cfg.num_heads, num_layers=cfg.num_layers,
        window_size=cfg.window_size, qk_norm=cfg.qk_norm,
        cross_attn_norm=cfg.cross_attn_norm, eps=cfg.eps,
    )

    logging.info(f"Loading Phantom checkpoint from {args.phantom_ckpt} to CPU...")
    state = _load_state_to_cpu(args.phantom_ckpt)
    missing, unexpected = obj.model.load_state_dict(state, strict=False)
    logging.info(f"  loaded ({len(missing)} missing, {len(unexpected)} unexpected keys)")
    obj.model.eval().requires_grad_(False)
    del state
    import gc; gc.collect()

    if multi_gpu:
        from accelerate import dispatch_model, infer_auto_device_map
        # Phantom's rope_apply uses torch.view_as_complex which doesn't accept
        # bf16. Patch it to upcast to fp32 around the complex op, then back.
        import phantom_wan.modules.model as _wm
        _orig_rope = _wm.rope_apply
        def _patched_rope(x, grid_sizes, freqs):
            # Move freqs to wherever x lives. With dispatch_model, x can be on
            # cuda:0 OR cuda:1 depending which transformer block is forwarding,
            # but `freqs` is a single buffer pinned to one device. Cross-device
            # multiplication in view_as_complex causes CUDA illegal memory access.
            freqs = freqs.to(x.device)
            grid_sizes = grid_sizes.to(x.device) if hasattr(grid_sizes, "to") else grid_sizes
            return _orig_rope(x.to(torch.float32), grid_sizes, freqs).to(x.dtype)
        _wm.rope_apply = _patched_rope
        # Phantom calls flash_attention() directly which asserts
        # FLASH_ATTN_2_AVAILABLE. flash-attn isn't installed in this env;
        # redirect to the `attention()` wrapper that falls back to PyTorch SDPA.
        from phantom_wan.modules import attention as _attn_mod
        _wm.flash_attention = _attn_mod.attention

        # Weight precision: bf16 (28 GB total) or FP8 layerwise (14 GB) for
        # longer sequences where activation memory is the bottleneck.
        use_fp8 = os.environ.get("WAN_FP8", "0") == "1"
        if use_fp8:
            from diffusers.hooks.layerwise_casting import apply_layerwise_casting
            logging.info("FP8 layerwise + multi-GPU dispatch (storage=fp8_e4m3fn, compute=bf16)")
            apply_layerwise_casting(
                obj.model,
                storage_dtype=torch.float8_e4m3fn,
                compute_dtype=torch.bfloat16,
                skip_modules_pattern=(
                    "patch_embedding", "norm", "head", "img_emb", "text_emb", "time_embedding",
                ),
                non_blocking=True,
            )
            infer_dtype = torch.float8_e4m3fn
        else:
            obj.model = obj.model.to(dtype=torch.bfloat16)
            infer_dtype = torch.bfloat16

        # Each GPU's max_memory needs headroom for activations + VAE + overheads.
        # bf16 dispatch:  default 11 GiB / 9 GiB (works ≤33 frames).
        # FP8 dispatch:   default 8 GiB / 6 GiB (weights halved → activations
        #                 get ~3-4 GB extra headroom on each GPU). Tested for
        #                 65+ frames at 832×480.
        if use_fp8:
            max_gpu0 = os.environ.get("WAN_MAX_GPU0", "8GiB")
            max_gpu1 = os.environ.get("WAN_MAX_GPU1", "6GiB")
        else:
            max_gpu0 = os.environ.get("WAN_MAX_GPU0", "11GiB")
            max_gpu1 = os.environ.get("WAN_MAX_GPU1", "9GiB")
        max_memory = {0: max_gpu0, 1: max_gpu1, "cpu": "60GiB"}
        # WanAttentionBlock-level no-split keeps each transformer block on a single GPU.
        no_split = ["WanAttentionBlock"]
        try:
            device_map = infer_auto_device_map(
                obj.model, max_memory=max_memory, no_split_module_classes=no_split,
                dtype=infer_dtype,
            )
        except TypeError:  # older accelerate signature
            device_map = infer_auto_device_map(
                obj.model, max_memory=max_memory, no_split_module_classes=no_split,
            )
        on_gpu = sum(1 for v in device_map.values() if v != "cpu")
        on_cpu = sum(1 for v in device_map.values() if v == "cpu")
        logging.info(f"dispatch device_map: {on_gpu} modules on GPU, {on_cpu} on CPU")
        obj.model = dispatch_model(obj.model, device_map)
        # Upstream Phantom_Wan_S2V.generate() unconditionally calls
        # `self.model.to(self.device)` at the start of every diffusion step
        # (subject2video.py:291) — accelerate forbids `.to()` on dispatched
        # models (raises RuntimeError). No-op the call: dispatch_model hooks
        # already place each layer on its assigned device.
        def _noop_to(*a, **kw):
            return obj.model
        obj.model.to = _noop_to
        # Same for .cpu() if offload_model accidentally triggers it.
        obj.model.cpu = lambda *a, **kw: obj.model
        if hasattr(torch.cuda, "empty_cache"):
            torch.cuda.empty_cache()
        for did in range(n_gpus):
            free, total = torch.cuda.mem_get_info(did)
            logging.info(f"  GPU{did} after dispatch: {(total - free)/1e9:.1f} GB used / {total/1e9:.1f} GB total")
    else:
        from diffusers.hooks.layerwise_casting import apply_layerwise_casting
        logging.info("Applying FP8 layerwise casting (storage=fp8_e4m3fn, compute=bf16)...")
        apply_layerwise_casting(
            obj.model,
            storage_dtype=torch.float8_e4m3fn,
            compute_dtype=torch.bfloat16,
            skip_modules_pattern=("patch_embedding", "norm", "head", "img_emb", "text_emb", "time_embedding"),
            non_blocking=True,
        )
        # DiT kept on CPU; upstream offload_model=True swaps it for sampling.
        logging.info("DiT on CPU (single-GPU FP8 mode; offload_model swaps for sampling).")
        if hasattr(torch.cuda, "empty_cache"):
            torch.cuda.empty_cache()
        free, total = torch.cuda.mem_get_info(device_id)
        logging.info(f"GPU{device_id} after model load (DiT on CPU): {(total - free)/1e9:.1f} GB used / {total/1e9:.1f} GB total")

    obj._multi_gpu = multi_gpu  # used to skip CPU-offload tricks downstream
    return obj


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Phantom-Wan 14B FP8 layerwise generator")
    p.add_argument("--prompt", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--ref-image", action="append", default=[], help="up to 4")
    p.add_argument("--task", default="s2v-14B", choices=["s2v-1.3B", "s2v-14B"])
    p.add_argument("--width", type=int, default=832)
    p.add_argument("--height", type=int, default=480)
    p.add_argument("--num-frames", type=int, default=81)
    p.add_argument("--fps", type=int, default=16)
    p.add_argument("--steps", type=int, default=50)
    p.add_argument("--guidance-text", type=float, default=7.5)
    p.add_argument("--guidance-img", type=float, default=5.0)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--ckpt-dir", default=str(WAN_BASE_CKPT))
    p.add_argument("--phantom-ckpt", default=str(PHANTOM_CKPT))
    p.add_argument("--device-id", type=int, default=0,
                   help="CUDA device. Set CUDA_VISIBLE_DEVICES first to remap.")
    p.add_argument("--single-gpu", action="store_true",
                   help="Force single-GPU FP8 mode even when 2+ GPUs are visible.")
    return p.parse_args()


def main() -> int:
    logging.basicConfig(level=logging.INFO,
                        format="[%(asctime)s] %(levelname)s: %(message)s")
    args = parse_args()

    if not (1 <= len(args.ref_image) <= 4):
        print(f"ERROR: need 1-4 --ref-image (got {len(args.ref_image)})", file=sys.stderr)
        return 1
    for ref in args.ref_image:
        if not Path(ref).exists():
            print(f"ERROR: ref image not found: {ref}", file=sys.stderr)
            return 1
    if not PHANTOM_REPO.exists():
        print(f"ERROR: PHANTOM_REPO not found: {PHANTOM_REPO}", file=sys.stderr)
        return 1
    if not Path(args.ckpt_dir).exists():
        print(f"ERROR: Wan base ckpt missing: {args.ckpt_dir}", file=sys.stderr)
        return 1
    if not Path(args.phantom_ckpt).exists():
        print(f"ERROR: Phantom ckpt missing: {args.phantom_ckpt}", file=sys.stderr)
        return 1

    n = args.num_frames
    if (n - 1) % 4 != 0:
        n = ((n - 1) // 4) * 4 + 1
        logging.info(f"snapped num_frames to {n} (Wan requires 4n+1)")

    from PIL import Image, ImageOps
    from phantom_wan.configs import SIZE_CONFIGS
    from phantom_wan.utils.utils import cache_video

    size_key = f"{args.width}*{args.height}"
    if size_key not in SIZE_CONFIGS:
        logging.warning(f"size {size_key} not in SIZE_CONFIGS; using closest 832*480")
        size_key = "832*480"
    size = SIZE_CONFIGS[size_key]

    # Pad ref images to target ratio (mirror upstream load_ref_images).
    def _pad(path: str):
        with Image.open(path) as img:
            img = img.convert("RGB")
            w, h = size[0], size[1]
            ir = img.width / img.height
            tr = w / h
            if ir > tr:
                nw, nh = w, int(w / ir)
            else:
                nh, nw = h, int(h * ir)
            img = img.resize((nw, nh), Image.Resampling.LANCZOS)
            dw, dh = w - nw, h - nh
            return ImageOps.expand(img, (dw // 2, dh // 2, dw - dw // 2, dh - dh // 2),
                                   fill=(255, 255, 255))
    ref_pils = [_pad(p) for p in args.ref_image]

    obj = _build_phantom(args, args.device_id)

    # F-VAE-ON-CPU: was needed when bf16 dispatch packed both GPUs (15.1+11.5
    # of 16+12). With FP8 layerwise + dispatch the GPU footprint is 9.5/6.6 —
    # plenty of headroom to leave VAE on GPU 1 (~1 GB), saving ~7-9 min of CPU
    # decode per scene. Only force VAE→CPU in the bf16 path.
    use_fp8 = os.environ.get("WAN_FP8", "0") == "1"
    if obj._multi_gpu and torch.cuda.device_count() >= 2 and not use_fp8:
        logging.info("Moving VAE to CPU (bf16 dispatch packs both GPUs — encode/decode will be slow)...")
        obj.vae.model.cpu()
        obj.vae.device = torch.device("cpu")
        # WanVAE also stores mean/std/scale tensors on the original device.
        # Move those too — encode/decode applies `(mu - scale[0]) * scale[1]`
        # which fails with device-mismatch if scale is on cuda:0 but mu on CPU.
        if hasattr(obj.vae, "mean"):
            obj.vae.mean = obj.vae.mean.cpu()
        if hasattr(obj.vae, "std"):
            obj.vae.std = obj.vae.std.cpu()
        if hasattr(obj.vae, "scale"):
            obj.vae.scale = [obj.vae.mean, 1.0 / obj.vae.std]
        _orig_encode = obj.vae.encode
        def _enc(videos, *a, **kw):
            videos = [v.cpu() for v in videos]
            with torch.no_grad():
                out = _orig_encode(videos, *a, **kw)
            return [t.to(obj.device) for t in out]
        obj.vae.encode = _enc
        _orig_decode = obj.vae.decode
        def _dec(latents, *a, **kw):
            latents = [t.cpu() for t in latents]
            with torch.no_grad():
                out = _orig_decode(latents, *a, **kw)
            return [t.to(obj.device) for t in out] if isinstance(out, list) else out.to(obj.device)
        obj.vae.decode = _dec
        free0, total0 = torch.cuda.mem_get_info(0)
        free1, total1 = torch.cuda.mem_get_info(1)
        logging.info(f"After VAE→CPU: GPU0 {(total0-free0)/1e9:.1f}/{total0/1e9:.1f} GB, GPU1 {(total1-free1)/1e9:.1f}/{total1/1e9:.1f} GB")
    elif obj._multi_gpu and use_fp8:
        # FP8 + multi-GPU: 14B fits as ~14 GB across both GPUs (9.5/6.6) —
        # leaves room for VAE on GPU 1 (~1 GB). Skip the CPU dance entirely.
        logging.info("FP8 multi-GPU: VAE stays on GPU (encode/decode at full speed).")
    else:
        # Single-GPU FP8 fallback (16 GB only): pre-encode then park VAE on CPU.
        logging.info("Single-GPU mode: pre-encoding refs, parking VAE on CPU...")
        ref_latents = obj.get_vae_latents(ref_pils, obj.device)
        obj.vae.model.cpu()
        if hasattr(torch.cuda, "empty_cache"):
            torch.cuda.empty_cache()
        _precomputed = ref_latents
        obj.get_vae_latents = lambda *a, **kw: _precomputed
        _orig_decode = obj.vae.decode
        def _wrapped_decode(*a, **kw):
            obj.vae.model.to(obj.device)
            return _orig_decode(*a, **kw)
        obj.vae.decode = _wrapped_decode

    # offload_model=True only matters in single-GPU mode; in multi-GPU dispatch
    # the model layers stay where dispatch_model put them.
    use_offload = not obj._multi_gpu

    logging.info(f"generate(): prompt={args.prompt[:80]!r}...")
    video = obj.generate(
        args.prompt,
        ref_pils,
        size=size,
        frame_num=n,
        shift=5.0,
        sample_solver="unipc",
        sampling_steps=args.steps,
        guide_scale_img=args.guidance_img,
        guide_scale_text=args.guidance_text,
        seed=args.seed,
        offload_model=use_offload,
    )

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    cache_video(
        tensor=video[None],
        save_file=args.output,
        fps=obj.config.sample_fps,
        nrow=1, normalize=True, value_range=(-1, 1),
    )
    logging.info(f"saved {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
