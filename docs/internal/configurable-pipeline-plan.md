# Configurable Multi-Model Pipeline — Design Doc

## Goal

Today the pipeline is hard-wired to LTX-Video text-only. Switching to a different video model (e.g. **Phantom-Wan 14B**) requires editing config flags and per-stage code. We want **named pipeline profiles** the user can pick at project-creation time:

```
POST /api/projects { ..., "pipeline": "ltx_text_only" }
POST /api/projects { ..., "pipeline": "wan_phantom_actions" }
POST /api/projects { ..., "pipeline": "wan_phantom_text" }
```

Each profile bundles together: which stages run, which video/audio/image providers, and what conditioning gets pinned where. New model = new profile + new provider plugin. No edits to orchestration.

---

## Current state (what works, what doesn't)

| Concern | Current | Limitation |
|---|---|---|
| Provider selection | `settings.video_provider = "ltx" | "stub"` | One global setting; can't run two projects with different models in parallel |
| Stage gating | `settings.image_pregen_enabled = bool` | Single boolean; can't say "Wan needs portraits, LTX doesn't" |
| Conditioning rules | Hard-coded in `ltx_provider.py` + `ltx_generate.py` | Wan needs reference embeddings, not frame pins; no place for that |
| Per-model tuning | `settings.ltx_*` (12 keys) | Wan would add `wan_*`; no isolation |
| Pipeline chain | `full_pipeline.py:build_pipeline_workflow` | Same chain for every project |

---

## Target architecture

### 1. Pipeline profile = a typed dataclass

`backend/app/orchestration/profiles.py` (new):

```python
@dataclass(frozen=True)
class PipelineProfile:
    name: str                      # "ltx_text_only", "wan_phantom_actions"
    description: str
    video_provider: str            # "ltx" | "wan_phantom" | "stub"
    audio_provider: str            # "chatterbox" | "stub"
    image_provider: str            # "sd35" | "stub"

    # Stage gates
    canonical_portrait_enabled: bool
    image_pregen_enabled: bool       # backgrounds + action stills
    face_restoration_enabled: bool   # Phase 2 post-LTX (planned)

    # Conditioning rules — what gets pinned where on the video provider
    pin_portrait_at_frame_zero: bool
    pin_action_stills: bool
    pin_last_frame_chain: bool
    drop_last_frame_on_tail: bool
    portrait_strength: float          # 0.0–1.0, ignored if pin_portrait_at_frame_zero=False
    action_still_strength: float

    # Visual director rules toggle (which HARD blocks apply)
    visual_director_far_camera: bool  # F-FAR-CAMERA
    visual_director_identity_echo: bool

    # Per-provider settings handed to the provider class
    provider_settings: dict           # opaque, validated by provider
```

### 2. Profile registry

`backend/app/orchestration/profiles.py`:

```python
PROFILES: dict[str, PipelineProfile] = {
    "ltx_text_only": PipelineProfile(
        name="ltx_text_only",
        description="LTX-Video FP8 distilled, text-only. Identity via "
                    "IDENTITY ECHO + last-frame chain. F-FAR-CAMERA on.",
        video_provider="ltx",
        audio_provider="chatterbox",
        image_provider="sd35",
        canonical_portrait_enabled=False,
        image_pregen_enabled=False,
        face_restoration_enabled=False,
        pin_portrait_at_frame_zero=False,
        pin_action_stills=False,
        pin_last_frame_chain=True,
        drop_last_frame_on_tail=True,
        portrait_strength=0.0,
        action_still_strength=0.0,
        visual_director_far_camera=True,
        visual_director_identity_echo=True,
        provider_settings={},  # picks up settings.ltx_*
    ),
    "wan_phantom_actions": PipelineProfile(
        name="wan_phantom_actions",
        description="Phantom-Wan 14B with reference-identity embedding + "
                    "per-second action stills as conditions.",
        video_provider="wan_phantom",
        audio_provider="chatterbox",
        image_provider="sd35",
        canonical_portrait_enabled=True,    # need it for identity embedding
        image_pregen_enabled=True,           # action stills are fed in
        face_restoration_enabled=False,      # Wan handles identity natively
        pin_portrait_at_frame_zero=False,    # Wan uses embedding, not frame pin
        pin_action_stills=True,
        pin_last_frame_chain=False,          # Wan handles continuity differently
        drop_last_frame_on_tail=False,
        portrait_strength=0.0,
        action_still_strength=0.7,
        visual_director_far_camera=True,
        visual_director_identity_echo=False, # Wan locks identity at model level
        provider_settings={
            "wan_model_id": "bytedance-research/Phantom",
            "wan_checkpoint": "phantom-wan-14b-fp16.safetensors",
            "wan_num_frames": 81,
            "wan_fps": 16,
            "wan_steps": 30,
            "wan_guidance": 5.0,
        },
    ),
    "wan_phantom_text": PipelineProfile(
        name="wan_phantom_text",
        description="Phantom-Wan 14B text-only — fastest Wan path, no stills.",
        video_provider="wan_phantom",
        audio_provider="chatterbox",
        image_provider="sd35",
        canonical_portrait_enabled=True,    # still need a portrait for identity
        image_pregen_enabled=False,
        face_restoration_enabled=False,
        pin_portrait_at_frame_zero=False,
        pin_action_stills=False,
        pin_last_frame_chain=False,
        drop_last_frame_on_tail=False,
        portrait_strength=0.0,
        action_still_strength=0.0,
        visual_director_far_camera=True,
        visual_director_identity_echo=False,
        provider_settings={ ...same as wan_phantom_actions... },
    ),
}

def get_profile(name: str) -> PipelineProfile:
    if name not in PROFILES:
        raise ValueError(f"Unknown profile: {name}. Choices: {list(PROFILES)}")
    return PROFILES[name]
```

### 3. Project carries the profile name

DB migration: `projects.pipeline_profile VARCHAR(64) NOT NULL DEFAULT 'ltx_text_only'`.
API contract: `POST /api/projects` accepts an optional `pipeline` field; defaults to `ltx_text_only` for backwards compat.

### 4. Stage code reads the profile, not `settings.*_enabled`

`stage_tasks.py:task_pregen_images`:

```python
profile = await load_project_profile(project_id)
if not profile.canonical_portrait_enabled and not profile.image_pregen_enabled:
    return  # full skip
if profile.canonical_portrait_enabled and not profile.image_pregen_enabled:
    await Pipeline().run_canonical_portrait(project_id)
    return
# else → full image_pregen
await Pipeline().run_image_pregen(project_id)
```

`scene_video.py:generate_single`:

```python
profile = await load_project_profile(project_id)
last_frame  = await _resolve_last_frame(...) if profile.pin_last_frame_chain else None
character   = await _resolve_character_image(scene) if profile.pin_portrait_at_frame_zero else None
action_imgs = await _resolve_action_images(...) if profile.pin_action_stills else []
if profile.drop_last_frame_on_tail and scene.order_index >= 3:
    last_frame = None
...
```

`visual_director.txt` becomes a Jinja-style template with optional blocks gated by `{% if profile.visual_director_far_camera %}…{% endif %}` — agent reads profile, fills the template before sending to LLM.

### 5. Provider plugins

Existing: `app/providers/video/{base,ltx_provider,stub_provider}.py`.

New: `app/providers/video/wan_phantom_provider.py`:

```python
class WanPhantomVideoProvider(VideoProvider):
    """Phantom-Wan 14B via subprocess call to wan_generate.py.
    Conditions on identity embedding + optional per-second action stills.
    Does NOT use frame-pin conditioning."""

    async def generate_video(
        self,
        prompt: str,
        negative_prompt: str,
        output_path: Path,
        video_settings: VideoSettings,
        condition_image_path: Optional[str] = None,
        character_image_path: Optional[str] = None,
        background_image_path: Optional[str] = None,
        scene_action_images: Optional[list[str]] = None,
        identity_embedding_path: Optional[str] = None,  # NEW arg
    ) -> VideoResult:
        cmd = [
            settings.gpu_python_path, "wan_generate.py",
            "--prompt", prompt,
            "--negative", negative_prompt,
            "--output", str(output_path),
            "--checkpoint", self.profile.provider_settings["wan_checkpoint"],
            "--frames", str(self.profile.provider_settings["wan_num_frames"]),
            "--fps", str(self.profile.provider_settings["wan_fps"]),
            "--steps", str(self.profile.provider_settings["wan_steps"]),
            "--guidance", str(self.profile.provider_settings["wan_guidance"]),
        ]
        if identity_embedding_path:
            cmd += ["--id-embed", identity_embedding_path]
        if scene_action_images:
            for i, p in enumerate(scene_action_images):
                cmd += [f"--action-{i}", p]
        ...
```

`get_video_provider(profile)` factory in `_common.py` becomes profile-aware.

### 6. Wan-side script (`wan_generate.py`, repo root)

Mirror of `ltx_generate.py`. Loads `Phantom-Wan` weights via `diffusers` or the `Phantom` repo's own pipeline class, runs single-pass inference with the args above, writes mp4. Respects `CUDA_VISIBLE_DEVICES`. Keep it as a subprocess so VRAM is released cleanly between scenes (same pattern as LTX).

---

## File changes summary

| Path | Status | Purpose |
|------|--------|---------|
| `backend/app/orchestration/profiles.py` | NEW | Profile dataclass + registry |
| `backend/app/models/project.py` | MODIFY | Add `pipeline_profile` column |
| `backend/alembic/versions/<new>.py` | NEW | DB migration |
| `backend/app/api/projects.py` | MODIFY | Accept `pipeline` field on POST |
| `backend/app/orchestration/_common.py` | MODIFY | `get_video_provider(profile)` etc. |
| `backend/app/orchestration/stages/scene_video.py` | MODIFY | Branch on profile fields |
| `backend/app/orchestration/tasks/stage_tasks.py` | MODIFY | Branch on profile fields |
| `backend/app/agents/visual_director_agent.py` | MODIFY | Render template with profile |
| `backend/app/prompts/visual_director.txt` | MODIFY | Wrap optional blocks in `{% if %}` |
| `backend/app/providers/video/wan_phantom_provider.py` | NEW | Wan provider plugin |
| `wan_generate.py` (repo root) | NEW | Subprocess inference script |
| `docs/FIXES_LOG.md` | MODIFY | Log F-PIPELINE-PROFILES |

---

## Migration rollout (suggested order)

1. **Refactor only — no Wan yet.** Add `PipelineProfile`, the registry with one profile (`ltx_text_only` matching today's behavior), the DB column with default. Replace every `settings.image_pregen_enabled` check with the profile field. Verify the existing pipeline still produces identical output to today's runs (M11/M12 unchanged).
2. **Add the Wan provider.** Build `wan_generate.py` as a standalone script first — test it independently with `python wan_generate.py --prompt … --output test.mp4` before wiring it into the backend. Verify VRAM frees between calls.
3. **Add Wan profile.** Register `wan_phantom_text` (text-only — simplest variant, no action stills). Run a smoke ad. Compare to LTX baseline on M11/M12/auto_total.
4. **Action-stills variant.** Register `wan_phantom_actions`. Re-enable `character_portraits` + `action_stills` agent paths gated by the profile. Run smoke. Compare.
5. **Eval split.** Update `eval_run.py` to record `pipeline_profile` in the result JSON so `improvement_loop.py` and dashboards can compare profiles side-by-side.
6. **API surface.** Add a `GET /api/pipelines` endpoint returning the registry so UI can populate a dropdown.

---

## Open decisions for the user

These are choices I'd ask you to make before I start coding:

1. **Profile selection UI.** Dropdown on the Create-Project form, or per-project override flag? (recommend dropdown.)
2. **Default profile.** Stick with `ltx_text_only` as default until Wan is proven, or flip default to Wan once it's better? (recommend keep LTX default, opt-in to Wan.)
3. **Concurrent profiles.** Should two projects with different profiles run on the same celery worker simultaneously, or serialise at the GPU level? Wan 14B + LTX FP8 won't both fit on a 16 GB card. (recommend serialise — profile-aware pipeline lock.)
4. **Phantom-Wan source.** Use Hugging Face `bytedance-research/Phantom` weights or a different Wan derivative? Confirm license is commercial-OK for ad content.
5. **VRAM budget.** Wan 14B fp16 ≈ 28 GB; even fp8 is ~14 GB. On the 16 GB 5070 Ti this needs sequential CPU offload similar to LTX. Acceptable cost or do we need to gate on a bigger GPU?
6. **Conditioning rules for Wan.** Phantom natively takes a reference portrait + per-frame OpenPose. Do we want the Wan profile to use OpenPose action-stills (different generation pipeline than the SD3.5 stills we use for LTX), or feed it the same SD3.5 stills?

---

## What I am NOT proposing

- **Per-stage profiles.** A single profile name covers the whole pipeline. If you want "LTX video with Wan audio" — that's a feature flag inside the profile, not a separate axis.
- **Runtime profile mutation.** A project's profile is fixed at creation. Re-running needs a new project (same as today's behavior).
- **Re-introducing frame-condition pictures into LTX.** Per `feedback_no_frame_conditioning_pictures.md` — the LTX profile keeps `pin_portrait_at_frame_zero=False`. Other profiles (Wan) can choose differently because Wan handles it differently.
- **Migrating existing projects.** Old projects without a `pipeline_profile` column get the default `ltx_text_only` via the DB default. No backfill.

---

## Verification

- After step 1 (refactor only): run the improvement loop's `running_shoes` ad. Auto_total within ±0.02 of pre-refactor baseline. No regression.
- After step 3 (Wan smoke): visually compare a Wan-generated `running_shoes` to an LTX one. M11 expected ≥0.85 because Wan locks identity at the model level. Motion quality is the open question — Phantom-Wan is reportedly weaker on dynamic action than LTX.
- After step 4 (Wan + actions): the action-still pipeline should give Wan the pose locking it lacks intrinsically. Expect M12 (full-body) ≥0.8.

---

## Concrete Phantom-Wan integration (focus first)

After surveying the upstream code at `~/Phantom/` (cloned from `github.com/Phantom-video/Phantom`):

### What Phantom actually is
**Subject-driven video generation** built on Wan 2.1. Takes 1–4 **reference images** + a text prompt and generates video with the subject's identity preserved. Identity injection happens **at the model level** via a custom `phantom_wan.Phantom_Wan_S2V` pipeline — it does NOT pin frames the way LTX did, so it sidesteps the morph failure mode that wrecked F-CANON-PORTRAIT.

### Two checkpoint sizes (single HF repo)
- **Phantom-Wan-1.3B** — single `Phantom-Wan-1.3B.pth` (~2.5 GB). Fits comfortably on 12 GB. Lower fidelity.
- **Phantom-Wan-14B** — 6 sharded safetensors (~30 GB total). Fits a single 24 GB+ card or 2× FSDP across the 5070 Ti (16 GB) + 4070 Ti (12 GB).

Both checkpoints share the **Wan 2.1 1.3B base model** at `--ckpt_dir` for text encoder + VAE — the variation is only in the diffusion transformer.

### Required on disk (downloads in flight)

| Asset | Source | Size | Status |
|---|---|---|---|
| `~/Phantom/` repo | `github.com/Phantom-video/Phantom.git` | ~50 MB | ✅ cloned |
| `~/Phantom-Wan-Models/` (14B + 1.3B ckpts) | `bytedance-research/Phantom` (HF) | ~30 GB | ⏳ downloading |
| `~/Wan2.1-T2V-1.3B/` (base for shared components) | `Wan-AI/Wan2.1-T2V-1.3B` (HF, NOT Diffusers variant) | ~5 GB | ⏳ downloading |

### Wrapper: `wan_generate.py` (already written, repo root)
Mirrors `ltx_generate.py`'s subprocess interface so the backend can swap providers via PipelineProfile. Translates our args → upstream `python ~/Phantom/generate.py` flags. Single-GPU by default; multi-GPU FSDP is the upstream `torchrun` path and would be a separate wrapper.

### Inference command (single-GPU, what the wrapper builds)
```bash
cd ~/Phantom && python generate.py \
    --task s2v-14B \
    --size 832*480 \
    --frame_num 121 \
    --sample_fps 24 \
    --sample_steps 50 \
    --base_seed 42 \
    --ckpt_dir ~/Wan2.1-T2V-1.3B \
    --phantom_ckpt ~/Phantom-Wan-Models \
    --ref_image "ref1.png,ref2.png" \
    --prompt "..." \
    --t5_cpu \
    --save_file out.mp4
```

### VRAM strategy on our hardware (5070 Ti 16 GB + 4070 Ti 12 GB)
Phantom doesn't ship FP8 layerwise casting, so 14B at fp16 = ~28 GB transformer weights. Three options ordered by risk:

1. **Phantom-Wan-1.3B single-GPU on the 4070 Ti** — derisks the integration. ~2.5 GB transformer, fits with room to spare. Run this FIRST to confirm the wrapper + repo paths work end-to-end. Quality ceiling lower than 14B but proves the stack.
2. **Phantom-Wan-14B with 2-GPU FSDP** — the upstream way. `torchrun --nproc_per_node=2 generate.py --dit_fsdp --t5_fsdp …` shards the 28 GB transformer across both GPUs. We'd need a second wrapper script (`wan_generate_distributed.py`) that calls torchrun. Combined 28 GB is exactly at the edge — likely OOMs unless we also `--t5_cpu`.
3. **Phantom-Wan-14B single-GPU with `enable_sequential_cpu_offload`** — Phantom doesn't expose this directly, but we could patch `phantom_wan/subject2video.py` to call `pipe.enable_sequential_cpu_offload()` after pipeline construction. Slow (~5 min per 5 s clip estimated) but works. Last-resort fallback.

**Recommended derisking order:** 1 → 2 → 3.

### Backend wiring (after smoke succeeds)
Per the profile registry above:
- **Provider plugin:** `backend/app/providers/video/wan_phantom_provider.py` — wraps `wan_generate.py` via subprocess (same pattern as `LTXVideoProvider` wrapping `ltx_generate.py`).
- **Profile field used:** `pin_action_stills=True` for `wan_phantom_actions` profile makes the orchestrator pass action stills as additional `--ref-image` args (Phantom takes up to 4). For `wan_phantom_text`, just the canonical portrait is passed.
- **Reference images:** Phantom's first ref image should be the canonical portrait (identity), additional refs can be product / scene-action stills if `pin_action_stills=True`.
- **Frame budget:** Phantom default is 121 frames @ 24 fps = ~5 s per clip — close enough to LTX's 57 frames @ 12 fps = 4.75 s. Adjust the profile's `provider_settings` to match the project's per-scene duration.

### What the FE will see (deferred but unblocked)
- `GET /api/pipelines` returns `[{name, description, model_size, vram_min_gb, supports_identity, recommended_for}]` from the registry.
- `POST /api/projects` accepts optional `pipeline` field — defaults to `ltx_text_only`. Frontend dropdown populated from `/api/pipelines` response. No DB changes beyond the one new column.
- Project detail endpoint surfaces `pipeline_profile` so the UI can label which model was used.

### Smoke test plan (once both downloads finish)

```bash
# 1. Sanity: 1.3B on 4070 Ti, single-GPU, one ref image
CUDA_VISIBLE_DEVICES=1 python wan_generate.py \
    --task s2v-1.3B \
    --prompt "A man in his early 30s in a charcoal performance tee runs down a street at dawn." \
    --ref-image /tmp/test_portrait.png \
    --output /tmp/wan_smoke_1p3b.mp4 \
    --t5-cpu

# 2. Same prompt, 14B, single-GPU sequential offload (path 3)
CUDA_VISIBLE_DEVICES=0 python wan_generate.py \
    --task s2v-14B \
    --prompt "..." \
    --ref-image /tmp/test_portrait.png \
    --output /tmp/wan_smoke_14b.mp4 \
    --t5-cpu

# 3. Visual + InsightFace M11 comparison vs an LTX baseline of the same prompt.
```

Any of these commands also need the running improvement loop to be paused, since they'll fight LTX for the 5070 Ti.
