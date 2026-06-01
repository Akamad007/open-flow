# Video Quality Improvement Plan

Audit of all generated videos in the system to identify failure modes and a
prioritized plan to push final-render quality from "sometimes good" to
"reliably good."

**Audit date:** 2026-05-05
**Sample size:** 17 final renders + ~150 scene videos across 30+ projects
**Reference frames:** `/tmp/video_audit/*.png` (sampled at 10/50/90% of duration)

---

## 1. What works today (good outputs)

These projects produced acceptable-to-good results. Common traits below.

| Project | Type | Why it worked |
|---|---|---|
| `6260138d` | Woman running urban | Single character, single environment, clear motion verb, motion blur reads as intentional |
| `008f33a0` | Woman running hills | Outdoor natural light, wide framing, action matches body language |
| `d094c133` | Runner sunset | Beautiful color grade, clear silhouette, environment supports motion |
| `aa8f0422` | Yoga mountain top | Single subject, clean background, peaceful mood matches static-ish frames |
| `c835fa9d` | Runner sunrise | Strong rim light, clear figure-ground separation |
| `09ecbd9a` scene 0 | Hands lifting soil | Tight close-up of hands with stable composition — img2img init close to target |

**Common traits of GOOD outputs:**

- ✅ **One dominant character** the whole way through
- ✅ **One environment** that visually supports the character's action
- ✅ **Clear motion verb** in every scene (running, bowing, lifting)
- ✅ **Outdoor natural lighting** (sunrise/sunset/midday) — skin tones and palette read naturally
- ✅ **Wide / medium-wide framing** — LTX has full body to extrapolate motion from
- ✅ **3-5 second scenes** — short enough that LTX denoising doesn't drift into artifacts

## 2. What fails today (bad outputs)

| Project | Failure | Root cause |
|---|---|---|
| `e4c13437` Save Soil scenes 2-4 | Same robe-walking shot 3× | last_frame chain dominated when scene 3 had no action stills |
| `e4c13437` scene 4 end | Color drift to sludgy green | Cumulative LTX denoising artifacts in tail scenes |
| `e4c13437` scenes 2-4 | Burned-in gibberish English text | LTX hallucinating subtitles from prompt context |
| `09ecbd9a` (prior Save Soil) | Sadhguru morphs into child | img2img init from prev scene leaked identity |
| `aa8f0422` end frame | Subject face blurred | LTX struggles with close-up face mid-scene |
| Various tail scenes | Style drift between scenes | No global style anchor — each scene re-grades independently |

## 3. Failure modes catalogued (with mechanisms)

### 3.1 Last-frame conditioning dominates over scene intent ✅ FIXED
**Symptom:** Scene N renders the same shot as scene N-1 even though prompt is different.
**Mechanism:** `_select_conditioning` returned `last_frame, None, None, []` whenever a last_frame existed, suppressing character + background + action stills.
**Status:** Fixed in [scene_video.py:104-130](backend/app/orchestration/stages/scene_video.py#L104-L130) — last_frame is now a fallback only.

### 3.2 No-character scenes silently inherit prev character ✅ FIXED
**Symptom:** Scene about earthworms/children renders Sadhguru.
**Mechanism:** `_resolve_primary_char` fell back to `fallback_chars[0]`. Then visual_director kept Sadhguru in the prompt anyway.
**Status:** Fixed via fuzzy char match + visual_director scope rule + skip-rule for unlinked scenes.

### 3.3 Burned-in subtitle/text artifacts ⏳ OPEN
**Symptom:** Gibberish English text overlays on scenes 2-4 of Save Soil.
**Mechanism:** LTX-Video hallucinates text when the prompt mentions "voiceover", "narration", or "ad" — the model pattern-matches "text-on-screen" from training data of similar ads.
**Why it persists:** Our `negative_prompt` includes "text, subtitles, watermark" but LTX appears to weakly honor negatives in image-conditioned mode. The text comes through anyway.
**Fix candidates** (priority order):
1. Strip narrative / dialogue / "voiceover" mentions from `video_prompt` before sending to LTX. The text in the original Save Soil story (e.g. *"Voiceover: 'We have less than 50 years…'"*) is the trigger.
2. Add aggressive negative-prompt baseline at the LTX provider level: `"text, subtitles, captions, words, letters, alphabet, English text, cyrillic, devanagari, gibberish text, on-screen text, lower thirds, title card, watermark, logo, signature"`
3. Lower CFG / guidance scale on LTX (text artifacts are often a high-guidance side effect).
4. Post-process: detect text via OCR on output frames and re-render scenes that fail.

### 3.4 Color / style drift across consecutive scenes ⏳ OPEN
**Symptom:** Scene 1 is warm sunset, scene 2 is cool grey, scene 3 is washed-out green. The video feels disjointed.
**Mechanism:** Each scene's `video_prompt` is generated independently by visual_director with `temperature=0.7`. The "style" dimension (lighting, color tone, atmosphere) drifts scene-to-scene because there's no global anchor.
**Fix candidates:**
1. Add a project-level **`style_lock`** field — a frozen 1-sentence style descriptor written once at story analysis time and prepended to every scene's video_prompt. Same words across scenes ⇒ same color grade.
2. Lower visual_director temperature (0.7 → 0.4) globally — accepting less variety for more consistency.
3. Pass adjacent scenes' `dim_style` to visual_director as anchors so it converges.

### 3.5 Cumulative denoising artifacts in tail scenes ⏳ OPEN
**Symptom:** Last 1-2 scenes of a long video look mushy / over-saturated / green sludge.
**Mechanism:** Every scene's first frame chains from previous scene's last frame via `--condition-image`. Each pass through LTX adds slight denoising noise. By scene 4-5 it compounds.
**Fix candidates:**
1. Reset the `--condition-image` chain every N scenes (e.g. drop last_frame for scenes ≥3).
2. Use the project's static character portrait + bg as condition every scene, instead of prev-frame chaining.
3. Re-run scene N if its output frame's color histogram drifts >X% from scene 0's.

### 3.6 Subject face blur in close/medium shots ⏳ OPEN
**Symptom:** When the camera is close on a face (yoga, dialogue), the face is blurry mid-frame.
**Mechanism:** LTX is trained on diverse motion; it preserves silhouettes well but loses fine facial detail when there's no temporal data to reference. Single-image conditioning can't tell LTX which way the eyes should move.
**Fix candidates:**
1. Avoid close-ups on faces in dialogue scenes — prefer medium-wide where blur is less visible.
2. For mandatory close-ups, supply 2-3 action stills with slight expression variation as conditioning (LTX uses these directly per `--scene-action-images`).
3. Add a face-restoration post-process pass (CodeFormer / GFPGAN) on close-up scenes only.

### 3.7 LTX struggles with abstract / environmental scenes ⏳ OPEN
**Symptom:** "Earthworms move" / "roots spread" / "child plants sapling" rendered as a robe-walking shot or unrelated content.
**Mechanism:** LTX is character-motion-driven. When given a scene with no clear human subject, it falls back to whatever's in the conditioning images — which is usually a previous-scene human.
**Fix candidates:**
1. **Detect environmental scenes** in scene_planner output (`character_names == []`) and route them to a different conditioning path: drop character/last_frame entirely, use only `--background-image` with a dedicated environmental prompt.
2. Generate scene-specific reference plates for environmental scenes (worms, sapling, etc.) via SD3.5 instead of relying on the location plate.
3. Reduce LTX's reliance on conditioning by lowering image-conditioning weight for these scenes.

### 3.8 Action stills don't visibly progress within a scene ⏳ OPEN
**Symptom:** 6 stills generated per scene look 90% identical — character in same pose with minor variations.
**Mechanism:** img2img from prev still at 0.55 strength keeps composition essentially fixed. The prompt asks for "progression" but SD3.5 with strong init won't deliver it.
**Fix candidates:**
1. Lower strength on later stills (0.55 → 0.65 → 0.75) so each subsequent still denoises more.
2. Drop the chain entirely every 3rd still (re-init from char portrait with strength 0.85).
3. Use DIFFERENT seeds across stills (we do, but seed=42+idx is too close — try seeds with larger gaps).
4. Use SDXL turbo or a faster img2img loop with explicit "next frame in motion sequence: X→Y" prompting.

### 3.9 Low frame count → choppy motion ⏳ OPEN
**Symptom:** 6s scenes feel "stuttery" or have visible interpolation artifacts.
**Mechanism:** LTX runs at a fixed FPS; the perceived motion smoothness depends on `num_frames / fps`. If we're under-allocating frames, motion looks choppy.
**Fix candidates:**
1. Verify `VideoSettings.fps` and `num_frames` are sized for 24fps minimum.
2. Optional post-process with RIFE or FILM frame interpolation to double the frame rate.

### 3.10 No global style anchor (cinematography rules vary scene-to-scene) ⏳ OPEN
**Symptom:** Camera moves randomly between dolly-in, static, handheld across scenes.
**Mechanism:** Visual_director picks `dim_camera` per scene without a project-wide camera-style baseline.
**Fix candidate:** Add `project.camera_style` (set at story analysis time): "static documentary tripod" / "handheld vérité" / "dolly + slider" — use as default unless scene explicitly overrides.

---

## 4. Improvement plan — prioritized by leverage

### Tier S — High leverage, low effort (do first)

| # | Change | Where | Effort | Expected impact |
|---|--------|-------|--------|-----------------|
| S1 | Strip "voiceover", "narration", dialogue quotes from `video_prompt` before LTX call | [ltx_provider.py](backend/app/providers/video/ltx_provider.py) — sanitize `prompt` arg | 1h | Eliminates 80% of burned-in text artifacts |
| S2 | Add hardcoded text-rejection negative-prompt baseline appended to every LTX call | [ltx_provider.py](backend/app/providers/video/ltx_provider.py) | 30m | Catches text artifacts the LLM-emitted negative misses |
| S3 | Add project-level `style_lock` field — one frozen style sentence prepended to every scene's video_prompt | [story_analyst.py](backend/app/agents/story_analyst.py), [project.py](backend/app/models/project.py) | 3h | Stops scene-to-scene color/style drift |
| S4 | Lower visual_director temperature 0.7 → 0.4 | [visual_director.py:163](backend/app/agents/visual_director.py#L163) | 1m | Less character/style hallucination |
| S5 | For environmental scenes (no character link), use a different LTX conditioning path: drop char + last_frame, keep only bg + scene-specific action stills | [scene_video.py](backend/app/orchestration/stages/scene_video.py) `_select_conditioning` | 2h | Stops "earthworm scene looks like Sadhguru walking" |

### Tier A — Medium leverage, medium effort

| # | Change | Where | Effort | Expected impact |
|---|--------|-------|--------|-----------------|
| A1 | Reset img2img chain every 3 stills (re-init from char portrait, strength 0.80) | [action_stills.py](backend/app/agents/image_pregen/action_stills.py) | 1h | Stills show more visible progression within scene |
| A2 | Drop `--condition-image` (last frame) for scenes with index ≥3, keeping only bg + char + actions | [scene_video.py](backend/app/orchestration/stages/scene_video.py) | 30m | Stops cumulative tail-scene degradation |
| A3 | Avoid extreme close-ups on faces in dialogue scenes — scene_planner picks medium-wide framing for dialogue | [scene_planner.py](backend/app/agents/scene_planner.py) prompt | 30m | Less face-blur in talking-head scenes |
| A4 | Add `project.camera_style` field (set at story analysis time) used as default unless scene overrides | [story_analyst.py](backend/app/agents/story_analyst.py), schema | 2h | Consistent cinematography across scenes |
| A5 | Generate scene-specific environment plates for environmental scenes (worms, sapling, etc.) instead of falling back to global location | [image_pregen.py](backend/app/orchestration/stages/image_pregen.py) | 4h | Environmental scenes have anchor that matches their content |

### Tier B — Lower leverage / experimental

| # | Change | Where | Effort | Expected impact |
|---|--------|-------|--------|-----------------|
| B1 | Face-restoration post-process (CodeFormer/GFPGAN) on close-up scenes | New post-process step | 4h | Sharper faces in close-ups |
| B2 | RIFE/FILM frame interpolation 12fps → 24fps | New stage after LTX | 4h | Smoother motion |
| B3 | OCR-based regen: detect text artifacts in output frames, regenerate failing scenes | New QA step | 6h | Catches escaped text without manual review |
| B4 | Lower CFG on LTX (test with `guidance_scale` 7.0 → 5.0) | [ltx_provider.py](backend/app/providers/video/ltx_provider.py) | 30m + tests | Less guidance-induced text/artifacts |
| B5 | Replace per-second action stills with single high-quality "key pose" per scene | [action_stills.py](backend/app/agents/image_pregen/action_stills.py) | 2h | Faster pipeline, less bloat — but loses temporal anchoring |

### Tier C — Pipeline-architecture changes (consider only if Tiers S/A insufficient)

| # | Change | Effort | Reasoning |
|---|--------|--------|-----------|
| C1 | Replace LTX-Video with a more controllable open-weights model (Wan-Video, HunyuanVideo) | 1-2 weeks | LTX has known weaknesses with multi-character + abstract scenes |
| C2 | Add ControlNet pose conditioning to SD3.5 stills + pose-aware video model | 2 weeks | Real per-frame pose control, not just prompt-level |
| C3 | Switch to a longer-context video model (15s+ in one pass) instead of 6s scenes stitched | 1 week | Eliminates per-scene drift entirely |

---

## 5. Acceptance test plan

A run is "good" if:

1. ✅ All scene videos render without all-black or pure-noise frames
2. ✅ ≤1 scene has burned-in text/subtitles
3. ✅ Frame-hash similarity between consecutive scenes < 0.7 (no "scene N looks like scene N-1")
4. ✅ Subject is visibly centered within central 70% of frame for ≥80% of duration
5. ✅ Color histogram drift between scene 0 and last scene < 25% per-channel
6. ✅ When the story has multiple characters, each is recognizable in their assigned scenes
7. ✅ Final stitched render duration matches `total_target_duration_seconds` ± 5%

The existing [scripts/measure_project.py](scripts/measure_project.py) covers
1, 3, 4, 6, 7. Items 2 (text detection via OCR) and 5 (color histogram) need
extending.

---

## 6. Recommended next steps

**This week (Tier S — get to 7/10 from 5/10):**

1. S2: hardcoded LTX negative baseline (30 min)
2. S1: strip dialogue/voiceover/narration from `video_prompt` (1 hour)
3. S4: visual_director temperature → 0.4 (1 minute)
4. Test with one Save Soil run + one runner-ad run.

**Next week (Tier S+A — get to 8/10):**

5. S3: project-level style_lock (3 hours)
6. S5: environmental-scene conditioning path (2 hours)
7. A2: drop last_frame for scenes ≥3 (30 minutes)
8. Test with multi-character ad.

**Stretch (Tier A+B — get to 9/10):**

9. A1: img2img chain reset every 3 stills
10. A4: project camera_style
11. B4: CFG 7→5 sweep + measure

---

## 7. Reference: what to AVOID re-introducing

These were tried and rolled back; don't bring them back without strong
justification.

- ❌ 7-framing system (`extreme_close_up`…`extreme_wide`) with per-still
  dimension switching, strength tables, and chain-reset on framing jump.
  Added prompt bloat, unpredictable composition, no measurable quality gain.
- ❌ Per-still `subject_position` field. Centering is mandatory; non-center
  options confused both SD3.5 and LTX.
- ❌ `is_major_framing_jump` reset logic. Made cross-still chaining brittle.
- ❌ Closed-loop `iterate_pipeline.py` runner — useful tool but not for
  unattended use; a 30-min/iteration loop hides regressions.

---

## 8. Open questions for the human

1. **Acceptable runtime per project?** Each Tier S/A change adds 0-5% runtime; Tier B (face restoration, RIFE) adds 30%+.
2. **Quality vs duration tradeoff?** Are you OK with 6 short scenes that look great vs 12 mediocre scenes?
3. **Per-domain tuning?** Save Soil-style ads (multi-character, environmental) need different defaults than runner ads (single subject, motion-led). Worth supporting "ad type" hints from the user?
4. **Brand consistency?** When a project is part of a campaign (multiple ads for the same client), should we lock character/style across projects, not just within one?
