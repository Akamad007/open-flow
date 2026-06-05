# Wan 2.2 TI2V-5B Implementation Plan

**Goal:** Add Wan 2.2 TI2V-5B as a third video provider alongside the existing
LTX and Phantom-Wan 14B paths, with first-class LoRA support so we can mix in
speed-distillation, style, motion, and identity LoRAs at generation time.

**Status:** Not started — planning doc.
**Last updated:** 2026-05-19

---

## 1. Why this model

- **Smaller footprint than Phantom-Wan 14B.** TI2V-5B fits comfortably on a
  single 16 GB GPU without the FP8 layerwise-casting + CPU-offload acrobatics
  the 14B path needs. Faster cold start, more headroom for batching.
- **Healthy LoRA ecosystem.** Wan 2.x is one of the most LoRA-rich open video
  model families. We get speed distillation (4-step Lightning, 6-10 step
  CausVid), style transfer, camera motion, and character LoRAs without having
  to train any ourselves.
- **Text-image-to-video.** Native I2V mode means we can keep using our
  identity-locked canonical stills as the conditioning image, the same way
  LTX consumes them today — no architectural rewrite of the pipeline.

---

## 2. LoRA ecosystem (the reason this is worth doing)

Most LoRAs were originally trained on Wan 2.1 14B and Wan 2.2 A14B. They
load on TI2V-5B but expect quality degradation and lower trigger weights
(0.5–0.7 instead of 1.0). Style LoRAs transfer better than character/identity
LoRAs.

### Speed/quality distillation (highest priority for us)

| LoRA | What it does | Source |
|---|---|---|
| **LightX2V Lightning** | 4-step distillation, ~20× faster, quality near base | `lightx2v/Wan2.2-Lightning` on HF |
| **CausVid** | 6–10 step distillation | HF / Civitai |
| **FusionX** | Merged LoRA stacking several quality+speed enhancements | Civitai |

If Lightning works on the 5B with acceptable quality, it collapses our ~80s
per-scene LTX generation to ~5–10s. This is the single biggest win.

### Style / aesthetic (Civitai)

Anime, cinematic film looks (35mm, anamorphic, film-stock emulations), 80s/90s
VHS, director-style (Wes Anderson, Wong Kar-wai), watercolor / oil / sketch.

### Motion

Camera moves (dolly, crane, orbit, push-in), subject motion (walk, dance,
fight cycles), slow-motion / time effects.

### Character / concept

Thousands of community character LoRAs on Civitai. Product/object LoRAs exist
but are sparser. For our ad use case, custom-trained product LoRAs are
probably more reliable than community ones.

### Where to pull from

- **Civitai** — largest hub, filter by "Wan Video" model type. Quality varies.
- **HuggingFace** — search `wan2.2` / `wan2.1`. More curated, research LoRAs.
- **Kijai's collections** — `Kijai/WanVideo_comfy` on HF bundles useful LoRAs
  alongside fp8 weights.

### TI2V-5B caveat

Most LoRAs target 14B variants. On 5B expect:

- Some quality degradation vs. running on 14B
- Trigger weights need lowering (0.5–0.7)
- Style LoRAs transfer cleanly; character/identity LoRAs less so
- 5B-native LoRAs exist but the catalog is small

If we hit a wall with LoRA quality on 5B, the fallback is to run Wan 2.1 14B
(largest LoRA catalog) or Wan 2.2 A14B with FP8 + offload like we already do
for Phantom-Wan 14B.

---

## 3. How it slots into the existing pipeline

We already have the provider abstraction:
[backend/app/providers/video/](../backend/app/providers/video/). Adding a
third provider is a localized change.

### Files to add

- `wan22_generate.py` (project root, mirrors `wan_generate.py` / `ltx_generate.py`)
  — in-process runner, subprocess-callable. Handles model load, LoRA merging,
  T2V/I2V routing, output writing.
- `backend/app/providers/video/wan22_provider.py` — `WanVideoProvider`
  subclassing `VideoProvider`. Mirrors `wan_phantom_provider.py`: builds
  args, spawns subprocess, parses result.

### Files to edit

- `backend/app/config.py` — extend `video_provider` enum to include `wan22`.
  Add LoRA config block: list of `(path, weight, trigger)` tuples loaded
  from settings.
- `backend/app/providers/video/__init__.py` — register the new provider.
- `start_all.sh` — no change (subprocess model, no new long-lived service).

### Conditioning translation

TI2V-5B is image-to-video, single conditioning image. Map:

- `character_image_path` → primary conditioning image (canonical portrait or
  identity-locked still, same as LTX path today)
- `condition_image_path` → ignored (no last-frame chaining in I2V mode unless
  we want to opt into it explicitly — keep parity with LTX behavior)
- `background_image_path`, `scene_action_images` → ignored

This honors the existing memory: **never pin pictures as frame conditions**.
TI2V-5B's I2V mode uses the image as a *starting frame*, which is the only
acceptable conditioning shape per that rule.

### LoRA loading

Two tiers:

1. **Always-on LoRAs** (e.g. Lightning speed distillation) — merged once at
   model load. Config-driven, listed in settings.
2. **Per-scene LoRAs** (style / motion / aesthetic) — selected at runtime
   by the LLM during prompt generation, applied per scene.

See section 4 for the LLM-driven selection mechanism.

---

## 4. LLM-driven per-scene LoRA selection

Style / motion / aesthetic LoRAs are scene-dependent: a slow dolly-in works
for an emotional close-up, a watercolor LoRA for a flashback, a 35mm-film
look for the hero shot. Hard-coding triggers or always-on lists wastes the
expressivity. The LLM already writes the scene prompt — let it also pick
the LoRA that fits.

### Catalog

A static YAML catalog at `backend/app/config/wan22_lora_catalog.yaml`:

```yaml
- id: cinematic_35mm
  path: ~/wan22-loras/cinematic_35mm.safetensors
  description: 35mm film grain, anamorphic compression, warm color cast
  default_weight: 0.7
  good_for: [hero_shot, emotional, product_reveal]
- id: dolly_in
  path: ~/wan22-loras/motion_dolly_in.safetensors
  description: Slow camera push toward subject
  default_weight: 0.6
  good_for: [emotional, close_up]
- id: vhs_80s
  path: ~/wan22-loras/vhs_80s.safetensors
  description: VHS chroma noise, scan lines, 80s color palette
  default_weight: 0.5
  good_for: [flashback, nostalgic]
- id: none
  path: null
  description: No style LoRA — let the base model render unstyled
  default_weight: 0.0
  good_for: [neutral, documentary]
```

The catalog is the contract: the LLM only picks from `id`s in this file. We
inject the catalog into the LLM context during prompt generation so the
model sees descriptions and `good_for` tags.

### LLM output schema extension

Today the prompt-generation LLM returns `video_prompt`, `negative_prompt`,
`camera_plan`, etc. Add two fields:

```json
{
  "video_prompt": "...",
  "negative_prompt": "...",
  "lora_id": "cinematic_35mm",
  "lora_weight": 0.7,
  ...
}
```

`lora_id` must be a valid catalog id (validated server-side; fallback to
`"none"` on unknown id). `lora_weight` is optional; defaults to the catalog
entry's `default_weight`.

### ScenePrompt model change

[backend/app/models/scene_prompt.py](../backend/app/models/scene_prompt.py)
gets two nullable columns via Alembic migration:

```python
lora_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
lora_weight: Mapped[float | None] = mapped_column(Float, nullable=True)
```

Persisted alongside the rest of the prompt fields in `_apply_prompt_result`
in [prompt_generation.py](../backend/app/orchestration/stages/prompt_generation.py).

### Wiring into the provider

The video-generation stage
([scene_video.py](../backend/app/orchestration/stages/scene_video.py)) reads
`scene.prompt.lora_id` and `scene.prompt.lora_weight`, resolves the id
against the catalog to get a path, and passes
`lora_path` + `lora_weight` to `WanVideoProvider.generate_video()`.

The provider forwards both to `wan22_generate.py` as CLI args
(`--lora-path`, `--lora-weight`). The runner applies the LoRA before
generation (and unloads it after, since per-scene LoRAs are not merged into
base weights — they're applied as adapters).

### Failure modes to handle

- **Unknown `lora_id`** → log warning, fall back to `"none"`. Do not fail
  the scene.
- **Missing LoRA file on disk** → same fallback. Surface the failure in the
  scene's prompt audit log so we can fix the catalog.
- **LLM returns no `lora_id` field** → treat as `"none"`. Backwards-compat
  for early prompts and for non-Wan2.2 providers (LTX ignores the field).

---

## 5. Tests

All tests must follow the project's no-network rule: mock the LLM agent and
the video provider, do not download weights. Write tests during the
refactor, not after.

### Unit tests

- `test_lora_catalog_load` — catalog YAML parses, required fields present,
  `none` entry exists.
- `test_lora_catalog_lookup_unknown_id` — unknown id returns the `none`
  entry, no exception.
- `test_scene_prompt_persists_lora` — `_apply_prompt_result` writes
  `lora_id` and `lora_weight` to `ScenePrompt` when the LLM returns them.
- `test_scene_prompt_lora_defaults` — when LLM omits `lora_id`, ScenePrompt
  stores `"none"` / `0.0`.
- `test_scene_prompt_invalid_lora_falls_back` — unknown `lora_id` from LLM
  is persisted as `"none"` after validation.

### Provider tests (subprocess mocked)

- `test_wan22_provider_passes_lora_args` — provider invokes the subprocess
  with `--lora-path` and `--lora-weight` when ScenePrompt has a LoRA set.
- `test_wan22_provider_omits_lora_args_for_none` — when `lora_id == "none"`
  or path is null, no `--lora-*` args are passed.
- `test_wan22_provider_lora_missing_file_fallback` — provider checks
  `Path(lora_path).exists()` and falls back to no-LoRA generation if the
  file is missing, logging a warning.

### Integration tests (LLM and provider both mocked)

- `test_prompt_generation_includes_catalog_in_context` — assert the LLM
  context dict passed to `agent.run()` contains a `lora_catalog` key with
  the catalog's id/description/good_for entries.
- `test_scene_video_stage_resolves_lora_path` — given a `ScenePrompt` with
  `lora_id="cinematic_35mm"`, the stage resolves to the correct path and
  forwards it to the provider.
- `test_ltx_provider_ignores_lora_field` — backwards-compat: a ScenePrompt
  with a `lora_id` set still works under the LTX provider (field ignored).

### Utilization gate

The plan is not done until:

1. At least one real scene has been generated end-to-end with an LLM-picked
   LoRA, captured in `docs/runs/`.
2. The pipeline test
   ([backend/test_pipeline_isolated.py](../backend/test_pipeline_isolated.py))
   covers the LoRA-selection path and is added to the standard test run in
   `test.sh`.

---

## 6. Open questions before we write code

1. **Does Lightning 4-step actually hold up on 5B?** Need a quick test:
   pull `lightx2v/Wan2.2-Lightning`, run it against 5B with one of our
   existing prompts, eyeball quality vs. our LTX baseline.
2. **Where do we keep LoRA weight files?** Probably under
   `~/wan22-loras/` to keep them out of the repo. Add to `start_all.sh`
   preflight check.
3. **Inference engine — diffusers or ComfyUI nodes?** Diffusers gives us a
   clean Python API; ComfyUI nodes have better LoRA-mixing tooling but a
   heavier integration. Start with diffusers; revisit if LoRA stacking gets
   awkward.
4. **5B or fall back to 14B?** If 5B + Lightning quality is unacceptable,
   skip the 5B path entirely and implement Wan 2.2 A14B with the same FP8
   approach as Phantom-Wan 14B.

---

## 7. Next concrete step

Spike: download TI2V-5B weights, run a single generation via diffusers with
no LoRAs, then with Lightning LoRA. Compare wall-clock and quality to our
current LTX output on the same prompt. Decision gate: if Lightning quality
≥ LTX baseline and wall-clock < 15s/scene, proceed with the full provider
build. Otherwise reassess (14B path or stay on LTX).
