# Quality Debug Review

A forensic walk-through of every pipeline stage based on the most recent
real run (Save Soil preview, project `6477fa1f`, 2026-05-05). Each finding
cites a concrete file/path so the bug can be reproduced. Items are tagged:

- 🔴 **DEFECT** — produced wrong output in this run; fix before next quality pass.
- 🟡 **WEAKNESS** — works today but masks problems or is one prompt change away from breaking.
- 🟢 **OK** — verified correct in the run.

A "where to look in the UI" line is given for every finding so the user can
reproduce and watch the same bug from the new tab panels.

---

## Stage 1 — Story analysis

**Job log:** [Story tab → Stage 1 panel] · result_json: `{"summary": "..."}`

🔴 **`style_lock` is empty.** `project.style_lock = ""` after this run.
   - **Why:** the system prompt at [backend/app/prompts/story_analyst.txt](backend/app/prompts/story_analyst.txt) lists 5 things the analyst must identify (summary, beats, characters, locations, pacing). It does **not** mention style_lock. The user prompt at [backend/app/agents/story_analyst.py:62](backend/app/agents/story_analyst.py#L62) sneaks it into the JSON shape only, which gpt-5.4-nano treats as optional.
   - **Effect:** every downstream `video_prompt` falls back to a hard-coded string at [backend/app/agents/visual_director.py:81](backend/app/agents/visual_director.py#L81). Different scenes now get different visual styles because the project-wide anchor is missing.
   - **Fix:** add an explicit "6. STYLE LOCK" item to the system prompt with the full instruction; validate non-empty + ≤25 words after the call (retry up to 2× if violated).

🔴 **Pacing notes describe 30 s, project is 12 s.**
   `pacing_notes = "30 seconds total: quick opening (0–6s)..."` — the
   analyst got the original story (a 30-second ad) and wasn't told the
   actual target duration.
   - **Why:** [backend/app/agents/story_analyst.py:24](backend/app/agents/story_analyst.py#L24) does not include `total_target_duration_seconds` in the user prompt.
   - **Effect:** the analyst plans pacing for the original story length; the planner has to retrofit. Visible in the Story tab.
   - **Fix:** pass `target_duration_seconds` into the analyst's user prompt; require pacing_notes whose timestamps fall inside `[0, target]`.

🟡 **No deduplication of characters.** "Farmer (unnamed)" and "Child
   (unnamed)" come back as separate characters even when neither has a
   face — they're disposable hand-only roles. The action-stills agent
   then refuses to render them because they have no portrait that can
   carry an identity.
   - **Where to look:** Characters tab — see the empty/placeholder portraits.
   - **Fix:** detect `physical_description` containing "only … hands/fingers" or "no face" and tag the character as `body_part_only=True`; image_pregen renders them with a hand-only template instead of a portrait.

🟢 **Locations consolidated correctly** — single "Dying Field to Living
   Soil" location reused by both scenes.

---

## Stage 2 — Scene planning

**Job log:** [Scenes tab → Stage 2 panel]

🟢 **Scene count matches target** — 12 s / 6 s = 2 scenes, planner produced 2.

🟢 **Characters correctly linked.** `scene_characters` has Sadhguru +
   Farmer for Scene 1, Sadhguru + Child for Scene 2.

🟢 **Location membership respected** — both scenes point at the one
   consolidated location.

🟡 **`audio_alignment_notes` is empty per scene.** The planner runs
   *before* the audio director, so it can't anchor narration windows.
   The audio director later writes `target_audio_segment_start/end` back
   to scenes — but those windows don't get fed into the visual director.
   - **Effect:** visual prompts don't know what narration runs over them.
   - **Where to look:** Scene drawer → "Continuity" → Audio segment is shown, but isn't echoed in the per-second beat plan.
   - **Fix:** post-audio, regenerate visual prompts with the narration excerpt for each second injected into the visual director's user prompt (already supported by the `critique_feedback` channel).

---

## Stage 3 — Visual director

**Job log:** [Scenes tab → Stage 3 panel] · ran twice (initial + post-critique)

🔴 **`approved = False` on every ScenePrompt** even after the correction pass.
   - **Where to look:** Scene drawer — the new "pending review" pill is on every scene.
   - **Fix:** Stage 5's correction loop must re-run the critic and gate progression — see Stage 5.

🔴 **No `scene_breakdown` lines for the Farmer/Child.** Scene 1's
   breakdown reads `0–1s: Fingers crumble soil + static close-up. 1–2s:
   Soil falls through fingers + extreme close-up. 2–3s: Sadhguru walks
   slowly + wide shot.` The first two seconds are about the farmer's
   hands but the breakdown attributes them to no one — the action-stills
   agent then renders Sadhguru kneeling for second 0 (the wrong
   character).
   - **Fix:** the visual director must emit per-second character attribution, e.g. `0–1s [Farmer]: Fingers crumble soil`. Then action_stills can pick the right character per second.

🟡 **`video_prompt` says "Save Soil logo appears + static hold" while
   `negative_prompt` includes "logo, text, watermark".** Internally
   contradictory — LTX sees both at the same weight.
   - **Where to look:** Scene drawer for Scene 2 → both fields visible.
   - **Fix:** add a structural validator that intersects positive/negative term sets and rejects on overlap.

🟡 **Style lock not embedded** (because Stage 1 produced an empty one).
   Once Stage 1 is fixed, prepend the locked sentence to every
   `video_prompt` defensively at insert time.

🟡 **Continuity guardrails empty.** Both scenes have
   `continuity_guardrails` blank. The director didn't fill it because
   the user prompt template marks it optional.
   - **Fix:** make it required; emit explicit "match Scene N-1 lighting,
     same character poses persist into the cut" sentences.

---

## Stage 4 — Audio director

**Job log:** [Audio tab → Stage 4 panel]

🔴 **Narration asks for a logo at the end** ("Save Soil. It is in your
   hands. … logo / Conscious Planet / SaveSoil.org"). Visual prompts
   simultaneously refuse text/logos. Whichever side wins, the other
   spec is broken.
   - **Where to look:** Audio tab → Dialogue Plan card.
   - **Fix:** the audio director must read the negative_prompts of all
     visual prompts (or a shared "no on-screen text" project flag) and
     not request anything that requires on-screen text.

🟡 **Timing map has 4 segments for 2 scenes** (each 6 s scene split
   into 2 sub-windows). The DB-level `target_audio_segment_start/end`
   columns are per scene and lose this granularity.
   - **Where to look:** Audio tab → Timing Map section now shows the
     full 4-row table; Scenes tab shows only the first/last second per
     scene.
   - **Fix:** persist the full segments on `audio_segments` (new table)
     keyed by `(scene_id, segment_idx)` and reference from the visual
     director.

🟡 **Word-budget unenforced.** Narration is 28 words for a 12 s budget.
   At 120 wpm that's ~14 s — overshoot of ~17 %. Chatterbox compressed
   it back to 12.3 s but at the cost of pacing.
   - **Fix:** validate `len(narration.split()) ≈ duration * 2.0 ± 15 %`,
     re-prompt if outside.

🟢 **Voice prompt references Sadhguru's `voice_notes`** ("deep male,
   urgent then steady, ~120 wpm").

---

## Stage 5 — Consistency critic

**Job log:** [Scenes tab → Stage 5 panel + Critic Review Summary card]

🔴 **No re-validation after the correction pass.** [backend/app/orchestration/stages/consistency_review.py:114-120](backend/app/orchestration/stages/consistency_review.py#L114) calls `prompt_generation.run(critique_feedback=...)` then logs "correction pass complete" — it never re-runs `ConsistencyCriticAgent`. Both scenes ended up `approved=False` after the second pass; pipeline still marched on.
   - **Where to look:** Scenes tab → Critic Review Summary shows
     `needs revision` on every scene.

🔴 **Critic failure is downgraded to "non-fatal".** [consistency_review.py:124](backend/app/orchestration/stages/consistency_review.py#L124) has `logger.error("... non-fatal, pipeline continues")`. So even a thrown exception in the critic itself becomes silent — and the project marches into image_pregen with un-reviewed prompts.
   - **Fix:** make critic failure block the pipeline by default (env
     toggle to keep current behavior for dev).

🟡 **`payload_json` empty** for `consistency_review` — we only see the
   output, not what the critic was asked to evaluate.

---

## Stage 6 — Image pregeneration

**Job log:** [Images tab → Stage 6 panel + Still-Critic Verdicts card]

🔴 **Action stills only render `scene.characters[0]`.** [backend/app/agents/image_pregen/action_stills.py:42](backend/app/agents/image_pregen/action_stills.py#L42) `_resolve_primary_char` returns `scene_chars[0]` for every still in the scene. So Scene 1 (Sadhguru + Farmer) never gets a Farmer-hands still; Scene 2 (Sadhguru + Child) never gets a Child-hands still.
   - **Where to look:** Images tab → both scenes show 6 stills, all
     Sadhguru, never the Farmer/Child even though the visual_summary
     says "farmer's dusty fingers" and "child's hand presses sapling".
   - **Fix:** action_stills must consume per-second character attribution
     from the visual director (Stage 3 fix above) and pick the right
     character per still.

🔴 **Still-critic verdicts ignored.** Both scenes' first stills came
   back rejected ("face cropped, legs not visible for walking action",
   "off-center, face cropped"). The verdict is logged to
   `image_pregen.result_json` but the pipeline takes no action.
   - **Where to look:** Images tab → "Still-Critic Verdicts"
     observational card now visible.
   - **Fix:** make rejected stills auto-regenerate with the verdict's
     composition complaint injected as a corrective prompt fragment
     (e.g. add "full body, all limbs visible, centered framing" when
     `composition_issues` contains "legs not visible").

🟡 **Same-character identity drift across stills.** Per-still SD3.5
   prompts vary subtly: `"very light stubble"` → `"clean-shaven"` →
   `"light stubble"` for the same character within one scene. Each
   still LLM-prompt is generated independently from the Character
   record, so the LLM nudges details around.
   - **Fix:** generate the character description once per scene and pass
     it verbatim to every per-second still prompt — the LLM only writes
     the WHAT-action portion.

🟡 **No fixed seed per character.** Re-rolls produce different
   identities; reviewers can't tell whether a regen fixed the issue.
   - **Fix:** record `seed` in `assets.metadata_json` and use seed+1 on
     re-roll.

🟡 **Asset metadata empty for stills.** `scene_action_seq.metadata_json`
   is null; only `generation_params_json` has `{label}`. SD3.5 settings
   (steps, guidance, strength, seed) are not persisted per still.
   - **Where to look:** Assets tab → expand any `scene_action_seq`
     row → metadata is `—`.

🟢 **Background plate negative prompt blocks people** correctly — single
   plate produced, no figures.

---

## Stage 7 — Scene video (LTX)

**Job log:** [Scenes tab → Stage 7 panel]

🟢 **Both clips are 73 frames @ 12 fps = 6.083 s** (verified by ffprobe
   after the run). Asset metadata stored model + frames + fps + height
   + width.

🟡 **Conflicting prompt content survives.** Scene 2's video_prompt
   includes "Save Soil logo appears + static hold" — LTX has no
   reliable text rendering and the negative prompt forbids logos.
   The clip will most likely show garbled text in seconds 5–6.
   - **Fix:** the structural validator from Stage 3 (block prompts that
     reference text/logos) prevents this from reaching LTX at all.

🟡 **No post-render motion check.** A black or frozen clip would still
   be marked `complete`. We were lucky here.
   - **Fix:** ffprobe-based luma + inter-frame variance check; reject
     clips below threshold.

🟡 **Last-frame extraction silent on failure.** The conditioning chain
   from Scene 1 → Scene 2 used a last-frame, but no validation that
   the extracted PNG is non-empty.

---

## Stage 8 — Audio generation (Chatterbox)

**Job log:** [Audio tab → Stage 8 panel]

🟢 **Output is 12.28 s** for a 12.0 s target — within 3 %.

🟡 **No actual-vs-target check.** A 30 % overshoot would silently desync
   the final stitch.

🟡 **Reference voice not surfaced** in the UI. If the user uploaded a
   different `narrator_reference.wav` mid-project, there's no
   indication.

---

## Stage 9 — Stitching

**Job log:** [Render tab → Stage 9 panel]

🟢 **Final render produced** at 720 p, 12 fps, libx264, 2 clips, 12 s.

🟡 **No precondition gate.** If a scene_video is missing/failed, ffmpeg
   silently stitches the rest and the final render is a few seconds short.
   - **Fix:** assert `len(scene_videos == complete) == required_scenes`
     before invoking ffmpeg.

🟡 **No final-render validator.** The output's duration, fps, and
   resolution aren't checked against the expected values.

---

## Cross-cutting findings

🔴 **`payload_json` is null on every stage.** Reviewers can see the
   *output* of each stage but not what the agent was asked. Adding
   `payload_json` writes (system prompt path, user prompt rendered,
   model id, model temperature, every DB id read) is the highest-ROI
   debugging change in the entire codebase.

🟡 **Job duration is created_at == updated_at** for stages that finish
   under 1.5 s (rounding wipes the duration). Move to monotonic clock
   and store milliseconds.

🟡 **No global "validators" log.** Every stage that has a structural
   check (LTX duration, narration word budget, style_lock length,
   prompt overlap) should write its pass/fail to a single per-job
   `result_json.validation` field — so the new Jobs tab can show a
   single ✓/✗ at a glance.

🟢 **All raw prompts/results that already exist are now visible in
   the UI** — Story tab shows beats/pacing/style_lock; Scene drawer
   shows the full ScenePrompt, conditioning images, and asset
   metadata; Images tab shows per-still prompts + critic verdicts;
   Audio tab shows the timing map; Assets/Jobs tabs expose
   `metadata_json` / `payload_json` / `result_json`.

---

## Debugging cheat-sheet — "I see X, where do I look?"

| Symptom | Tab | What to inspect |
|---|---|---|
| Style drifts between scenes | Story | `style_lock` field — empty? |
| Wrong character in a still | Images | Per-still prompt sidecar — does it name the right character? |
| Critic flagged but pipeline ran | Scenes | Critic Review Summary card; `result_json` of last `consistency_review` job |
| Black or frozen LTX clip | Scenes drawer | `metadata_json` of scene_video asset (frames, fps); ffprobe the file path |
| Audio out of sync | Audio | Timing Map; `metadata_json` of `full_story_audio` asset (`actual_duration` vs target) |
| Final render shorter than expected | Render | Stage 9 panel + Assets tab — count `scene_video` rows with `status=complete` |
| Identity drift between stills of the same character | Images | Per-still prompts; compare consecutive sidecars in `scene_actions/.../*_prompt.txt` |
| Prompt-vs-negative contradiction | Scenes drawer | Full `video_prompt` and `negative_prompt` side by side |

---

## Top-5 fixes by ROI

1. **🔴 [P0] Make Stage 5 critic gate the pipeline** (re-validate after
   correction; fail loudly on `approved=False`). Touches one file.
   *Catches every bad-prompt-out-of-Stage-3 issue.*

2. **🔴 [P0] Per-second character attribution in visual director +
   action_stills.** The director already knows which character is
   active each second from the planner's `per_second_plan`; just emit
   `0–1s [Farmer]: …` and have action_stills consume it.
   *Eliminates the "wrong character in still" failure mode.*

3. **🔴 [P0] Style-lock validation in Stage 1.** Reject empty/over-long
   style_lock; retry. Then prepend it to every `video_prompt` at
   insert time.
   *Single visual anchor across the whole project.*

4. **🔴 [P0] Persist `payload_json` for every stage.** Tiny per-stage
   diff, but turns the Jobs tab into a real debugger.

5. **🔴 [P0] LTX post-render validators (duration, frames, motion).**
   Cheap, deterministic, prevents silent regressions on the most
   expensive stage.
