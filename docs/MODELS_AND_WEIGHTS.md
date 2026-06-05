# Models, Weights & GPU Requirements

OpenFlow drives several open AI models. **None are bundled** — they are large
(multi-GB) and carry their own licenses (see
[THIRD_PARTY_LICENSES.md](../THIRD_PARTY_LICENSES.md)). You only need the weights
for the providers you actually enable; **stub mode needs none** (see the no-GPU
quickstart in the [README](../README.md)).

## TL;DR

```bash
# 1. choose where weights live (default <repo>/models)
export MODELS_ROOT=/data/openflow-models

# 2. (gated models) authenticate to Hugging Face
huggingface-cli login            # or: export HF_TOKEN=hf_...

# 3. download what you need
python backend/scripts/download_models.py --all      # or --ltx --wan22 --sd35
```

Point the app at the weights via `MODELS_ROOT` (or per-model overrides
`WAN22_MODEL_PATH`, `WAN22_MOTION_MODEL_PATH`, `WAN22_LORA_DIR`) in `.env`.

## Models

| Provider | Env to enable | Hugging Face repo | Approx size | License notes |
|---|---|---|---|---|
| LTX-Video | `VIDEO_PROVIDER=ltx` | `Lightricks/LTX-Video` | ~20 GB | OpenRAIL-style; check repo |
| Wan 2.2 TI2V-5B | `VIDEO_PROVIDER=wan22` | `Wan-AI/Wan2.2-TI2V-5B-Diffusers` | ~20 GB | Apache-2.0 (verify) |
| Wan 2.2 motion (FrameINO) | `VIDEO_PROVIDER=wan22` (motion scenes) | per upstream | ~10 GB | check upstream |
| Stable Diffusion 3.5 Medium | `IMAGE_PROVIDER=sd35` | `stabilityai/stable-diffusion-3.5-medium` | ~10 GB | **Stability Community License — commercial limits**; gated, needs `HF_TOKEN` |
| Chatterbox TTS | `AUDIO_PROVIDER=chatterbox` | per `chatterbox_generate.py` | ~2 GB | check upstream |
| GFPGAN / CodeFormer (face restore) | auto on distant shots | fetched on first use | <1 GB | vendored, gitignored |
| InstantID (identity) | `IDENTITY_PROVIDER_ENABLED=true` | external scripts in `INSTANTID_DIR` | ~5 GB | **identity synthesis — see [ETHICAL_USE.md](../ETHICAL_USE.md)** |

### InstantID is external

The InstantID face-identity pipeline is invoked as standalone scripts living in
`INSTANTID_DIR` (default `~/instantid`): `generate_instantid.py`,
`generate_instantid_pose.py`, `extract_embedding.py`, `instantid_daemon.py`.
These are **not part of this repo**. If the directory is missing, OpenFlow falls
back to plain SD 3.5 text-to-image automatically. Set `INSTANTID_DIR` to wherever
you install them.

## GPU / VRAM requirements

- **No GPU:** stub mode runs the entire pipeline on CPU for development/testing.
- **Image only (SD 3.5):** ~12 GB VRAM.
- **Video (Wan 2.2 TI2V-5B / LTX-13B fp8):** **16 GB+ VRAM** recommended;
  validated on a single 5070 Ti (16 GB) at ~6–8 min/scene. Lower VRAM works at
  reduced resolution/steps (see `preview.sh`).
- **Multi-GPU:** Celery routes one worker per card (`gpu{i}` queues); set
  `CUDA_DEVICE_ORDER=PCI_BUS_ID`. See the orchestration docs.
- Disk: budget **60–80 GB** for the full set of weights.
