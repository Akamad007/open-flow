# Video Generation Pipeline — Data Flow

End-to-end map of the storyvideo pipeline: every prompt that is built, every model
that consumes it, every DB row that is written, and every API surface that exposes
the result. Used as the contract between backend stages and the UI.

> All file paths are relative to `backend/app/` unless noted. Scene-level data lives
> on `scenes` + `scene_prompts` (1:1 by `scene_id`). Project-level on `projects`
> + `audio_plans` (1:1 by `project_id`). Generated artifacts live on `assets` keyed
> by `(project_id, scene_id?, asset_type)`. Stage execution is tracked on
> `render_jobs` keyed by `(project_id, job_type)` with a Celery `task_id`.

---

## 1. Story analysis  → beats / characters / locations / style_lock

| What | Where |
|---|---|
| Agent | `agents/story_analyst.py` |
| Stage | `orchestration/stages/story_analysis.py` |
| Job type | `story_analysis` |
| LLM | `llm.complete_json` (default `gpt-4o-mini`, see `Settings.llm_model`) |
| System prompt | `prompts/story_analyst.txt` |
| User prompt | `story_analyst.py:24-64` (story text + extraction rules) |
| Inputs | `projects.original_story_text`, `total_target_duration_seconds` |
| Writes | `projects.story_summary`, `beat_list_json`, `pacing_notes`, `style_lock`; rows in `characters` (`canonical_name`, `physical_description`, `clothing_description`, `personality_notes`, `voice_notes`); rows in `locations` (`name`, `description`) |
| API | `GET /projects/{id}` (project fields), `GET /projects/{id}/characters`, `GET /projects/{id}/locations` |

**Style-lock contract.** A single sentence (≤25 words) that every downstream visual
prompt is required to embed verbatim. Drift here propagates everywhere.

---

## 2. Scene planning  → scene rows + per-second beats

| What | Where |
|---|---|
| Agent | `agents/scene_planner.py` |
| Stage | `orchestration/stages/scene_planning.py` |
| Job type | `scene_planning` |
| LLM | `llm.complete_json` |
| System prompt | `prompts/scene_planner.txt` |
| User prompt | `scene_planner.py:52-103` (story, beats, characters, locations, target counts) |
| Inputs | `projects.beat_list_json`, target scene duration (`6.0s`), `total_target_duration_seconds`, character/location lists |
| Writes | `scenes` (`order_index`, `source_excerpt`, `duration_seconds`, `scene_purpose`, `visual_summary`, `audio_alignment_notes`, `continuity_from_previous`, `continuity_to_next`, `location_id`, `status='planned'`); junction rows in `scene_characters`. The planner also emits a `per_second_plan` array of `{second, action, camera_note}` that becomes the seed for both the visual director and the per-second action stills. |
| API | `GET /projects/{id}/scenes`, `GET /scenes/{id}` |

**Hard constraint.** `required_scenes = round(total_target_duration / 6.0)`. The
planner is instructed to produce exactly that many scenes; any deviation is a bug.
Locations must be reused from the known list (no inventing new strings).

---

## 3. Visual director  → ScenePrompt (the core LTX prompt)

| What | Where |
|---|---|
| Agent | `agents/visual_director.py` |
| Stage | `orchestration/stages/prompt_generation.py` |
| Job type | `prompt_generation` |
| LLM | `llm.complete_json` with `Settings.llm_strong_model` (default `gpt-4o`), temperature `0.4` |
| System prompt | `prompts/visual_director.txt` (the 6-Dimension Framework) |
| User prompt | `visual_director.py:72-170` |
| Inputs | story_summary, pacing_notes, style_lock, scene visual_summary + per_second_plan, characters in scene (with descriptions), full cast (consistency), continuity from/to neighbors. Optional critique-feedback block when re-running after consistency review. |
| Writes | `scene_prompts` (`video_prompt`, `negative_prompt`, `style_notes`, `camera_plan`, `camera_angle`, `subject_description`, `environment_description`, `action_description`, `continuity_guardrails`, `scene_breakdown`, `critic_notes`, `approved=False`); `scenes.status='prompted'` |
| API | `GET /scenes/{id}` (returns nested `prompt`); `PUT /scenes/{id}/prompt` (manual override) |

**Output contract — per scene_prompt:**

- `video_prompt`: ≤150 words, present tense, embeds every `0–1s:`, `1–2s:` … line verbatim. This is what LTX consumes.
- `negative_prompt`: must contain the canonical anti-list: `text, subtitles, watermark, logo, title card, letters, words, folk art, static camera, frozen, jitter, flickering, temporal inconsistency, blurry, distorted`.
- `scene_breakdown`: one line per second of the scene; the planner's per_second_plan shaped into the form LTX is conditioned on.

---

## 4. Audio director  → continuous narration + timing map

| What | Where |
|---|---|
| Agent | `agents/audio_director.py` |
| Stage | `orchestration/stages/audio_planning.py` |
| Job type | `audio_planning` |
| LLM | `llm.complete_json`, temperature `0.6` |
| System prompt | `prompts/audio_director.txt` |
| User prompt | `audio_director.py:61-103` (story, full scene table inc. `video_prompt` of each scene, character voice_notes, target duration) |
| Inputs | All scenes + their `video_prompt` (so narration matches on-screen action), characters' `voice_notes`, `total_target_duration_seconds` |
| Writes | `audio_plans` (`full_story_narration_text`, `full_story_dialogue_plan`, `full_story_audio_prompt`, `ambience_progression_notes`, `sound_transition_notes`, `total_estimated_audio_duration`, `timing_map_json`, `approved=False`); back-fills `scenes.target_audio_segment_start/end` from `timing_map_json` |
| API | `GET /projects/{id}/audio-plan`, `PUT /audio-plans/{id}` |

**Timing map shape:** `[{scene_index, audio_segment_start, audio_segment_end, narration_excerpt, transition_note}, …]`.

---

## 5. Consistency critic  → fix scenes that fail the 11-point checklist

| What | Where |
|---|---|
| Agent | `agents/consistency_critic.py` |
| Stage | `orchestration/stages/consistency_review.py` |
| Job type | `consistency_review` |
| LLM | `llm.complete_json`, temperature `0.3` |
| System prompt | `prompts/consistency_critic.txt` (11-point checklist) |
| User prompt | `consistency_critic.py:48-97` (every scene's video_prompt, characters, audio plan, target duration) |
| Inputs | All scene_prompts + audio_plan + characters |
| Writes | `render_jobs.result_json` for `consistency_review` row: `{overall_quality, issues:[{scene_index, issue_type, description, severity}], suggestions, approved}`. If `approved=False` and any issue is `medium`/`high`, the stage re-invokes the visual director on flagged scenes with a critique-feedback block injected. The corrected `scene_prompts.video_prompt` overwrites the originals; `critic_notes` records the rationale. |
| API | _Currently not exposed._ Lives only on `render_jobs.result_json`. (Surfacing this is an action item — see fool-proof plan.) |

---

## 6. Image pregeneration  → SD 3.5 Medium reference + per-second stills

Three parallel passes. All run through `agents/image_pregen_agent.py` and the
`agents/image_pregen/` sub-package; orchestration is `orchestration/stages/image_pregen.py`.
Job type: `image_pregen`.

### 6a. Character portraits

| What | Where |
|---|---|
| Builder | `image_pregen/character_portraits.py` |
| Prompt LLM | `llm.complete_json` — system `prompts/character_portrait.txt`, user `image_pregen/prompts.py:26-33` (character physical + clothing + story_summary) |
| Returns | `portrait_prompt`, `negative_prompt` |
| Image model | SD 3.5 Medium, `width=sd35_char_width`, `height=sd35_char_height`, steps `sd35_steps`, guidance `sd35_guidance`. After generation, background is removed (`human_seg`). |
| Writes | `characters.reference_image_path`; `assets` row (`asset_type='character_ref'`, `metadata_json`, `generation_params_json`, `generation_provider='StableDiffusion3.5Provider'`) |

### 6b. Background plates

| What | Where |
|---|---|
| Builder | `image_pregen/backgrounds.py` |
| Prompt LLM | system `prompts/background_scene.txt`, user `image_pregen/prompts.py:58-64` (location + story_summary) |
| Image model | SD 3.5 at `sd35_bg_width × sd35_bg_height`. **Negative includes "people, characters, person, human"** to keep plates empty. |
| Writes | `locations.reference_image_path`; `assets` row (`asset_type='background_ref'`) |

### 6c. Action stills (per-second)

| What | Where |
|---|---|
| Builder | `image_pregen/action_stills.py` |
| Prompt LLM | system `prompts/scene_action_portrait.txt`, user `image_pregen/prompts.py:100-137` (character + WHAT-at-second-N, with environment/style explicitly stripped) |
| Image model | SD 3.5 img2img — strength `0.35` for the first still, `0.55` for chained subsequent stills. `init_image` is the prior still (or the character portrait for `s00`). Background-removed afterwards. |
| Sidecars | `{still}_opaque.png` (pre-removal), `{still}_prompt.txt` (LLM prompt + negative — read by `still_critic.py` and the UI) |
| Writes | One `assets` row per second (`asset_type='scene_action_seq'`, `metadata_json` carries scene_index + second + strength); `scenes.scene_ref_image_path` set to the first still |

### 6d. Still critic (vision-LLM, non-blocking)

`agents/still_critic.py` runs after the stills are generated. It vision-inspects
the **first still of each scene** against `scene.visual_summary` and reports:
composition issues, missing body parts (legs for walking, hands for holding),
anatomy errors, burned-in text. Output is logged and stored on the
`image_pregen` `render_jobs.result_json`; **it does not block the pipeline.**

API: `GET /projects/{id}/images` returns `{characters[], locations[], scene_refs[]}`,
where each `scene_ref` includes `action_image_seq[]` of `{url, prompt, negative}`
(read from the sidecar `_prompt.txt`).

---

## 7. Scene video generation  → LTX-Video 0.9.8 dev (per scene)

| What | Where |
|---|---|
| Agent | `agents/asset_orchestrator.py::generate_scene_video` |
| Stage | `orchestration/stages/scene_video.py` (Celery chord, one task per scene) |
| Job type | `video_generation` (per scene) |
| Provider | `providers/video/ltx_provider.py` shells out to `/home/akash/PycharmProjects/video-app/ltx_generate.py` |
| Prompt | `scene.prompt.video_prompt` (the only thing LTX reads — every other artifact is conditioning) |
| Negative | `scene.prompt.negative_prompt` |
| Conditioning | (1) prior scene's last frame — extracted via `ltx_generate.py --extract-last-frame` after each scene completes, used as I2V seed for the next; (2) character portrait (background-removed); (3) background plate (composited behind character); (4) the per-second action stills — one per second of `duration_seconds`. |
| Settings | `ltx_num_frames=73`, `ltx_fps=12` (= 6.083 s, the closest 8n+1 frame count to 6 s); height/width/steps/guidance from `Settings.ltx_*`. |
| Writes | `assets` (`asset_type='scene_video'`, `scene_id`, `file_path`, `metadata_json` — duration, fps, resolution, model id, has_character/has_background/has_action_stills flags, `generation_params_json`); `scenes.status='generated'`/`'failed'` |
| API | `GET /projects/{id}/assets`, `GET /assets/{id}/file` (streams MP4) |

---

## 8. Audio generation  → full-story Chatterbox WAV

| What | Where |
|---|---|
| Agent | `agents/asset_orchestrator.py::generate_full_story_audio` |
| Stage | `orchestration/stages/audio_generation.py` |
| Job type | `audio_generation` |
| Provider | `providers/audio/chatterbox_provider.py` (shells out to `/home/akash/PycharmProjects/video-app/chatterbox_generate.py`) |
| Inputs | `audio_plans.full_story_narration_text`, `full_story_audio_prompt` (voice description), `total_estimated_audio_duration`, reference voice WAV at `Settings.chatterbox_reference_audio` |
| Writes | `assets` (`asset_type='full_story_audio'`, `metadata_json` includes actual duration); `projects.final_audio_duration_seconds` |
| API | `GET /projects/{id}/assets`, `GET /assets/{id}/file` (streams WAV) |

---

## 9. Stitching  → final render

| What | Where |
|---|---|
| Agent | `agents/stitching_agent.py` |
| Stage | `orchestration/stages/stitching.py` |
| Job type | `stitching` |
| Provider | `ffmpeg` shell-out (`Settings.ffmpeg_path`) |
| Inputs | All `scene_video` assets (status `complete`) ordered by `scenes.order_index`, plus the `full_story_audio` asset |
| Writes | `assets` (`asset_type='final_render'`, `file_path=storage/renders/{project_id}/final_render.mp4`); `projects.status='complete'` |
| API | `GET /projects/{id}/assets`, `GET /assets/{id}/file` |

---

## API → field index (what the UI can see today)

| Endpoint | Surfaces |
|---|---|
| `GET /projects` | id, title, status, story_summary, beat_list_json, pacing_notes, style_lock, scene_count, total_target_duration_seconds, final_audio_duration_seconds |
| `GET /projects/{id}` | as above |
| `GET /projects/{id}/scenes` | scene rows + nested `prompt` (every ScenePrompt column) + `characters` + `location` |
| `GET /projects/{id}/characters` | every `characters` column inc. `reference_image_path` |
| `GET /projects/{id}/locations` | every `locations` column inc. `reference_image_path` |
| `GET /projects/{id}/audio-plan` | every `audio_plans` column inc. `timing_map_json`, `full_story_dialogue_plan` |
| `GET /projects/{id}/images` | character portraits, background plates, per-scene action stills with prompt+negative sidecars |
| `GET /projects/{id}/assets` | every `assets` column inc. `metadata_json`, `generation_params_json` |
| `GET /projects/{id}/jobs` | every `render_jobs` column inc. `payload_json`, `result_json`, `error_text`, `celery_task_id` |
| `GET /assets/{id}/file` | streams the underlying media file |

The data is already on the wire — what's missing is UI rendering for `metadata_json`,
`generation_params_json`, `payload_json`, `result_json`, `timing_map_json`,
`beat_list_json`, `pacing_notes`, `full_story_dialogue_plan`, the prompt
sidecars, and the relationship between scenes ↔ characters ↔ locations.
