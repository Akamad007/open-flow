# HunyuanVideo-Foley — Setup Runbook + video-app Integration Plan

Replace / augment the current **Chatterbox TTS** audio generator with Tencent's
**HunyuanVideo-Foley** — a video-to-audio (Foley) model that takes a *silent
video clip + optional text prompt* and emits a *synced sound-effects / ambience
track*.

This doc is two things at once:
1. A reproducible standalone setup runbook (the "RUN.md" — exact commands to
   stand up the model and run one generation + the Gradio UI).
2. The plan for wiring it into this repo's provider-based audio pipeline.

---

## 0. Read this first — Foley is NOT a drop-in for narration

The thing we have today and the thing we're adding are different kinds of audio:

| | Current: `ChatterboxAudioProvider` | New: HunyuanVideo-Foley |
|---|---|---|
| Input | narration **text** (+ a voice reference WAV) | a silent **video** (+ optional text prompt) |
| Output | spoken **narration** (voice) | **sound effects / ambience** (no speech) |
| Driven by | `AudioPlan.full_story_narration_text` | the rendered scene clips + `ambience_progression_notes` |
| Duration | natural TTS length (no stretch) | exactly matches the input video length |

Implication: Foley cannot literally "replace narration" without losing the
spoken track. There are two integration shapes (pick one — see §7):

- **A. Replace** — drop voice narration entirely; the episode's audio is pure
  Foley/ambience. Simplest. Use when these are ambience-driven videos, not
  voiced ones.
- **B. Layer (recommended)** — keep Chatterbox narration, generate Foley from
  the silent render, then mix Foley *under* the voice (same pattern the YouTube
  background-music path already uses in
  [audio_generation.py](../backend/app/orchestration/stages/audio_generation.py#L67)).

Either way, Foley's "output length == input video length" behaviour is a clean
fit for this repo's rule that audio matches the rendered video and is **never
time-stretched** (audio stage already runs *after* the video chord and probes
real clip durations — see
[audio_generation.py:199-214](../backend/app/orchestration/stages/audio_generation.py#L199-L214)).

---

## 1. Target hardware / context

- GPU: single NVIDIA card, **16 GB VRAM**.
- OS: Linux (use WSL conventions if this turns out to be Windows).
- Decided model: **XXL (best quality) with offload ENABLED** → fits in ~12 GB.
  - If CUDA OOM *with* offload → fall back to **XL**.
  - Only after XL also fails → consider the **ComfyUI FP8** path.
  - **Do not silently swap models/flags — report the error and the proposed
    fix first.**
- Note for *this* machine: the repo's GPU helper expects multi-GPU and pins
  non-video work to the non-largest card
  ([gpu.py:37-45](../backend/app/utils/gpu.py#L37-L45)). On a single-GPU box
  `non_largest_gpu_index()` returns `0`, so Foley and any concurrent video gen
  share one card — schedule Foley so it does not overlap a Wan22/LTX render
  (the pipeline already serializes audio after the video chord, so this holds).

---

## 2. Prerequisites — VERIFY before installing anything

Run these and report findings *before* touching the environment. Do not assume.

```bash
# GPU + driver + free VRAM
nvidia-smi

# CUDA toolkit version — need 12.4 or 11.8; flag if mismatched
nvcc --version || echo "nvcc not on PATH — check /usr/local/cuda*/bin"

# Python 3.8+ available
python3 --version

# Free disk space — weights are multi-GB (Foley model + SigLIP-2 + CLAP +
# Synchformer + 48kHz audio VAE). Warn if the target volume looks tight (<40GB).
df -h .
```

Pass criteria:
- A CUDA-capable GPU with ≥12 GB *free* (XXL+offload target). If free VRAM is
  low because a video render is live, wait for it.
- CUDA 12.4 **or** 11.8. Anything else → flag the mismatch before proceeding.
- Python ≥ 3.8.
- Comfortable free disk (budget ~30–40 GB for weights + clones + outputs).

---

## 3. Isolated environment (name: `hyvf`) — never system Python

Conda preferred:

```bash
conda create -n hyvf python=3.10 -y
conda activate hyvf
```

venv acceptable (if no conda) — **do not** reuse the repo's `video-app` pyenv;
Foley gets its own env to avoid dependency collisions:

```bash
python3 -m venv ~/envs/hyvf
source ~/envs/hyvf/bin/activate
```

Verify isolation: `which python` should point inside `hyvf`, not system / the
`video-app` pyenv.

---

## 4. Clone + install

```bash
cd ~                                  # or wherever you keep model repos
git clone https://github.com/Tencent-Hunyuan/HunyuanVideo-Foley
cd HunyuanVideo-Foley

pip install -r requirements.txt
```

Verify after install (don't assume success):

```bash
python -c "import torch; print('torch', torch.__version__, 'cuda', torch.cuda.is_available())"
pip check        # surfaces dependency conflicts
```

- Pin versions **only if** a fresh install breaks; otherwise use exactly what
  `requirements.txt` specifies.
- If `pip install` fails, capture the exact error and propose a fix before
  retrying.

---

## 5. Download weights → local `./weights`

The download bundles the Foley model **plus** SigLIP-2, CLAP, Synchformer and a
48 kHz audio VAE, so it is multi-GB.

```bash
# from inside the HunyuanVideo-Foley repo, env hyvf active
huggingface-cli download tencent/HunyuanVideo-Foley \
    --local-dir ./weights \
    --local-dir-use-symlinks False
```

Report the total pulled:

```bash
du -sh ./weights
```

Many of these repos expect a `HIFI_FOLEY_MODEL_PATH` env var pointing at the
weights dir. Set it for the session (and confirm the actual var name against the
repo README — it is authoritative if it differs):

```bash
export HIFI_FOLEY_MODEL_PATH="$PWD/weights"
```

> Verify-as-you-go: confirm the encoders (SigLIP-2, CLAP, Synchformer, VAE) are
> present under `./weights` — some repos auto-fetch them on first run instead of
> via the single `download` call. If first inference tries to reach the network
> for a missing encoder, that's why.

---

## 6. First test generation — XXL + offload

Get a sample clip first (use the repo's bundled examples if you have none):

```bash
ls examples/    # repo ships short test videos here
```

Single-video CLI (XXL config, offload on). **Flag names below match the repo at
release; if `infer.py`'s args differ, the repo README/`-h` is authoritative —
do not guess, check `python infer.py -h`.**

```bash
python infer.py \
    --model_path ./weights \
    --config_path configs/hunyuanvideo-foley-xxl.yaml \
    --single_video examples/1.mp4 \
    --single_prompt "footsteps on gravel, distant city ambience" \
    --output_dir results/ \
    --offload                      # enable CPU offload so XXL fits in ~12GB
```

Confirm the output actually exists and report path + duration:

```bash
ls -lh results/
ffprobe -v error -show_entries format=duration \
    -of default=noprint_wrappers=1:nokey=1 results/*.wav 2>/dev/null \
 || ffprobe -v error -show_entries format=duration \
    -of default=noprint_wrappers=1:nokey=1 results/*.mp4
```

If CUDA OOM **even with `--offload`**: stop, report it, and (per the constraint)
get the go-ahead before falling back to XL:

```bash
# fallback ONLY after reporting:
python infer.py --model_path ./weights \
    --config_path configs/hunyuanvideo-foley-xl.yaml \
    --single_video examples/1.mp4 \
    --single_prompt "footsteps on gravel, distant city ambience" \
    --output_dir results/ --offload
```

---

## 7. Launch the Gradio web UI (XXL + offload)

```bash
python gradio_app.py
# → note the printed local URL, e.g. http://127.0.0.1:7860
```

If the app reads model/config from env rather than flags, set them first:

```bash
export HIFI_FOLEY_MODEL_PATH="$PWD/weights"
# (and any XXL/offload env the README documents)
python gradio_app.py
```

Open the URL, upload a silent clip, type a prompt, generate, listen.

---

## 8. Integrating into video-app

The audio subsystem is **provider-based** and selected at runtime, so wiring a
new backend is localized. Files that matter:

- Interface: [providers/audio/base.py](../backend/app/providers/audio/base.py)
  — `AudioProvider.generate_full_story_audio(narration_text, output_path,
  target_duration, audio_settings) -> AudioResult`.
- Existing subprocess pattern to mirror:
  [chatterbox_provider.py](../backend/app/providers/audio/chatterbox_provider.py)
  + root script [chatterbox_generate.py](../chatterbox_generate.py). The model
  runs in a **subprocess** (its own env) so it never loads into the web server
  or Celery worker — Foley must do the same, and it lives in the `hyvf` env, not
  `video-app`, which makes the subprocess boundary mandatory.
- Provider factory: `get_audio_provider()` in
  [_common.py:74-79](../backend/app/orchestration/_common.py#L74-L79).
- Stage that calls it: `run()` in
  [audio_generation.py:139-257](../backend/app/orchestration/stages/audio_generation.py#L139-L257).
- Config: `audio_provider` + provider settings in
  [config.py:77-80](../backend/app/config.py#L77-L80).

### 8.1 The interface gap

`generate_full_story_audio` takes **narration text**, not a video. Foley needs
the **silent rendered video**. The rendered scene clips already exist on disk at
this stage (the stage even probes them via `_sum_scene_video_durations`,
[audio_generation.py:35-49](../backend/app/orchestration/stages/audio_generation.py#L35-L49)).
Two ways to bridge:

- **Minimal (recommended):** concat the episode's completed `scene_video`
  assets into one silent `episode_silent.mp4` (ffmpeg concat), then have the
  Foley provider take that path. Add an optional `video_path` kwarg to
  `generate_full_story_audio` (default `None`, ignored by Chatterbox/Stub) so
  the signature stays backward-compatible.
- **Cleaner long-term:** add a dedicated `task_generate_foley` stage between the
  video chord and stitching that owns the concat→Foley→(mix) flow, leaving the
  TTS stage untouched. More code; do this only if Foley becomes the default.

### 8.2 New files / edits

1. **`hunyuan_foley_generate.py`** (repo root) — standalone subprocess script,
   modelled on `chatterbox_generate.py`. Args: `--video`, `--prompt`,
   `--output`, `--config` (xxl/xl), `--offload`, `--model-path`. It activates /
   runs under the `hyvf` interpreter, runs `infer.py`'s pipeline (import or
   `subprocess`), and prints a final JSON line `{ "duration", "output", ... }`
   for the provider to parse (same contract Chatterbox uses).

2. **`backend/app/providers/audio/hunyuan_foley_provider.py`** — implements
   `AudioProvider`. Builds the command, pins GPU via
   `apply_gpu_env(env, non_largest_gpu_index())`
   ([gpu.py:115-119](../backend/app/utils/gpu.py#L115-L119)), runs the
   subprocess with a **separate interpreter** (new setting, see below — *not*
   `gpu_python_path`, which points at the `video-app` env), parses the JSON,
   returns `AudioResult`. The Foley prompt is composed from the audio plan's
   `ambience_progression_notes` + per-scene `visual_summary` rather than the
   narration text.

3. **`get_audio_provider()` edit** — add the branch:
   ```python
   if settings.audio_provider == "hunyuan_foley":
       from app.providers.audio.hunyuan_foley_provider import HunyuanFoleyProvider
       return HunyuanFoleyProvider()
   ```

4. **`config.py` + `.env`** — new settings:
   ```python
   # ── Audio Provider ──
   audio_provider: str = "stub"  # chatterbox | hunyuan_foley | stub
   foley_python_path: str = "/home/akash/envs/hyvf/bin/python"   # or conda env python
   foley_repo_dir: Path = Path("/home/akash/HunyuanVideo-Foley")
   foley_weights_dir: Path = Path("/home/akash/HunyuanVideo-Foley/weights")
   foley_config: str = "hunyuanvideo-foley-xxl.yaml"            # xl fallback
   foley_offload: bool = True
   foley_layer_under_narration: bool = True   # True = mode B (mix), False = mode A (replace)
   ```

5. **Stage wiring** — in `audio_generation.run()`:
   - Mode A (replace): set `audio_provider=hunyuan_foley`; concat scene videos →
     silent mp4 → pass as `video_path`; the returned WAV becomes the
     `full_story_audio` asset directly.
   - Mode B (layer): keep the Chatterbox call, then generate Foley from the
     silent concat and mix it *under* the narration with
     `mix_two_audio_tracks(..., background_volume=~0.5)` — reuse
     [`_mix_youtube_as_background`](../backend/app/orchestration/stages/audio_generation.py#L67-L91)
     as the template.

### 8.3 What does NOT change

- LLM audio planning (`audio_director.py`, `audio_planning.py`) — still produces
  the narration + `ambience_progression_notes` Foley will use as its prompt.
- Stitching — already overlays whatever WAV/MP3 the `full_story_audio` asset
  points at; provider-agnostic.
- DB models / schemas / API — `full_story_audio` asset type already generic;
  record `generation_provider="hunyuan_foley"` + the prompt in `metadata_json`.

---

## 9. Constraints / discipline (carry these through execution)

- Run real commands; verify each install/download actually worked before moving
  on (`pip check`, `du -sh weights`, `ffprobe` the output).
- Pin versions only if a fresh install breaks.
- On any failure: surface the **exact error** + proposed fix *before* retrying.
- **Do not** silently swap XXL→XL→ComfyUI-FP8 or toggle flags — report first.
- Soft-delete discipline still applies — never `rm` user artifacts; the Foley
  outputs land in `results/` (standalone) and under
  `storage/audio/<project>/episodes/<episode>/` (integrated).

---

## 10. RUN — copy/paste reproducible commands

Standalone (after §3–§5 are done once):

```bash
conda activate hyvf                 # or: source ~/envs/hyvf/bin/activate
cd ~/HunyuanVideo-Foley
export HIFI_FOLEY_MODEL_PATH="$PWD/weights"

# --- single-video CLI ---
python infer.py \
    --model_path ./weights \
    --config_path configs/hunyuanvideo-foley-xxl.yaml \
    --single_video examples/1.mp4 \
    --single_prompt "footsteps on gravel, distant city ambience" \
    --output_dir results/ \
    --offload

# --- Gradio web UI ---
python gradio_app.py     # open the printed http://127.0.0.1:7860
```

Integrated (once §8 is implemented):

```bash
# in video-app .env
AUDIO_PROVIDER=hunyuan_foley
FOLEY_PYTHON_PATH=/home/akash/envs/hyvf/bin/python
FOLEY_REPO_DIR=/home/akash/HunyuanVideo-Foley
FOLEY_WEIGHTS_DIR=/home/akash/HunyuanVideo-Foley/weights
FOLEY_CONFIG=hunyuanvideo-foley-xxl.yaml
FOLEY_OFFLOAD=true
FOLEY_LAYER_UNDER_NARRATION=true

# then run the normal pipeline (start_all.sh) — Foley fires in the audio stage,
# after the video chord, against the real rendered clip durations.
```

> Flag-name caveat: `infer.py` / `gradio_app.py` argument names and the offload
> mechanism are taken from the repo at model release. Before first run, confirm
> with `python infer.py -h` and the repo README — those are authoritative.
