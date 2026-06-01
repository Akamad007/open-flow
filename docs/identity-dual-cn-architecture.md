# Identity-Locked Action Stills (production)

## Goal

Render the **same character in multiple action poses, full body**, from one source portrait. Replaces the SD3.5 t2i action-stills path that lost identity across stills.

## Architecture

```
Character portrait (opaque)               ┐
                  ↓ InsightFace antelopev2 │
            face embedding ────────────────┤   InstantID
                                           ├─→ ControlNet ─┐
Per-scene SD3.5 t2i pose reference         │              │
                  ↓ controlnet_aux         │              │   SDXL UNet → Action still
                  OpenposeDetector         │              │       ↑
            OpenPose skeleton ─────────────┴─→ OpenPose───┘   Prompt
                                              SDXL CN
```

Two ControlNets stacked via `MultiControlNetModel`:

| ControlNet | Input | Locks |
|---|---|---|
| **InstantID** (`InstantX/InstantID`) | face embedding + face keypoints | identity (face, hair, head shape) |
| **OpenPose** (`thibaud/controlnet-openpose-sdxl-1.0`) | OpenPose skeleton | body pose (running, sitting, jumping, ...) |

The pose reference is a generic-person SD3.5 t2i image — its skeleton is the only thing OpenPose extracts; identity comes from the InstantID embedding.

## Files

| Layer | Path |
|---|---|
| GPU subprocess (face + body) | `~/instantid/generate_instantid_pose.py` |
| GPU subprocess (face only, fallback) | `~/instantid/generate_instantid.py` |
| InstantID repo (pipeline class) | `~/InstantID/` |
| Provider | `backend/app/providers/image/instantid_provider.py` |
| Per-scene pose-ref helper | `backend/app/agents/image_pregen/pose_refs.py` |
| Routing | `backend/app/agents/image_pregen/action_stills.py` |
| Config | `backend/app/config.py` (`identity_provider_enabled`, `identity_strength`, `pose_strength`) |

## Flow per scene

1. `image_pregen` pre-renders the character portrait via SD3.5 (saves both a bg-removed canonical and an opaque sidecar `<name>_opaque.png`).
2. `action_stills.generate_for_scene` (per scene):
   a. Calls `pose_refs.generate_for_scene` — one SD3.5 t2i pose reference per scene, prompt derived from `scene.prompt.action_description`.
   b. For each second of the scene, builds the still prompt via the visual director, then calls `InstantIDImageProvider.generate_with_identity` with `pose_image_path = <scene's pose ref>`.
3. Provider invokes `~/instantid/generate_instantid_pose.py` (subprocess; full VRAM release after each call).
4. Output is bg-removed (rembg) and stored as `scene_NNN_sNN.png`. Opaque sidecar kept.

## Routing priority (action_stills.py:103)

1. **PRODUCT-IMG2IMG** — only when product role is `hero`.
2. **IDENTITY+POSE dual-CN** — when identity provider is on, character has portrait, scene has pose ref.
3. **IDENTITY-LOCK (face-only InstantID)** — when identity is on but no pose ref.
4. **TEXT-TO-IMAGE** — final fallback.

## Tuned defaults (smoke test 2026-05-06)

- `identity_strength = 0.80` — slight loosening from 0.85 for pose freedom.
- `pose_strength = 0.65` — lets prompt's clothing description bleed through OpenPose's clothing leak.
- `steps = 40` — cleaner than 30, modest extra time.
- `guidance = 5.0` — InstantID convention.

## Per-character LoRA (optional optimization)

Once the pipeline produces a good batch of dual-CN stills for a character, those can become a DreamBooth-LoRA training set:

- `backend/lora_training/build_dataset.py` — generates 20 dual-CN poses + caption pairs.
- `backend/lora_training/train_lora.sh` — SDXL LoRA, rank=16, 800 steps, fp16, 8-bit Adam.
- `backend/lora_training/inference_lora.py` — loads SDXL + LoRA, runs inference.

Inference cost: ~10 s per still vs ~80 s for the dual-CN subprocess. Use the LoRA when the character will be reused across many projects; fall back to dual-CN for one-shot characters.

## Known limits

- **Pose-ref drives clothing**: OpenPose ControlNet leaks color/material from the pose reference image. Mitigate by lowering `pose_strength` and beefing up the prompt's clothing description.
- **Single pose ref per scene**: All per-second stills in a scene share one pose ref. Per-second variation comes only from the prompt's beat hint. If finer pose progression is needed, generate multiple pose refs per scene.
- **antelopev2 license**: face encoder is research-only. Re-evaluate vs `buffalo_l` (MIT) before paid customers — buffalo_l reduces ID fidelity but is commercial-clean.
- **Diffusers 0.38 deprecation**: `MultiControlNetModel` from `diffusers.pipelines.controlnet.multicontrolnet` is hard-removed; the InstantID pipeline imports from there. We monkey-patch the symbol before importing the pipeline (see `~/instantid/generate_instantid_pose.py`).
