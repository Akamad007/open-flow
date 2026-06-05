# Fool-Proofing Each Pipeline Stage

This is the action list to make every stage of the video pipeline produce
output of consistent, reviewable quality. It assumes the data flow described
in `pipeline-data-flow.md`.

A "fool-proof stage" has four properties:
1. **Inputs are validated** before the stage runs.
2. **Outputs are validated** before the next stage starts (hard gate, with
   a precise reason on failure).
3. **All intermediate prompts/decisions are persisted** (in `payload_json`,
   `result_json`, or asset metadata) so a human reviewer can audit them.
4. **A regen path** exists that consumes the validation feedback and
   produces a corrected output (no silent re-run with the same inputs).

The legend below uses `[P0]`/`[P1]`/`[P2]` for priority. P0 = ship-blocker
quality bug, P1 = high value, P2 = nice-to-have.

---

## Cross-cutting prerequisites

These touch every stage and should land first.

- **[P0] Persist `payload_json` for every stage.** Today it's null for most
  stages. Adopt a convention: at the top of every stage, write the inputs
  the agent saw — model id, system-prompt path, user-prompt rendered text,
  every DB id read. This is what reviewers grep when something looks off.
  See `orchestration/_common.py` for the helper to extend.
- **[P0] Persist a stable `result_json` shape per stage.** Today
  `consistency_review` and `image_pregen` write rich JSON; the others write
  nothing or a one-line summary. Standard fields: `{summary, model, tokens,
  duration_s, validation: {ok, errors[]}}`. Add an Alembic migration only
  if the schema requires new columns; everything fits in `result_json`
  already.
- **[P0] Validation gate.** Add `_common.validate_stage_outputs(stage_name,
  project_id)` that runs after each stage, raises a typed error on failure,
  and writes `result_json.validation` even on success. Wire it into every
  stage's epilogue.
- **[P1] Token + cost tracking.** Wrap `llm.complete_json` to record
  `input_tokens`, `output_tokens`, `model`, `duration_s` into `result_json`
  per call. Surface in the Jobs tab.
- **[P2] LLM caching.** Hash `(system_prompt, user_prompt, model,
  temperature)` and cache `result_json.body` for non-time-sensitive stages
  (story_analyst, scene_planner, audio_director). Replays during dev are
  free.

---

## Stage 1 — Story analysis

**Today's failure modes**

- Style lock comes back longer than 25 words or lacks key constraints
  (lighting/palette/mood); downstream prompts then carry inconsistent
  style.
- Characters get duplicated when the analyst splits one person across two
  beats (e.g. "Sadhguru" + "the speaker").
- Locations get invented per beat instead of consolidated.
- `beat_list_json` shape is loose (no schema enforcement on the
  `characters` / `location` fields).

**Fool-proofing actions**

- **[P0] Validate `style_lock`** post-call: word count ≤ 25; must mention
  ≥3 of `{lighting, color/palette, lens/film, mood/tone, time-of-day}`.
  Reject and re-prompt with a corrective hint up to 2 retries.
- **[P0] Deduplicate characters** by lowercased canonical_name and by
  fuzzy match (e.g. "Sadhguru" vs "Sadhguru / the speaker"). Merge
  descriptions before insert.
- **[P0] Cap location count** to `ceil(scenes / 2)` and re-prompt if the
  analyst exceeds it. The scene_planner is forbidden from inventing new
  locations, so the analyst is the choke point.
- **[P1] JSON-schema the `beat_list_json`** array (use Pydantic at the
  parse step). Reject malformed beats and retry.
- **[P1] Spot check via vision-LLM** when reference images are uploaded
  (e.g. user supplies a real photo of "Sadhguru"): the analyst should
  describe matching ethnicity/clothing/age. Use a small vision call as a
  cross-check, not a generation step.

**UI surfacing**: Story tab now shows beats / pacing / style_lock — extend
to flag style_lock violations inline (red border + reason).

---

## Stage 2 — Scene planning

**Today's failure modes**

- Scene count drifts off `total_target_duration / 6.0`.
- `per_second_plan` is missing or has fewer entries than
  `duration_seconds`.
- Characters listed for a scene aren't in the analyst's character list
  (planner hallucinates).
- Continuity strings (`continuity_from_previous`/`to_next`) are vague or
  contradictory.
- Locations not from the consolidated list (despite the system-prompt
  rule).

**Fool-proofing actions**

- **[P0] Hard-assert scene count** equals `required_scenes`. Re-prompt up
  to 2 times with `"You produced N scenes; produce exactly M."`.
- **[P0] Hard-assert per-second coverage**:
  `len(per_second_plan) == round(duration_seconds)`. Reject otherwise.
- **[P0] Membership checks** for scene characters (must be ⊂ analyst
  characters) and `location_name` (must be ⊂ analyst locations).
- **[P1] Continuity sanity**: scene N's `continuity_to_next` must be
  consistent with scene N+1's `continuity_from_previous` — string-match
  the entities mentioned (character names, location). Flag mismatches as
  warnings on the consistency_review stage.
- **[P1] Audio alignment notes** must reference the audio_plan timing
  windows once that plan exists; mark scenes whose visual_summary length
  vastly exceeds the time budget at 120 wpm.

**UI surfacing**: Scenes tab now shows location and characters per scene
(via the drawer). Add a per-second breakdown row in the card view next
iteration.

---

## Stage 3 — Visual director

This is the highest-leverage stage — a bad `video_prompt` cannot be
recovered downstream because LTX is conditioned on it directly.

**Today's failure modes**

- Per-second timestamps absent — LTX then produces static-feeling clips.
- Style lock not embedded verbatim — color/lighting drifts between
  scenes.
- Character physical description copy-pasted incorrectly between scenes
  (Scene N inherits Scene N-1's character).
- Negative prompt missing the canonical anti-list.
- Prompt overrun (>150 words) gets truncated by LTX.

**Fool-proofing actions**

- **[P0] Structural validation** of every ScenePrompt:
    - `video_prompt` ≤ 150 words.
    - Contains `0–1s:`, `1–2s:`, … timestamps for each second.
    - Contains the project's `style_lock` substring.
    - `negative_prompt` is a superset of the canonical anti-list.
    - `scene_breakdown` has exactly `duration_seconds` non-empty lines.
  Failure → re-prompt with a corrective system message that quotes the
  failed checks (max 2 retries). After that mark the prompt
  `approved=False` and surface the failure on Jobs.
- **[P0] Character-leak guard**: regex-grep `subject_description` for
  characters not in `scene.characters`. If found, abort and re-prompt
  with `"You must only describe {names}."`
- **[P1] Style-lock enforcement at insertion**: before save, prepend the
  style_lock sentence to `video_prompt` if the model omitted it. Cheaper
  than another LLM round-trip.
- **[P1] Cosine similarity between adjacent prompts** ≥ threshold for
  shared characters/locations — used as a soft gate that flags
  "discontinuity" issues to the consistency critic.
- **[P2] A/B parallel sampling**: produce 3 candidate prompts at temp
  0.4/0.6/0.8, score each by the structural checks, pick the highest.

**UI surfacing**: Drawer now shows the full prompt + approval badge +
critic notes. Add an inline "✓/✗" for each structural check next.

---

## Stage 4 — Audio director

**Today's failure modes**

- Narration totals more (or less) seconds at 120 wpm than the visual
  duration → final stitched output desyncs.
- `timing_map_json` doesn't cover every scene, or windows overlap/gap.
- Voice description (`full_story_audio_prompt`) drifts from the
  characters' `voice_notes`.
- Missing dialogue plan when the story has explicit dialogue.

**Fool-proofing actions**

- **[P0] Word-count budget**: target words = `duration * 2.0` (120 wpm).
  Reject narrations more than ±15% off-budget; re-prompt with the exact
  delta.
- **[P0] Validate timing_map_json**:
    - One entry per scene, in order.
    - `audio_segment_end - start ≈ scene.duration_seconds` (±0.3s).
    - No gaps or overlaps across the timeline.
- **[P0] Voice consistency**: `full_story_audio_prompt` must reference at
  least one character's `voice_notes` if narration is in-character.
- **[P1] Dialogue presence**: if any character has non-empty
  `voice_notes` and the story_summary mentions speaking, require a
  non-empty `full_story_dialogue_plan`. Re-prompt otherwise.
- **[P1] Pre-render TTS budget check**: dry-run Chatterbox length-only
  estimation (no audio bytes) to confirm the script fits the duration
  before committing.

**UI surfacing**: Audio tab now shows dialogue_plan + timing_map. Add a
red border on the timing-map row when a window mismatches its scene.

---

## Stage 5 — Consistency critic

**Today's failure modes**

- Outputs are written to `render_jobs.result_json` but never re-checked
  after the correction pass — if the corrective re-run still has issues,
  nothing flags it.
- The critic re-runs the *visual director*, not the *scene planner* —
  so structural mistakes baked at planning never get fixed.
- Severity scoring is fuzzy; the gate is "any high/medium". A "medium"
  issue with no fix path becomes a permanent thorn.

**Fool-proofing actions**

- **[P0] Re-validate after correction**: run the critic again on the
  corrected scenes. If still `needs_revision`, abort the pipeline with a
  clear status `consistency_failed` instead of marching on.
- **[P0] Issue → fix mapping**: each `issue_type` has a designated
  upstream stage (e.g. `duration` → scene_planner; `weak_prompt` →
  visual_director; `identity` → story_analyst character merge). Replay
  only the relevant stage, not all of them.
- **[P1] Persist per-issue pass/fail** after re-run on the same
  `result_json` (`fixed`, `still_failing`, `regressed`) so a human can
  see what improved.
- **[P2] Paired regression test**: when a critic catches a known issue
  type, store a fixture so we can replay the same failing prompt offline
  and prove the fix path works.

**UI surfacing**: Jobs tab now shows `result_json` so the critic's
issues array is reviewable. Add a "Critic" sub-tab next that filters
just consistency_review jobs and renders issues per scene.

---

## Stage 6 — Image pregeneration (SD 3.5)

This stage has the most moving parts. Three sub-passes each fail
differently.

### 6a. Character portraits

**Failures**: face cropped, wrong ethnicity, body half-cut, multiple
characters in one frame, burned-in text, wrong age.

**Fool-proofing**:

- **[P0] Vision-LLM verification** of every portrait: full body visible?
  matches `physical_description` ethnicity/age/gender? Single subject?
  No text? On rejection, regenerate with a corrective negative prompt.
  Currently `still_critic.py` does this only for action stills — extend
  to portraits.
- **[P0] Fixed seed per character per project**, recorded in
  `assets.metadata_json`. Re-rolls happen with seed+1 (not random) so
  failures are reproducible.
- **[P1] Reference photo upload path**: when a user uploads a real
  reference, switch to IP-Adapter / image-to-image at low strength
  instead of pure text-to-image.

### 6b. Backgrounds

**Failures**: people present despite negative, wrong time-of-day,
inconsistent palette across scenes that share a location.

**Fool-proofing**:

- **[P0] Vision-LLM verification**: no people detected; matches
  `description` time-of-day; no burned-in text.
- **[P0] One plate per location, reused across scenes** — already the
  design; assert no duplicate `background_ref` assets per location.
- **[P1] Palette extraction**: extract the dominant 5 colors and store
  on the asset's metadata. Compare against the `style_lock` palette
  (when extractable); flag drift.

### 6c. Per-second action stills

**Failures**: the still-critic already catches "off-center, face
cropped, legs not visible for walking action" — but the pipeline does
not act on the verdict.

**Fool-proofing**:

- **[P0] Make the still-critic blocking** for action stills marked
  `approved=False`: regenerate with a corrected prompt that fixes the
  framing/composition complaint. Today the verdict is observational only.
- **[P0] Composition guards** in the SD prompt template: always include
  "full body, all limbs visible, centered framing" when the action
  involves walking/running/kneeling/holding. The action-still LLM prompt
  already strips environment — extend to inject these composition
  hints based on action verbs.
- **[P1] Background-removal sanity check**: assert the alpha-channel
  coverage is between 15% and 60% (not entirely empty, not full-frame).
  Outliers → bg-removal failure → regenerate the still without bg
  removal and let LTX composite.
- **[P1] Same-character chain integrity**: every still in a scene's
  sequence must be derived from the prior still as init image (with the
  prescribed strength). Audit `metadata_json` to confirm; fail loudly
  on broken chains.

**UI surfacing**: Images tab now shows per-still prompt + negative
sidecar. Add the still-critic verdict per still next.

---

## Stage 7 — Scene video (LTX-Video)

**Today's failure modes**

- Output duration ≠ 6s (8n+1 frames constraint not met).
- Last-frame extraction silently fails → next scene loses I2V conditioning.
- Conditioning images path-mismatch (relative vs absolute).
- LTX returns success but produces black/frozen frames.

**Fool-proofing actions**

- **[P0] Post-render `ffprobe` validation** for every scene clip:
  - `duration_seconds` within 0.25s of target.
  - frame count == `ltx_num_frames` (== 73 for 6s).
  - non-zero motion: average inter-frame difference > a noise floor
    (cheap luma-variance test on 5 sampled frames).
  - sample 10 frames and check mean luma > 5/255 (catches all-black
    output).
  Fail the asset and queue retry on any check failure.
- **[P0] Retry policy**: 1 retry with the same conditioning, then 1
  retry that drops the prior-scene last-frame conditioning (in case the
  prior frame is the cause). Then fail loudly.
- **[P0] Last-frame extraction must be idempotent and verified**:
  assert the extracted PNG is non-empty and matches LTX output's last
  decoded frame within ε. Today it's a fire-and-forget shell call.
- **[P1] Pre-flight check** before each LTX run: confirm every
  conditioning file exists and is the expected size class. Fail fast
  with which-file-missing.
- **[P1] GPU OOM canary**: track peak VRAM in `metadata_json` so a
  reviewer can see when we're close to falling back; a regression in
  steps/resolution that breaches an OOM threshold should fail-fast
  before generation.

**UI surfacing**: Drawer now shows `metadata_json` and
`generation_params_json` per scene asset. Add an inline duration/motion
verdict pill next.

---

## Stage 8 — Audio generation (Chatterbox)

**Today's failure modes**

- Chatterbox produces WAV ~10–20% off target duration → desync at
  stitch.
- Reference voice WAV missing or wrong → silent fallback voice.
- Long narrations > `chatterbox_max_chunk_chars` are split badly,
  introducing audible seams.

**Fool-proofing actions**

- **[P0] Reference-voice precondition**: assert
  `Settings.chatterbox_reference_audio` exists and is a valid WAV before
  scheduling the job. Fail with a clear error otherwise.
- **[P0] Output validation**: ffprobe the WAV; assert duration within
  ±10% of `total_estimated_audio_duration`; loudness (LUFS) within a
  reasonable band; non-zero RMS; sample rate matches the configured
  value.
- **[P1] Auto-trim/pad** to exact target duration ± 0.05s before
  stitching, with crossfade at chunk boundaries.
- **[P2] Forced alignment** of generated audio to the
  `timing_map_json` to confirm scene N's narration starts within
  `audio_segment_start ± 0.5s`.

**UI surfacing**: Audio tab shows generated/failed badge already; show
estimated-vs-actual duration and per-chunk metadata next.

---

## Stage 9 — Stitching (FFmpeg)

**Today's failure modes**

- Audio drift over multi-minute renders due to fps rounding (12 fps ×
  73 frames ≠ exactly 6s).
- Final render misses scenes silently if any `scene_video` is `failed`.
- No re-encode pass to harmonize codec parameters → some players choke.

**Fool-proofing actions**

- **[P0] Pre-stitch gate**: refuse to stitch if any scene_video is not
  `complete`, or if `scene_count` < `required_scenes`. Surface the
  blocker.
- **[P0] Concat with explicit `concat demuxer + -fflags +genpts`** and
  `-async 1` to keep audio aligned. Validate the post-stitch duration
  against the sum of inputs.
- **[P1] Final-render validation**: ffprobe the output for resolution,
  fps, codec, bitrate, audio sample rate. Persist on
  `metadata_json`.
- **[P1] Frame-accurate scene boundaries**: write a sidecar JSON with
  `scene_index → start_frame, end_frame` so the UI can scrub by scene.

---

## Tooling that pays off everywhere

- **[P0] `pytest` smoke fixtures** per stage that take a frozen LLM
  reply (already saved on `result_json`) and run only the validators.
  Catches regression in validator logic itself.
- **[P0] One CLI** (`python -m app.tools.review_project <project_id>`)
  that prints a single-screen pass/fail across all stages — used in
  CI on the seed projects.
- **[P1] Pipeline timeline component** in the UI: a horizontal bar per
  stage with duration, status, and click-to-inspect of the new
  `payload_json`/`result_json`. Single place to triage a failed run.
- **[P1] Consolidated "Critique" tab** that fuses consistency-critic
  issues + still-critic verdicts + LTX validators into one prioritized
  list per scene.

---

## Suggested rollout order

1. Cross-cutting: `payload_json` writers + `result_json` standard shape +
   validation gate helper. Touches all stages but small per-stage diff.
2. Stage 7 (LTX) post-render validators — biggest visible quality win.
3. Stage 6c still-critic enforced — directly fixes the "off-center,
   legs not visible" failures already logged.
4. Stage 3 visual-director structural validators — prevents bad prompts
   from reaching LTX.
5. Stage 4/8 audio duration matching — fixes desync.
6. Stage 5 critic re-validation loop.
7. Stage 1/2 input validators (analyst dedup, planner membership).
8. UI: critique tab + timeline component.

Each step is independently shippable; the pipeline keeps working with the
old behavior in between.
