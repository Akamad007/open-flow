# Configurable Pipeline Architecture

## Goal

Today the pipeline is hard-wired around LTX-Video. Switching the video model
to **Wan 2.1 14B / Phantom-Wan** (or any future model) should be a config
change, not a rewrite. Different models need different pre-stages: LTX runs
pure text-to-video (image conditions hurt it); Wan/Phantom is built around
reference images and per-shot action stills, so its pipeline must include
the image-pregen path that LTX skips.

**Concrete user requirement:**
- "LTX pipeline" = `prompt → visual scene → video` (text-only, no stills).
- "Phantom-Wan-14B pipeline" = same plus `character portrait → action sequences → image-conditioned video`.
- Selectable per project (or per-call) via a single setting.

---

## What is hard-wired today

1. **Pipeline chain** in [full_pipeline.py](backend/app/orchestration/tasks/full_pipeline.py:25-35):
   ```python
   chain(analyze, plan_scenes, generate_prompts, plan_audio,
         review_consistency, pregen_images, dispatch_video_chord)
   ```
   Same chain for every model; `pregen_images` self-skips when `image_pregen_enabled=False`.
2. **Stage gating** by a single boolean `settings.image_pregen_enabled` — coarse. There is no way to say "for Wan, run portrait + action stills; for LTX, run nothing".
3. **Provider selection** by `settings.video_provider` ([_common.py](backend/app/orchestration/_common.py:88)). Each provider is selected by string but its pipeline shape is not part of the selection.
4. **Prompt template** [visual_director.txt](backend/app/prompts/visual_director.txt) is shared by all models. Its CAMERA DISTANCE / FULL BODY / IDENTITY ECHO rules were tuned for LTX text-only output. Wan would benefit from different framing (it can use reference images, so identity rules can soften).
5. **Per-scene conditioning** in [scene_video.py:_select_conditioning](backend/app/orchestration/stages/scene_video.py:106-134) is hard-coded to LTX's "last-frame chain only" rules. Wan would want portrait + action stills passed through.
6. **LTX-specific quirks** baked into the provider:
   - `_FAR_CAMERA_PREFIX` in [ltx_provider.py](backend/app/providers/video/ltx_provider.py) (only relevant when LTX drifts to close-ups).
   - Gray placeholder injection in [ltx_generate.py](ltx_generate.py:455-461) (LTXConditionPipeline workaround).
   - `--background-image` pass-through used only for pipeline-class selection.

---

## Proposed architecture

### Core idea: a `PipelineSpec` object

A pipeline is a list of named stages with per-stage flags. Each video provider declares the spec it wants. At dispatch time we build the Celery chain from the spec instead of hard-coding it.

```python
# backend/app/orchestration/spec.py (NEW)
@dataclass(frozen=True)
class StageSpec:
    name: str                       # "analyze_story", "pregen_portraits", ...
    enabled: bool = True
    config: dict | None = None      # arbitrary stage params

@dataclass(frozen=True)
class PipelineSpec:
    name: str                       # "ltx_text_only", "phantom_wan_14b"
    video_provider: str             # "ltx" | "phantom_wan" | "stub"
    stages: tuple[StageSpec, ...]
    prompt_template_path: str       # which visual_director-style template to use
    conditioning: dict              # what to pass to the video provider per scene
                                    # e.g. {"portrait": True, "action_stills": True,
                                    #       "background": True, "last_frame": True}
```

### Two named specs to ship

```python
LTX_TEXT_ONLY = PipelineSpec(
    name="ltx_text_only",
    video_provider="ltx",
    stages=(
        StageSpec("analyze_story"),
        StageSpec("plan_scenes"),
        StageSpec("generate_prompts", config={"template": "visual_director_ltx.txt"}),
        StageSpec("plan_audio"),
        StageSpec("review_consistency"),
        StageSpec("pregen_portraits", enabled=False),    # LTX skips
        StageSpec("pregen_backgrounds", enabled=False),
        StageSpec("pregen_action_stills", enabled=False),
        StageSpec("dispatch_video_chord"),
        StageSpec("generate_audio"),
        StageSpec("stitch"),
    ),
    prompt_template_path="prompts/visual_director_ltx.txt",
    conditioning={
        "portrait": False,
        "action_stills": False,
        "background": False,
        "last_frame": True,        # last-frame chain only
        "last_frame_tail_purge": 3 # drop for scene_index >= 3
    },
)

PHANTOM_WAN_14B = PipelineSpec(
    name="phantom_wan_14b",
    video_provider="phantom_wan",
    stages=(
        StageSpec("analyze_story"),
        StageSpec("plan_scenes"),
        StageSpec("generate_prompts", config={"template": "visual_director_wan.txt"}),
        StageSpec("plan_audio"),
        StageSpec("review_consistency"),
        StageSpec("pregen_portraits", enabled=True),     # Wan needs these
        StageSpec("pregen_backgrounds", enabled=True),
        StageSpec("pregen_action_stills", enabled=True), # Wan can use action stills
        StageSpec("dispatch_video_chord"),
        StageSpec("generate_audio"),
        StageSpec("stitch"),
    ),
    prompt_template_path="prompts/visual_director_wan.txt",
    conditioning={
        "portrait": True,
        "action_stills": True,
        "background": True,
        "last_frame": True,
        "last_frame_tail_purge": None,   # don't purge — Wan handles drift better
    },
)
```

Specs live in `backend/app/orchestration/specs/` (one file per spec). Adding a new model = add a new file + register in `REGISTRY`.

### Selection

```python
# backend/app/orchestration/specs/__init__.py
REGISTRY = {
    "ltx_text_only": LTX_TEXT_ONLY,
    "phantom_wan_14b": PHANTOM_WAN_14B,
}

def resolve_spec(name: str | None) -> PipelineSpec:
    return REGISTRY[name or settings.default_pipeline]
```

Settings get one new field:
```python
# config.py
default_pipeline: str = "ltx_text_only"
```

A project can override with a column `Project.pipeline_name` — empty falls back to default.

### Chain builder reads the spec

```python
# full_pipeline.py
def build_pipeline_workflow(project_id: str):
    spec = resolve_spec(_lookup_project_pipeline(project_id))
    tasks = []
    for stage in spec.stages:
        if not stage.enabled:
            continue
        task = STAGE_TASK_MAP[stage.name].si(project_id)
        tasks.append(task)
    return chain(*tasks)
```

`STAGE_TASK_MAP` is the existing `{name: task}` dict from `tasks/stage_tasks.py`, just made explicit.

### Per-provider conditioning

`scene_video.generate_single` reads the spec's `conditioning` dict and passes only the inputs the spec asks for:

```python
spec = resolve_spec(_lookup_project_pipeline(project_id))
character = await _resolve_character_image(scene)   if spec.conditioning["portrait"]      else None
background = await _resolve_background_image(scene) if spec.conditioning["background"]    else None
action_imgs = await _resolve_action_images(scene)   if spec.conditioning["action_stills"] else []
last_frame = await _resolve_last_frame(scene)       if spec.conditioning["last_frame"]    else None
purge = spec.conditioning["last_frame_tail_purge"]
if purge and scene.order_index >= purge:
    last_frame = None
```

This kills the F-CANON-PORTRAIT-REVERTED tail-scene purge being a hard-coded value — it becomes a per-spec knob.

### Per-provider prompt template

Today `visual_director.txt` is the only template. Split into:
- `prompts/visual_director_ltx.txt` — current file (CAMERA DISTANCE, IDENTITY ECHO, FULL BODY, no-image-conditioning rules — tuned for text-only LTX).
- `prompts/visual_director_wan.txt` — new file. Drops the IDENTITY ECHO HARD repetition (Wan handles identity from reference image), softens the FULL BODY rule (Wan can use action stills for body anchors), keeps the per-second beat structure.

Loading switches by `spec.prompt_template_path`.

### Provider abstraction additions

Today `VideoProvider.generate_video` accepts `condition_image_path`, `character_image_path`, `background_image_path`, `scene_action_images`. That signature is fine — Wan's provider just consumes more of them than LTX's.

New file: `backend/app/providers/video/phantom_wan_provider.py`. Same interface, different subprocess + different prompt prefix logic. Drop the LTX `_FAR_CAMERA_PREFIX` (Wan can be told distance via reference images / text without the brute hack).

`get_video_provider()` extends:
```python
if settings.video_provider == "ltx":          return LTXVideoProvider()
if settings.video_provider == "phantom_wan":  return PhantomWanProvider()
return StubVideoProvider()
```

---

## Migration path (no big-bang)

1. **Land the spec/registry**, keeping LTX_TEXT_ONLY as the default. No behaviour change. Pipeline chain still produces the same Celery tasks, but they come from the spec list.
2. **Move ltx-specific guards into the spec** (tail_purge=3, conditioning flags). Delete the hard-coded checks in `scene_video.py`.
3. **Split the prompt template** into `visual_director_ltx.txt`. Stop reading `visual_director.txt` directly.
4. **Add Phantom-Wan provider** (subprocess wrapper around the Wan inference script — see Open Questions below).
5. **Add PHANTOM_WAN_14B spec** — at this point you can flip `settings.default_pipeline = "phantom_wan_14b"` per project and the right stages light up.
6. **A/B**: same project under both specs, compare metrics + visual quality.

Each step ships independently. Step 1–3 alone removes the "LTX-shaped" hard-coding and makes the codebase flexible without anyone using a second model yet.

---

## Critical files / new files

| File | Status | Purpose |
|------|--------|---------|
| `backend/app/orchestration/spec.py` | NEW | `StageSpec`, `PipelineSpec` dataclasses |
| `backend/app/orchestration/specs/__init__.py` | NEW | `REGISTRY`, `resolve_spec()` |
| `backend/app/orchestration/specs/ltx_text_only.py` | NEW | LTX_TEXT_ONLY spec |
| `backend/app/orchestration/specs/phantom_wan_14b.py` | NEW | PHANTOM_WAN_14B spec |
| `backend/app/orchestration/tasks/full_pipeline.py` | EDIT | Build chain from spec, not hard-coded |
| `backend/app/orchestration/stages/scene_video.py` | EDIT | Read conditioning dict from spec |
| `backend/app/orchestration/tasks/stage_tasks.py` | EDIT | Stage tasks read `enabled` flag from spec |
| `backend/app/prompts/visual_director_ltx.txt` | RENAME from `visual_director.txt` | LTX-specific prompt rules |
| `backend/app/prompts/visual_director_wan.txt` | NEW | Wan-specific prompt rules |
| `backend/app/providers/video/phantom_wan_provider.py` | NEW | Wan video provider |
| `backend/app/orchestration/_common.py` | EDIT | `get_video_provider()` adds Wan branch |
| `backend/app/config.py` | EDIT | `default_pipeline: str = "ltx_text_only"` |
| `backend/app/models/project.py` | EDIT | Optional `pipeline_name: str \| None` column |

---

## Open questions

1. **Wan inference path**: do we wrap the official Wan repo (PyTorch CLI) like we wrap LTX, or use a HuggingFace `diffusers` pipeline? The latter is simpler if Wan is on `diffusers`. Need to confirm.
2. **VRAM budget**: Wan 14B on a single 5070 Ti (16 GB) needs FP8 + offload like LTX. The existing `enable_layerwise_casting` + `enable_sequential_cpu_offload` plumbing in `ltx_generate.py` is reusable; the Wan wrapper should mirror it.
3. **Action-still re-enablement**: today action stills are blocked by `image_pregen_enabled=False` AND by [ltx_provider.py](backend/app/providers/video/ltx_provider.py) skipping them. The spec architecture lets us turn them back on for Wan only — but it requires resurrecting / fixing the still-rendering pipeline (was working pre-iter6, currently dormant).
4. **Per-spec metrics weights?** `eval_run.py` weights are calibrated for the current LTX path (M11 + M12 dominant). Wan output may need different weights. For now: keep one weight set and let the loop's threshold-based fix selection self-tune.
5. **Prompt template inheritance**: instead of two ~250-line files diverging, consider a base template + per-model override blocks. Defer until we actually have two specs and can see what differs.
6. **Pipeline selection UX**: project creation API today has no "pipeline" field. Add `pipeline_name` to `POST /api/projects`, with default = `settings.default_pipeline`.

---

## What this enables (concrete)

- `POST /api/projects { pipeline_name: "phantom_wan_14b", ... }` runs portrait + action stills + image-conditioned Wan video.
- `POST /api/projects { pipeline_name: "ltx_text_only", ... }` runs the current text-only LTX path.
- New model X arrives: write `specs/x.py`, `providers/video/x_provider.py`, optionally `prompts/visual_director_x.txt`. No core pipeline code edits.
- The improvement-loop fixes apply per-spec automatically — `fix_m12_full_body` lives in the LTX prompt file; an analogous Wan fix lives in the Wan prompt file. They don't collide.
- A/B testing the same project under two specs becomes a one-line config change.

---

## What this is NOT solving (deliberately)

- **No automatic prompt translation between specs.** A prompt written for LTX (with IDENTITY ECHO repeated per beat) won't be auto-rewritten for Wan; the spec just picks a different template at planning time.
- **No mixed-provider scenes within one project.** Each project pins one spec start to finish.
- **No spec versioning.** If a spec changes mid-run we don't snapshot it onto the project. Good enough for now; revisit if A/B comparisons diverge over time.
