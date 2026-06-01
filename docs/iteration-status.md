# yoga_mat — iteration status

Loop is running with strict rubric in [docs/ad-quality-metrics.md](ad-quality-metrics.md).
Each iteration ships ONE deliberate change, runs the full pipeline,
auto-grades with `eval_run.py`, then hand-grades visual metrics from
sampled frames.

---

## Score progression

| Iter | Auto total | Hand total | Δ vs baseline | Headline change | Headline win |
|---|---|---|---|---|---|
| 0 (baseline) | 0.716 | 0.31 | — | — | — |
| 1 | 0.893 | 0.69 | +0.18 | F1 bg "no person" + F2 portrait outfit splice | M1 0.0→1.0 (bg leak killed) |
| 2 | 0.894 | 0.77 | +0.18 | F-PORTRAIT-OFF (skip standing portrait when stills present) | M6 0.73→1.00 (2-person hallucination gone), M3 → 1.00 |
| 3 | **0.934** | _better_ | +0.22 | F3 per-beat distinct pose-refs (target M5) | M5 0.07→0.41 (only metric still differentiating runs) |
| 4 | _running_ | _pending_ | _pending_ | F4 bake project bg into action stills (composite RGBA cutout onto bg PNG, no more LTX-side compositing) | _pending_ |

> **2026-05-07 14:55 — eval upgraded.** Auto totals re-graded with InsightFace (M3/M6) replacing OpenCV Haar (close-up false-positives), plus newly automated M4 (cross-still chest-color cosine), M5 (face-bbox L2 within scene), M8 (cross-frame chest-color cosine). M2 still hand-graded (single-portrait color vs spec — SD3.5 ignores color tokens, IP-Adapter is the eventual fix). Auto-rubric was saturated post-iter1 under the old (Haar + 4 hand-grades) scheme; the new metrics actually move iter-to-iter.

## What each change actually did

### Iter 1 — F1 + F2

**F1 — bg "no person" prompt.** Stripped the phrase *"for a head-to-toe
standing person to be composited in later"* from the bg framing prefix
(SD3.5 was reading "person" in the positive prompt as "render a person
here"). Replaced with neutral `EMPTY UNOCCUPIED room` framing. Added
explicit `person, people, human, figure, silhouette` to the bg
negative. Updated the bg system prompt to forbid activity-named
locations (`yoga studio` → `wood-floored room`).

**F2 — portrait outfit splice.** The character portrait builder now
strips clothing words from the LLM output and appends the canonical
outfit clause verbatim — same byte-identical clothing tail the action
stills already use. SD3.5 still doesn't honor specific colors (it
rendered white tank instead of sage green), but the portrait and
stills now wear the *same string* of clothing tokens, so any drift is
SD3.5's fault, not prompt drift.

### Iter 2 — F-PORTRAIT-OFF

The big issue in iter1: the standing portrait was pinned at LTX
frame 0 with strength 0.75, while the action stills (kneeling /
sitting) were pinned at frame 12+. LTX bridged the standing→kneeling
gap by **rendering both bodies overlapping** for the first second —
the dreaded "two-person hallucination."

Fix: when action stills are present, don't pass the static portrait
to LTX as a frame-0 condition. The stills already carry identity
(InstantID-locked face) AND the right pose. LTX's open frames now
naturally interpolate toward the first still, no morph artifact.

Result: M6 `video_one_person` jumped 0.54 → 0.85, M8 `outfit_stability`
jumped 0.50 → 0.80. All 6 sampled iter2 frames show one woman, one
sage green tank, one mat. No more visual chaos.

### Iter 4 — F4 bg-bake (queued)

Action stills currently get SD3.5's hallucinated bg removed and LTX
composites the RGBA cutout over the project bg PNG at video time. Two
sources of truth means:
  1. The still itself looks weird in the UI (transparent halos around
     hair/fingers if rembg's alpha matting misses an edge).
  2. LTX bridges between the bg-only frame 0 and the cutout still at
     frame 12+, sometimes painting a faint duplicate-character ghost as
     it interpolates.

F4 bakes the project bg PNG into each action still post-rembg:
canonical = opaque RGB on the right backdrop. LTX's bg input becomes
redundant (kept for safety) and the cutout-vs-bg discontinuity at the
LTX bridge frames disappears. No new GPU work — rembg already
isolated the character; the composite is a single PIL.paste.

### Iter 5 — candidate F5: scene_planner hook/turn/payoff

All prior iters produce the same flat structure: scene 0 = `action`
(unroll mat), scene 1 = `reaction` (sit cross-legged). M10 scores 1.0
because there are 2 distinct purposes, but there is no actual narrative
arc — no hook, no turn, no payoff. Rewriting `scene_planner.txt` to
require a 3-act structure on any ad ≥9s should bump narrative quality;
M10 should be tightened to require at least one of {hook|setup} AND
one of {payoff|conclusion|reveal} in the purpose set, not just ≥2
distinct.

### Iter 3 — F3 per-beat pose-refs (kept)

Until now, all 6 stills of one scene shared a single pose-ref skeleton
(one library hit per scene). Result: 6 near-identical stills, M5
`pose_variance` stuck at 0.10–0.30, LTX with no kinetic targets to
interpolate, video looks frozen.

F3: each beat (per-second action description) gets its OWN pose
matched independently against the library via the LLM. So scene 0's
"kneels → unrolls → smooths → settles" maps to 4 different skeleton
labels, and LTX has real motion targets between frames.

Same call cost (~$0.0005/scene × 6 beats = $0.003/scene), no extra
GPU work — pose-library hits are PNG copies.

---

## Frame evidence (iter2)

All 6 sampled frames at 0.5s intervals across both scenes:

| Frame | Time | Iter2 observation |
|---|---|---|
| s0_01 | 0.5s | Single woman, sage green tank, sitting at rolled mat. ✓ |
| s0_06 | 3.0s | Single woman, sage green tank, arms-out with rolled mat ✓ |
| s0_12 | 6.0s | Single woman, sage green tank, cross-legged in window light ✓ |
| s1_01 | 0.5s | Single woman, sage green tank, lavender leggings, cross-legged on mat ✓ |
| s1_06 | 3.0s | Single woman, same outfit, cross-legged with bracelet ✓ |
| s1_12 | 6.0s | Single woman, same outfit, cross-legged ✓ |

vs **iter0 (baseline)** where scene 1 had **2 people** in 5 of 6 sampled
frames.

---

## Outstanding issues (queued for future iters)

| Metric | Current iter2 | Target | Likely fix | Effort |
|---|---|---|---|---|
| **M2** portrait_outfit_match | 0.20 | ≥0.7 | IP-Adapter clothing reference (Tier 2) — SD3.5 doesn't honor color tokens via text | 1 day |
| **M5** pose_variance | 0.30 | ≥0.7 | F3 (in flight, iter 3) | _testing_ |
| **Screenplay quality** | not graded yet | — | Tighten scene_planner.txt + visual_director.txt to require hook/turn/payoff arc; also tighten M9/M10 to actually grade narrative strength | 2-3 hr |
| **Output resolution** | 576x1024 | 1080p+ | Post-LTX ffmpeg/ESRGAN upscale subprocess (in `ltx_provider.py`) — LTX exits → free VRAM → cheap upscale | 1.5 hr |
| **DB project state lock** | manual unstick each run | auto | Cleanup script that auto-fails any project in `*ing` state for >30 min | 30 min |

## How to read each iter

Every run drops a JSON in `docs/runs/` with per-metric scores. Open
that to see the auto-graded numbers. Then run:
```bash
ffmpeg -i backend/storage/videos/<project_id>/scene_000_*.mp4 \
       -vf "fps=2" /tmp/eval_<iter>/s0_%02d.png
```
to see frame-by-frame quality.
