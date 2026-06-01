#!/usr/bin/env python3
import os

os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
# PCI bus order = nvidia-smi order (keeps the larger GPU as cuda:0). Must be
# set before torch is imported below.
os.environ.setdefault("CUDA_DEVICE_ORDER", "PCI_BUS_ID")
"""
Generate a video with LTX-Video on Linux + NVIDIA CUDA.

Supports two modes:
  1. Text-to-Video (T2V): standard generation from prompt alone
  2. Image-to-Video (I2V): condition on a first frame image for continuity

Examples:
    # T2V
    python ltx_generate.py --prompt "..." --output out.mp4

    # I2V (for scene continuity — feed last frame of previous scene)
    python ltx_generate.py --prompt "..." --condition-image prev_last_frame.png --output out.mp4

    # Extract last frame from a video (for chaining scenes)
    python ltx_generate.py --extract-last-frame scene_001.mp4 --output last_frame.png
"""

import argparse
import sys
import torch
from pathlib import Path
from PIL import Image

# ── Quality Suffix ────────────────────────────────────────────────────────────────
# Appended to prompts unless --no-enhance is used
QUALITY_SUFFIX = (
    ", masterpiece quality, sharp focus, smooth fluid motion, "
    "no compression artifacts, ultra detailed, cinematic, "
    "locked-off camera, tripod stable, static shot, character fully visible"
)

# ── Default Negative Prompt ────────────────────────────────────────────────────────────
DEFAULT_NEGATIVE_PROMPT = (
    "worst quality, low quality, bad quality, "
    "blurry, out of focus, grainy noise, "
    "pixelated, compressed, watermark, text, logo, "
    "overexposed, underexposed, flat shading, "
    "inconsistent motion, jittery, flickering, stuttering, "
    "distorted anatomy, deformed limbs, extra limbs, missing limbs, "
    "bad proportions, disfigured, mutated, "
    "ghosting, translucent body, misty figure, see-through character, "
    "ghostly hands, blurry fingers, misty hands, melting fingers, extra fingers, "
    "double exposure, motion blur on person, dissolving body, "
    "camera zoom, camera dolly, camera pan, camera drift, "
    "camera shake, handheld shake, moving camera, zooming in, zooming out, "
    "anime, manga, cartoon, 3d render, cgi, "
    "low detail, temporal inconsistency, warping, morphing"
)

# I2V guidance scale — lower than T2V to avoid fighting the conditioning frame
I2V_GUIDANCE_SCALE = 2.5


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Generate video with LTX-Video (T2V and I2V modes)"
    )
    p.add_argument("--prompt", help="Text prompt (required for generation)")
    p.add_argument("--output", default="output.mp4", help="Output mp4 or png path")
    p.add_argument("--model", default="Lightricks/LTX-Video", help="HF model id")
    p.add_argument("--height", type=int, default=480)
    p.add_argument("--width", type=int, default=704)
    # 73 frames @ 12fps = ~6s. Must be 8k+1: 25, 49, 73, 97, 121, 161, 193...
    p.add_argument(
        "--num-frames",
        type=int,
        default=73,
        help="Frame count (must be 8k+1: 25,49,73,97,121,161,193)",
    )
    p.add_argument("--fps", type=int, default=12, help="Export fps")
    p.add_argument(
        "--num-inference-steps",
        type=int,
        default=80,
        help="Denoising steps — 60-80 for quality",
    )
    p.add_argument(
        "--guidance-scale",
        type=float,
        default=3.5,
        help="CFG scale — 3.0-4.0 recommended; higher values cause subject instability",
    )
    p.add_argument("--seed", type=int, default=42)
    p.add_argument(
        "--negative-prompt", default=None, help="Override default negative prompt"
    )
    p.add_argument(
        "--no-enhance",
        action="store_true",
        help="Disable automatic quality suffix and anime prefix",
    )
    # I2V mode
    p.add_argument(
        "--condition-image",
        default=None,
        help="Path to conditioning image (first frame) for I2V mode. "
        "Enables LTXImageToVideoPipeline for scene continuity.",
    )
    p.add_argument(
        "--character-image",
        default=None,
        help="Path to character portrait image. Composited over --background-image to form the conditioning frame.",
    )
    p.add_argument(
        "--scene-action-image",
        default=None,
        help="Path to scene action still (character performing scene action). Added as extra condition.",
    )
    p.add_argument(
        "--scene-action-image-2",
        default=None,
        help="Path to secondary action still (different pose/beat). Added as an additional condition.",
    )
    p.add_argument(
        "--scene-action-images",
        nargs="+",
        default=None,
        metavar="IMG",
        help="Multiple action still images placed at 1-second intervals (s1, s2, s3...). "
             "Overrides --scene-action-image / --scene-action-image-2 when provided.",
    )
    p.add_argument(
        "--background-image",
        default=None,
        help="Path to background scene image. Used as the base layer when compositing with --character-image.",
    )
    # Frame extraction utility
    p.add_argument(
        "--extract-last-frame",
        default=None,
        help="Extract last frame from this video file and save to --output as PNG",
    )
    p.add_argument(
        "--device",
        default=None,
        help="Force device: 'cuda', 'cpu', or 'hybrid'. Default: auto-detect CUDA, fall back to CPU.",
    )
    p.add_argument(
        "--model-file",
        default=None,
        help="Specific safetensors filename within the model repo (e.g. ltxv-13b-0.9.8-dev-fp8.safetensors). "
        "When set, uses from_single_file loading instead of from_pretrained.",
    )
    # LoRA scale overrides (for sweep / ablation testing)
    p.add_argument("--pose-scale",      type=float, default=0.5,
                   help="IC-LoRA Pose Control scale (0.0–1.0, default 0.5)")
    p.add_argument("--depth-scale",     type=float, default=0.5,
                   help="IC-LoRA Depth Control scale (0.0–1.0, default 0.5)")

    p.add_argument("--snorricam-scale", type=float, default=1.0,
                   help="Snorricam Camera Style scale (0.0–1.0, default 1.0)")
    return p.parse_args()


def extract_last_frame(video_path: str, output_path: str) -> int:
    """Extract the last frame of a video and save as PNG."""
    import cv2

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"ERROR: Cannot open video: {video_path}", file=sys.stderr)
        return 1
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, total_frames - 1))
    ret, frame = cap.read()
    cap.release()
    if not ret:
        print("ERROR: Could not read last frame", file=sys.stderr)
        return 1
    # Convert BGR → RGB and save
    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    Image.fromarray(frame_rgb).save(output_path)
    print(f"Extracted last frame ({total_frames} frames total) → {output_path}")
    return 0


def _load_adapter_stack(pipe, pose_scale: float = 0.5, depth_scale: float = 0.5, snorricam_scale: float = 1.0):
    """
    Fuse IC-LoRA adapter stack into any LTX transformer.
    Baked into weights via fuse_lora() so they work with
    LTXPipeline, LTXImageToVideoPipeline, and LTXConditionPipeline alike.
    Must be called BEFORE FP8 layerwise casting.
    """

    def _fuse(repo, filename, label, scale=1.0):
        if scale == 0.0:
            print(f"  \u25cb {label} skipped (scale=0.0)")
            return
        try:
            from huggingface_hub import try_to_load_from_cache

            cached = try_to_load_from_cache(repo, filename)
            if cached and Path(str(cached)).exists():
                print(f"  Fusing {label} (scale={scale})...")
                pipe.load_lora_weights(repo, weight_name=filename)
                pipe.fuse_lora(lora_scale=scale)
                pipe.unload_lora_weights()
                print(f"  \u2713 {label} fused")
            else:
                print(f"  \u25cb {label} not cached \u2014 skipping")
        except Exception as e:
            print(f"  \u2717 {label} failed: {e}")

    print(f"\nLoading adapter stack (pose={pose_scale}, depth={depth_scale}, snorricam={snorricam_scale})...")
    _fuse(
        "Lightricks/LTX-Video-ICLoRA-detailer-13b-0.9.8",
        "ltxv-098-ic-lora-detailer-diffusers.safetensors",
        "IC-LoRA Detailer",
        scale=1.0,  # sharpness only — fixed, not swept
    )
    _fuse(
        "Lightricks/LTX-Video-ICLoRA-pose-13b-0.9.7",
        "ltxv-097-ic-lora-pose-control-diffusers.safetensors",
        "IC-LoRA Pose Control",
        scale=pose_scale,
    )
    _fuse(
        "Lightricks/LTX-Video-ICLoRA-depth-13b-0.9.7",
        "ltxv-097-ic-lora-depth-control-diffusers.safetensors",
        "IC-LoRA Depth Control",
        scale=depth_scale,
    )

    _fuse(
        "Lightricks/LTXV-LoRAs",
        "Snorricam_step_02000_comfy.safetensors",
        "Snorricam Camera Style",
        scale=snorricam_scale,
    )


def main() -> int:
    args = parse_args()

    # ── Frame extraction mode ─────────────────────────────────────────────────
    if args.extract_last_frame:
        return extract_last_frame(args.extract_last_frame, args.output)

    # ── Validation ────────────────────────────────────────────────────────────
    if not args.prompt:
        print("ERROR: --prompt is required for video generation", file=sys.stderr)
        return 1

    # ── Device / dtype + GPU count detection ─────────────────────────────
    if args.device:
        device = args.device
    elif torch.cuda.is_available():
        device = "cuda"
    else:
        device = "cpu"

    print(f"Device         : {device} (single-GPU bf16 + sequential CPU offload)")

    if device == "cpu":
        dtype = torch.float32
        print("NOTE: Pure CPU inference — slow but fits any model in 96GB RAM")
    else:
        dtype = torch.bfloat16

    # ── Build prompts ─────────────────────────────────────────────────────────
    if args.no_enhance:
        prompt = args.prompt
    else:
        prompt = args.prompt + QUALITY_SUFFIX

    negative_prompt = args.negative_prompt or DEFAULT_NEGATIVE_PROMPT

    print(
        f"Mode           : {'I2V (image-conditioned)' if args.condition_image else 'T2V (text-only)'}"
    )
    print(f"Resolution     : {args.width}x{args.height}")
    print(
        f"Frames/FPS     : {args.num_frames} @ {args.fps}fps = {args.num_frames / args.fps:.1f}s"
    )
    print(
        f"Steps/CFG      : {args.num_inference_steps} steps, guidance={args.guidance_scale}"
    )
    print(f"Prompt         : {prompt[:120]}...")

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)

    # ── Always use LTXConditionPipeline ─────────────────────────────────────────────
    # F-TEXT-ONLY-LTX (iter6): even without bg/character/stills as frame
    # conditions we MUST load LTXConditionPipeline. The base LTXPipeline
    # path (`from_single_file` without separate text_encoder load) is
    # broken on the distilled FP8 checkpoint — T5EncoderModel weights
    # are not in the safetensors file. The Condition pipeline path
    # explicitly loads T5 from HF first, which works. Empty conditions
    # list is fine — LTX runs as pure text-to-video.
    if True:
        from diffusers import LTXConditionPipeline
        from diffusers.pipelines.ltx.pipeline_ltx_condition import LTXVideoCondition
        from diffusers.utils import export_to_video
        from PIL import Image as PILImage

        print("\nLoading LTXConditionPipeline (multi-image conditioning)...")
        if args.model_file:
            from huggingface_hub import hf_hub_download
            from transformers import T5EncoderModel

            ckpt_path = hf_hub_download(repo_id=args.model, filename=args.model_file)
            print(f"Checkpoint : {ckpt_path}")
            print("Loading T5 text encoder (CPU)...")
            text_encoder = T5EncoderModel.from_pretrained(
                args.model,
                subfolder="text_encoder",
                torch_dtype=dtype,
                device_map="cpu",
            )
            pipe = LTXConditionPipeline.from_single_file(
                ckpt_path, text_encoder=text_encoder, torch_dtype=dtype,
            )
        else:
            pipe = LTXConditionPipeline.from_pretrained(args.model, torch_dtype=dtype)

        # ── Adapter fusion ────────────────────────────────────────────────────
        _load_adapter_stack(pipe, pose_scale=args.pose_scale, depth_scale=args.depth_scale, snorricam_scale=args.snorricam_scale)

        # FP8 layerwise: store transformer weights at fp8_e4m3 (half size) and
        # compute in bf16. The full fp8 transformer (~13 GiB) fits resident
        # on the 5070 Ti (16 GiB), so the per-step layer-from-CPU streaming
        # cost of plain bf16 + offload is gone. Sequential CPU offload still
        # evicts the T5 encoder + VAE during the transformer pass so peak
        # stays under 14 GiB.
        print("\nApplying FP8 layerwise casting (storage=fp8, compute=bf16)...")
        pipe.transformer.enable_layerwise_casting(
            storage_dtype=torch.float8_e4m3fn,
            compute_dtype=torch.bfloat16,
        )
        pipe.enable_sequential_cpu_offload()
        pipe.enable_attention_slicing(1)
        pipe.vae.enable_tiling()
        pipe.vae.enable_slicing()
        print("✓ Single-GPU setup complete (FP8 + sequential CPU offload)")

        conditions = []

        # ── Frame 0: prev scene last-frame (seamless cut — highest priority) ──
        if args.condition_image and Path(args.condition_image).exists():
            last_frame_img = PILImage.open(args.condition_image).convert("RGB")
            last_frame_img = last_frame_img.resize(
                (args.width, args.height), PILImage.LANCZOS
            )
            conditions.append(
                LTXVideoCondition(image=last_frame_img, frame_index=0, strength=0.9)
            )
            print(f"Condition[0]: prev scene last-frame @ frame 0, strength=0.9")

        def _rgba_to_rgb(img):
            if img.mode == "RGBA":
                bg = PILImage.new("RGB", img.size, (255, 255, 255))
                bg.paste(img, mask=img.split()[3])
                return bg
            return img.convert("RGB")

        # F-TEXT-ONLY-LTX (iter6): bg arg flows in solely to select the
        # LTXConditionPipeline class (the base LTXPipeline.from_single_file
        # path is broken with the FP8 distilled checkpoint). We do NOT
        # add it as a frame condition — it would pin the mid-frame to a
        # static image, defeating text-to-video freedom.
        if args.background_image and Path(args.background_image).exists():
            print("Skipping background frame-condition (F-TEXT-ONLY-LTX); "
                  "arg pass-through only.")

        # ── Character: frame 0 appearance reference ──
        # Skip when action stills are provided. The action stills already
        # carry identity (InstantID-locked face) AND the correct pose for
        # the scene. Pinning a STANDING portrait at frame 0 while the
        # action stills are KNEELING/SITTING creates a 1-second morph that
        # LTX renders as a "second person" hallucination — the standing
        # body fading out while the seated body fades in. Letting the
        # first action still drive frame 0 (since stills are pinned at
        # fps*1, fps*2, …, LTX naturally interpolates the open frames
        # toward the first still's pose) eliminates the morph.
        # F-CANON-PORTRAIT (iter7): only pin the portrait when nothing else
        # already occupies frame 0. The previous-scene last-frame
        # (--condition-image) is added above at strength 0.9 — pinning the
        # portrait at the same frame_index would conflict and confuse LTX.
        # The portrait identity propagates transitively: scene 1 has no
        # last-frame so the portrait anchors it, scene 1's last-frame
        # carries that identity into scene 2's frame 0, and so on.
        _has_last_frame = (
            args.condition_image and Path(args.condition_image).exists()
        )
        if (
            args.character_image
            and Path(args.character_image).exists()
            and not args.scene_action_images
            and not _has_last_frame
        ):
            char_img = _rgba_to_rgb(PILImage.open(args.character_image))
            char_img = char_img.resize((args.width, args.height), PILImage.LANCZOS)
            # F-CANON-PORTRAIT (iter7): 0.90 → 0.50. The 0.90 anchor was
            # calibrated for the era when action stills also pinned LTX —
            # with action stills gone, 0.90 produced a "standing portrait
            # → seated/running action morph" because the body pose in the
            # portrait fights the prompt's action verbs. 0.50 gives LTX
            # enough freedom to evolve into the scene action while face
            # geometry stays anchored. If a previous scene's last_frame
            # is also pinned at frame 0 (via --condition-image), LTX
            # blends both — last_frame wins on pose, portrait wins on
            # identity. DO NOT push back to 0.90 (see FIXES_LOG).
            anchor_strength = 0.50
            conditions.append(
                LTXVideoCondition(image=char_img, frame_index=0, strength=anchor_strength)
            )
            print(f"Condition: character @ frame 0, strength={anchor_strength} (identity anchor)")
        elif args.character_image:
            if _has_last_frame:
                print(
                    "Skipping portrait condition: previous-scene last-frame "
                    "already pinned at frame 0 (carries identity transitively "
                    "from scene 1's portrait anchor)."
                )
            else:
                print(
                    "Skipping static-portrait condition (action stills present "
                    "carry identity and the correct pose; portrait@0 would "
                    "force a standing→action morph)."
                )

        # ── Action stills: spread across timeline ──
        n = args.num_frames

        if args.scene_action_images:
            # Multi-image mode: place one image per second of the clip
            # s1 → fps*1, s2 → fps*2, ...
            fps = args.fps
            for idx, img_path in enumerate(args.scene_action_images):
                if not Path(img_path).exists():
                    print(f"  [warn] action image {idx+1} not found: {img_path}")
                    continue
                frame_idx = fps * (idx + 1)  # 1s, 2s, 3s ...
                if frame_idx >= n:
                    print(f"  [warn] action image {idx+1} frame {frame_idx} >= num_frames {n}, skipping")
                    break
                # Slight strength decay: earlier frames anchor more
                strength = max(0.5, 0.7 - idx * 0.03)
                act_img = _rgba_to_rgb(PILImage.open(img_path))
                act_img = act_img.resize((args.width, args.height), PILImage.LANCZOS)
                conditions.append(
                    LTXVideoCondition(image=act_img, frame_index=frame_idx, strength=strength)
                )
                print(f"Condition: action still {idx+1} @ frame {frame_idx} ({idx+1}s), strength={strength:.2f}")
        else:
            # Legacy 2-image mode
            if args.scene_action_image and Path(args.scene_action_image).exists():
                action_img = _rgba_to_rgb(PILImage.open(args.scene_action_image))
                action_img = action_img.resize((args.width, args.height), PILImage.LANCZOS)
                f1 = n // 3
                conditions.append(
                    LTXVideoCondition(image=action_img, frame_index=f1, strength=0.7)
                )
                print(f"Condition: action still @ frame {f1} (1/3), strength=0.7")

            if args.scene_action_image_2 and Path(args.scene_action_image_2).exists():
                action2_img = _rgba_to_rgb(PILImage.open(args.scene_action_image_2))
                action2_img = action2_img.resize(
                    (args.width, args.height), PILImage.LANCZOS
                )
                f2 = (n * 2) // 3
                conditions.append(
                    LTXVideoCondition(image=action2_img, frame_index=f2, strength=0.65)
                )
                print(f"Condition: action still 2 @ frame {f2} (2/3), strength=0.65")


        # F-TEXT-ONLY-LTX (iter6): LTXConditionPipeline crashes on
        # `(1 - conditioning_mask_model_input) * 1000.0` when called with
        # an empty conditions list (the mask is None). When we genuinely
        # have no images to condition on, inject a single near-zero
        # strength gray placeholder so the pipeline still has SOMETHING
        # to mask against — it has effectively no influence on the
        # output, but it lets the pipeline run.
        if not conditions:
            placeholder = PILImage.new("RGB", (args.width, args.height), (128, 128, 128))
            conditions.append(
                LTXVideoCondition(image=placeholder, frame_index=0, strength=0.05)
            )
            print("Condition: gray placeholder @ frame 0, strength=0.05 "
                  "(LTXConditionPipeline requires >=1 condition)")

        generator = torch.Generator(device="cpu").manual_seed(args.seed)

        # ── VAE divisor snapping ──
        def _snap(v, divisor=32):
            return (v // divisor) * divisor

        lo_h = _snap(int(args.height * 2 / 3))
        lo_w = _snap(int(args.width * 2 / 3))

        # Check if latent upscaler is cached.
        # Force-disabled: step 3 of the upscale pipeline doubles spatial dims
        # (height*2 × width*2) and reliably OOMs on the 16 GiB 5070 Ti at any
        # portrait resolution we ship — the FP8 transformer alone is ~13 GiB
        # resident, leaving only ~2-3 GiB for activations which is blown by
        # the doubled-resolution refine pass. Re-enable when we have either
        # more VRAM or a separate post-pipeline upscaler.
        UPSCALER_REPO = "a-r-r-o-w/LTX-0.9.8-Latent-Upsampler"
        upscaler_available = False

        if upscaler_available:
            # Correct workflow (per official LTX docs):
            # Step 1: Generate at full target res → latents [B, C, T, H/32, W/32]
            # Step 2: Upsample latents 2× → [B, C, T, H/16, W/16]
            # Step 3: Refine at doubled pixel resolution (height*2, width*2)
            upscale_h = _snap(args.height * 2)  # 480 → 960
            upscale_w = _snap(args.width * 2)  # 704 → 1408

            print(
                f"\n3-Step Upscale Pipeline: {args.width}x{args.height} → upsample → {upscale_w}x{upscale_h}"
            )

            # Step 1: Generate at full target resolution, output latents
            print(
                f"  Step 1: Generating at {args.width}x{args.height} ({args.num_inference_steps} steps)..."
            )
            latents = pipe(
                conditions=conditions,
                prompt=prompt,
                negative_prompt=negative_prompt,
                height=args.height,
                width=args.width,
                num_frames=args.num_frames,
                frame_rate=args.fps,
                num_inference_steps=args.num_inference_steps,
                guidance_scale=args.guidance_scale,
                guidance_rescale=0.0,
                decode_timestep=0.05,
                decode_noise_scale=0.025,
                image_cond_noise_scale=0.0,
                generator=generator,
                max_sequence_length=512,
                output_type="latent",
            ).frames

            # Step 2: Latent upsample 2× — runs on pure GPU (upsampler is ~200MB, fits easily)
            from diffusers import LTXLatentUpsamplePipeline
            from diffusers.pipelines.ltx.modeling_latent_upsampler import (
                LTXLatentUpsamplerModel,
            )

            print(f"  Step 2: Upsampling latents 2x → {upscale_w}x{upscale_h}...")
            torch.cuda.empty_cache()
            upsampler_model = LTXLatentUpsamplerModel.from_pretrained(
                UPSCALER_REPO, torch_dtype=dtype
            )
            pipe_upsample = LTXLatentUpsamplePipeline(
                vae=pipe.vae, latent_upsampler=upsampler_model
            )
            # Can't call .to("cuda") — pipe.vae already has sequential offload hooks.
            # Sequential offload on the upsampler is fine; it's a tiny model.
            pipe_upsample.enable_model_cpu_offload()
            upscaled_latents = pipe_upsample(
                latents=latents, adain_factor=1.0, output_type="latent"
            ).frames
            del pipe_upsample, upsampler_model
            torch.cuda.empty_cache()

            # Step 3: Refine at DOUBLED resolution — dimensions must match upscaled latents
            print(
                f"  Step 3: Refining at {upscale_w}x{upscale_h} (10 steps, denoise=0.4)..."
            )
            frames = pipe(
                conditions=conditions,
                prompt=prompt,
                negative_prompt=negative_prompt,
                width=upscale_w,  # must match upscaled latent spatial dims
                height=upscale_h,  # must match upscaled latent spatial dims
                num_frames=args.num_frames,
                frame_rate=args.fps,
                denoise_strength=0.4,  # 4 effective steps out of 10
                num_inference_steps=10,
                latents=upscaled_latents,
                decode_timestep=0.05,
                decode_noise_scale=0.025,
                image_cond_noise_scale=0.0,
                guidance_scale=args.guidance_scale,
                guidance_rescale=0.0,
                generator=generator,
                max_sequence_length=512,
                output_type="pil",
            ).frames[0]

        else:
            # Fallback: single-pass at full resolution
            print(
                f"\nGenerating (LTXCondition, {len(conditions)} image(s), single-pass)..."
            )
            frames = pipe(
                conditions=conditions,
                prompt=prompt,
                negative_prompt=negative_prompt,
                height=args.height,
                width=args.width,
                num_frames=args.num_frames,
                frame_rate=args.fps,
                num_inference_steps=args.num_inference_steps,
                guidance_scale=args.guidance_scale,
                guidance_rescale=0.0,
                decode_timestep=0.05,
                decode_noise_scale=0.025,
                image_cond_noise_scale=0.0,
                generator=generator,
                max_sequence_length=512,
            ).frames[0]

        export_to_video(frames, args.output, fps=args.fps)
        print(f"\nSaved: {args.output}")
        return 0

    # ── Legacy single-image I2V (condition_image only) ──────────────────────────────
    if args.condition_image:
        from diffusers import LTXImageToVideoPipeline
        from diffusers.utils import export_to_video
        from PIL import Image as PILImage

        print(f"\nLoading I2V model: {args.model}")
        pipe = LTXImageToVideoPipeline.from_pretrained(args.model, torch_dtype=dtype)

        _load_adapter_stack(pipe, pose_scale=args.pose_scale, depth_scale=args.depth_scale, snorricam_scale=args.snorricam_scale)

        pipe.transformer.enable_layerwise_casting(
            storage_dtype=torch.float8_e4m3fn,
            compute_dtype=torch.bfloat16,
        )
        pipe.enable_sequential_cpu_offload()
        pipe.enable_attention_slicing(1)
        pipe.vae.enable_tiling()
        pipe.vae.enable_slicing()

        condition_img = PILImage.open(args.condition_image).convert("RGB")
        condition_img = condition_img.resize(
            (args.width, args.height), PILImage.LANCZOS
        )

        generator = torch.Generator(device="cpu").manual_seed(args.seed)


        i2v_guidance = min(args.guidance_scale, I2V_GUIDANCE_SCALE)
        if args.guidance_scale > I2V_GUIDANCE_SCALE:
            print(
                f"WARNING: --guidance-scale {args.guidance_scale} clamped to "
                f"{i2v_guidance} for I2V mode (I2V_GUIDANCE_SCALE={I2V_GUIDANCE_SCALE})"
            )
        print(
            f"I2V guidance   : {i2v_guidance} (lowered to preserve conditioning image)"
        )


        print("\nGenerating (I2V last-frame continuity)…")
        result = pipe(
            prompt=prompt,
            negative_prompt=negative_prompt,
            image=condition_img,
            height=args.height,
            width=args.width,
            num_frames=args.num_frames,
            num_inference_steps=args.num_inference_steps,
            guidance_scale=i2v_guidance,
            decode_timestep=0.05,
            decode_noise_scale=0.025,
            generator=generator,
            max_sequence_length=512,
        )

    # ── T2V Mode ──────────────────────────────────────────────────────────────
    else:
        from diffusers import LTXPipeline
        from diffusers.utils import export_to_video

        print(
            f"\nLoading T2V model: {args.model} / {args.model_file or '(from_pretrained)'}"
        )
        if args.model_file:
            from huggingface_hub import hf_hub_download

            ckpt_path = hf_hub_download(repo_id=args.model, filename=args.model_file)
            pipe = LTXPipeline.from_single_file(ckpt_path, torch_dtype=dtype)
        else:
            pipe = LTXPipeline.from_pretrained(args.model, torch_dtype=dtype)

        _load_adapter_stack(pipe, pose_scale=args.pose_scale, depth_scale=args.depth_scale, snorricam_scale=args.snorricam_scale)

        if device == "cuda":
            pipe.transformer.enable_layerwise_casting(
                storage_dtype=torch.float8_e4m3fn,
                compute_dtype=torch.bfloat16,
            )
            pipe.enable_sequential_cpu_offload()
            pipe.enable_attention_slicing(1)
        else:
            pipe.to(device)

        pipe.vae.enable_tiling()
        pipe.vae.enable_slicing()

        generator = torch.Generator(device="cpu").manual_seed(args.seed)

        print("\nGenerating (T2V)…")
        result = pipe(
            prompt=prompt,
            negative_prompt=negative_prompt,
            height=args.height,
            width=args.width,
            num_frames=args.num_frames,
            num_inference_steps=args.num_inference_steps,
            guidance_scale=args.guidance_scale,
            guidance_rescale=0.0,
            decode_timestep=0.05,
            decode_noise_scale=0.025,
            generator=generator,
            max_sequence_length=512,
        )

    frames = result.frames[0]
    export_to_video(frames, args.output, fps=args.fps)
    print(f"\nSaved: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
