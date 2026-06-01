# Preserving faces in motion-heavy Wan2.2 scenes

## What I actually observed

I sampled start/mid/end frames from 8 motion-heavy scenes already in the
project (`ad_02_running_woman`, `ad_09_running_shoes`, `hist_02_buddha_sujata`,
`hist_03_chanakya_chandragupta`). Three distinct failure modes:

**1. Identity drift mid-clip — confirmed on `ad_02` scene 2 (the runner's
"breath visible" beat).** At t=0.5s the woman has a clearly defined athletic
face. By t=4.5s the same character has morphed into a different person —
elongated jaw, more painted/stylized features, even hairstyle subtly different.
This is a single 5-second clip drifting away from itself.

**2. Hand/finger artefacts during fast motion.** Same `ad_02` scene 2 end
frame: the runner's arm/hand at full extension shows fused fingers and a
malformed wrist. This shows up consistently in scenes where the model
extrapolates limbs at the edge of frame.

**3. Walking scenes hold up.** `hist_02_buddha_sujata` (Sujata walking with a
bowl) and `hist_03_chanakya_chandragupta` (sword sparring in forest light)
both keep face identity through start/mid/end. Slow locomotion = less
per-frame jump for the model to integrate over.

What did *not* show face drift:
- Pure-body shots where face wasn't in frame (ad_09 foot-strike, ridge-crest)
- Walking-pace shots regardless of camera distance
- The far-wide `ad_02` side-profile (faces too small to read drift)

So the actual problem is narrower than "any motion": **mid-clip identity
drift on character running, especially when the face is visible at medium
distance.** That's where to spend optimisation effort.

## Why the existing pipeline doesn't fix it

- CodeFormer postproc gates on `shot_type == "wide"` and runs per-frame
  with no temporal coherence. So:
  - Closeups skip it entirely (correct: GFPGAN over-processes large faces).
  - Wides that DO run it get inconsistent per-frame faces — fine for stills,
    but doesn't fix the model-level identity drift, just polishes each
    drifted frame individually.
- I2V chain (now correctly wired post-fix) carries identity *across*
  scenes but doesn't constrain identity *within* a single 5s clip.
- No identity reference is supplied to Wan2.2 — it has nothing to anchor on.

This doc lays out the options I see, ranked by **expected quality lift × cost
to ship**, so you can pick what to try next.

---

## Status (2026-05-21)

**Shipped:**
- ✅ Option 1: motion-aware step bump (40 → 55) on `action_running`,
  `walking_locomotion`, `dancing_high_motion`, `dramatic_cinematic_war`.
  Static/closeup scenes unchanged.
- ✅ Option 2: face/hand distortion negative-prompt baseline injected for all
  Wan22 scenes (motion + static). Caller-supplied negatives still take
  precedence and are preserved verbatim.
- ✅ Option 3 (partial): motion-aware CFG bump (5.0 → 6.0) on the same motion
  scene types. Static scenes keep 5.0 baseline. No full grid sweep yet.
- ✅ **Smart character-aware I2V seed picker**: `_resolve_last_frame` now
  walks back through prior scenes and seeds from the most recent one sharing
  ≥1 character with the current scene. Skips environmental shots and
  different-character intermediates. Falls back to cold T2V if no prior
  scene shares — better than seeding with a wrong face. Implementation:
  pure-function `_pick_seed_scene_index()` in [scene_video.py](backend/app/orchestration/stages/scene_video.py),
  12 tests in [test_scene_video_smart_seed.py](backend/tests/test_scene_video_smart_seed.py).

Implementation: pure-function `_tune_for_motion()` in
[wan22_provider.py](backend/app/providers/video/wan22_provider.py), 22 tests in
[test_wan22_motion_tuning.py](backend/tests/test_wan22_motion_tuning.py).

**Not shipped (in priority order):**
- ⏳ Option 5 (face-swap, biggest expected lift) — needs the InsightFace
  `buffalo_l` + `inswapper_128.onnx` models + a reference-portrait pipeline
  for text-only profiles. Half-day build.
- Options 4 / 6 / 7 / 8 — parked, see notes below.

---

## Option 1 — More inference steps (cheapest, smallest lift)

What it is: bump `num_inference_steps` from `40` → `50–60`.

| | |
|---|---|
| Quality lift | Small. Sharpens details, slightly stabilises faces. |
| Cost | +25–50% wall-clock per scene (~1 min more on wide+postproc). |
| Effort | One config change in `wan22_text_only` profile's `provider_settings`. |
| Risk | None. Pure inference quality knob. |

**Recommend:** try 50 steps first as a baseline. Past 50 returns diminish hard
on Wan22; the UniPC scheduler convergence is mostly done by step 40.

---

## Option 2 — Negative-prompt face guardrails (free, small lift)

What it is: extend the negative prompt with explicit anti-distortion terms.
Currently empty/short.

```
negative_prompt = (
    "warped face, distorted features, melting face, asymmetric eyes, "
    "drifting identity, face morphing, plastic skin, smeared features, "
    "blurry face, double face, extra fingers, deformed hands"
)
```

| | |
|---|---|
| Quality lift | Small but free. Best for the "melting face mid-stride" failure mode. |
| Cost | Zero. Already a CLI flag. |
| Effort | Edit `Wan22VideoProvider.generate_video` to pass a stronger default
when caller doesn't override. |
| Risk | Slightly over-cautious motion if negatives are too aggressive. |

**Recommend:** ship together with Option 1. Both touch the same provider and
test together.

---

## Option 3 — Lower CFG / higher CFG sweep (free, motion-dependent)

What it is: tune `guidance_scale`. Currently `5.0`.

- **CFG 4.0–4.5:** softer, more natural motion; risk: identity drift.
- **CFG 6.0–7.0:** more rigid adherence to prompt; risk: stiff motion, less natural blink/breath.

Faces in motion typically hold better at **slightly higher CFG (5.5–6.5)** but
motion can become jerky. Worth a small grid sweep on a 3-prompt eval set.

| | |
|---|---|
| Quality lift | Variable. Some prompts win at 6.0, others at 4.5. |
| Cost | Eval-runtime only. |
| Effort | A/B harness on 3 prompts × 3 CFG values = 9 clips, ~30 min total. |
| Risk | Per-prompt optimum varies. Single global value is a compromise. |

---

## Option 4 — Identity-preserving LoRA (medium lift, moderate setup)

Single-subject LoRA trained on 15–40 photos of a specific face, applied at
`weight 0.6–0.8` alongside the scene LoRA.

Options that work with Wan2.2 architecture:
- **Standard Wan2.2 single-subject LoRA**: train via `diffusers` / `kohya-ss`
  on 20+ images of the subject. ~2hrs train time on RTX 5070 Ti.
- **PuLID-Wan** (if/when released for Wan2.2): cross-attention identity adapter.
  Currently PuLID exists for Flux + SDXL but not Wan2.2 yet (as of Jan 2026).
- **InfiniteYou / InstantID-style**: works on image, not natively on video models.

| | |
|---|---|
| Quality lift | **Large** for identity preservation. Faces stay consistent across motion. |
| Cost | Per-character training cost: ~2hrs GPU + curating 20 photos. |
| Effort | Add LoRA training pipeline + per-project subject LoRA selection. |
| Risk | Style bleed: the LoRA can also lock costume/pose, reducing variety. Mitigated by lower weight (0.6). |

**Recommend** for **brand mascot / recurring character ads** where you'll
reuse the same face across many projects. Overkill for one-off historical
mini-series with new characters each time.

---

## Option 5 — Frame-by-frame face-swap (highest practical lift, production-grade)

What it is: after Wan22 generates the video, run **InsightFace + InSwapper**
(or ReActor) against a reference portrait of the intended character. This is
the technique most commercial AI video tools use to fix identity drift.

Pipeline:
1. Wan22 generates raw clip (faces drift across motion — accepted).
2. Pick a single reference portrait of the character (or pre-generated SD3.5 portrait).
3. Run `insightface buffalo_l` face detection per frame.
4. Swap each detected face with the reference using `inswapper_128.onnx`.
5. Run CodeFormer at fidelity 0.7 on the swap output to clean blending artifacts.

| | |
|---|---|
| Quality lift | **Very large.** Identity locks across the full clip regardless of motion. |
| Cost | +30s–60s post-process per scene on RTX 5070 Ti. |
| Effort | New `wan22_face_swap.py` subprocess script, wired similarly to current face_restore. ~half day. |
| Risk | If the source face is too small (<60 px crop), swap fails — falls back to raw frame. Need same closeup-gate logic as current restore. |
| Risk | Reference portrait must match the prompt's ethnicity/age/gender — wrong reference produces obviously-swapped uncanny faces. |

**Recommend:** highest ROI of the options if movement-heavy clips are the
common case. This is the option I'd actually ship first.

---

## Option 6 — ControlNet face-landmark conditioning

If a Wan2.2-compatible **Face ControlNet** ships, condition the model on
MediaPipe face landmarks extracted from the reference portrait, propagated
across the desired motion path. This forces the model to keep the same face
structure across frames.

As of Jan 2026: ControlNet adapters for Wan2.2 are not yet broadly released
in the Diffusers ecosystem. Pose ControlNet (OpenPose) exists for some Wan
variants but Face ControlNet specifically does not.

| | |
|---|---|
| Quality lift | Would be best-in-class if available. |
| Cost | N/A today. |
| Effort | Wait for upstream. |

**Recommend:** track but don't build against. Re-evaluate Q2 2026.

---

## Option 7 — Shorter scene chunks with stronger I2V chain

Currently each scene is 121f @ 24fps ≈ 5s. Drop to 73f @ 24fps ≈ 3s and chain
twice as many I2V hops. Each 3s clip has half the cumulative drift; the I2V
seed from the previous frame keeps identity tighter.

| | |
|---|---|
| Quality lift | Moderate — reduces per-clip drift, but doubles the number of stitch joins (slightly more visible). |
| Cost | Same total render time (more clips × shorter each). |
| Effort | Profile setting change + planner update (twice the scenes per duration target). |
| Risk | More visible cuts unless xfade transitions are tuned up. |

**Recommend:** secondary fix to stack on top of Option 5. Worth it if face-swap
still leaves residual drift in 5s clips.

---

## Option 8 — Optical-flow-guided face restoration (research-tier)

Replace current per-frame CodeFormer with a video-aware version:
- **CodeFormer + RAFT optical flow warping** (manually link adjacent face restores).
- **BFRffusion** (Blind Face Restoration via diffusion, multi-frame aware).
- **VFR-Net** / **KEEP** (Keep-yourself-Constant face restore for video).

| | |
|---|---|
| Quality lift | Moderate — fixes the *temporal flicker* of per-frame restoration but doesn't fix the underlying model drift. |
| Cost | +60–120s per scene. |
| Effort | New restoration pipeline; KEEP has a published model + repo. |
| Risk | Some are research code with rough integration. |

**Recommend:** lower priority than face-swap. Tackle if Option 5 lands and we
still see flicker.

---

## My recommended sequence

1. **Ship in one PR (1 day):** Option 1 (50 steps) + Option 2 (negative prompts) + Option 3 (CFG 6.0). Free wins, no new code paths.
2. **Build next (half-day):** Option 5 — InsightFace + InSwapper face-swap post-process, gated on `shot_type == "wide" or character_face_visible`. Treat current CodeFormer as the cleanup pass *after* the swap.
3. **Decide based on results:** if motion-heavy clips still drift, layer Option 7 (3s chunks) on top.
4. **Park:** Options 4 (LoRA training), 6 (ControlNet), 8 (video face restore) — revisit when 1+2+5+7 plateau.

---

## Comparison table

| Option | Quality lift | Cost / scene | Effort to ship | Reusable across projects |
|---|---|---|---|---|
| 1. More steps | + | +25–50% | 1 line | ✓ |
| 2. Negative prompts | + | 0 | 1 line | ✓ |
| 3. CFG tuning | +/- | 0 | sweep eval | ✓ |
| 4. Identity LoRA | +++ | +0 (inference) | training pipeline | per-character |
| **5. Face-swap (InsightFace/InSwapper)** | **++++** | **+30–60s** | **half-day** | **✓** |
| 6. Face ControlNet | +++++ | n/a | wait upstream | ✓ |
| 7. Shorter chunks | ++ | same total | profile+planner | ✓ |
| 8. Video face restore | ++ | +60–120s | new pipeline | ✓ |

---

## Notes on the current pipeline

- `wan22_face_restore_codeformer.py` uses `RetinaFace + CodeFormer + RealESRGAN`. After the recent fix, output is scaled back to 832×480 so stitching works regardless of postproc.
- Postproc is gated on `shot_type == "wide"` — closeups skip it (per the
  saved feedback: face-restore over-processes closeups). This gate would
  apply identically to a face-swap step.
- I2V chain is now live (`pin_last_frame_chain=True`, environmental-drop
  bug fixed). That alone has already reduced cross-scene drift; in-scene
  motion drift is what Options 4/5/6 address.
