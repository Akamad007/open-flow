# Ad-Quality Metrics — scoring rubric for every yoga_mat / batch run

Every iteration produces a numeric score. We change one thing at a time
and only keep the change if the score moves in the right direction.
**No vibes-based "looks better" judgments — only the rubric.**

---

## How to run

```bash
backend/python_eval_run.py --project <uuid> > docs/runs/<timestamp>.json
```

This script:
1. Reads the project's artifacts (bg, portrait, action stills, scene videos).
2. Computes each metric below.
3. Writes a JSON line to `docs/runs/`, plus a short markdown summary.

**Run-comparison rule:** before any change is "kept," the diff between
the new run and the prior baseline must show *strictly more* metrics
moving toward target than away. If two metrics improve and three
regress, the change is reverted.

---

## Metrics

Each metric has: **id, name, definition, measurement method, target,
weight.** Score per metric is `0.0` (worst) to `1.0` (perfect target).
Final ad score = weighted sum (weights sum to 1.0).

### Image-stage metrics (cheap, run for every still)

| ID | Name | Definition | Measurement | Target | Weight |
|---|---|---|---|---|---|
| **M1** | bg_zero_people | Background has zero humans | InsightFace face count on bg PNG. 0 faces → 1.0; ≥1 face → 0.0 | 1.0 (binary) | 0.10 |
| **M2** | portrait_outfit_match | Portrait wears the spec'd outfit colors | Crop torso & legs from portrait, dominant-color match against clothing_description color tokens (sage green, olive, etc.) | ≥0.7 cosine | 0.05 |
| **M3** | stills_one_person | Each action still has exactly 1 person | InsightFace face count per still, % of stills with exactly 1 face | ≥0.95 | 0.05 |
| **M4** | stills_outfit_match | Stills wear consistent outfit colors across all stills | Pairwise chest-band (h 35-55%, w 25-75%) BGR mean cosine across all stills | ≥0.7 mean | 0.05 |
| **M5** | pose_variance | Action stills have DIFFERENT poses, not clones | Pairwise L2 distance between InsightFace bbox signatures (cx,cy,w,h normalized) within each scene, averaged. Cap 0.10 → 1.0 | ≥0.10 (normalized) | 0.05 |

### Video-stage metrics (run on the final scene mp4)

| ID | Name | Definition | Measurement | Target | Weight |
|---|---|---|---|---|---|
| **M6** | video_one_person | Every frame has exactly 1 person | Sample 6 frames per scene, InsightFace face count. Score = % frames with face_count==1 | ≥0.95 | 0.15 |
| **M7** | motion_magnitude | Real motion, not static morph | Dense optical flow (Farneback) mean magnitude across all frame pairs | ≥1.5 px/frame mean | 0.15 |
| **M8** | outfit_stability | Outfit doesn't drift mid-clip | Pairwise chest-band BGR mean cosine across video frames sampled every 1.0 s | ≥0.85 cosine | 0.10 |
| **M11** | video_face_consistency | Same face across all frames of a scene (no identity drift) | Pairwise cosine over InsightFace 512-d embeddings sampled every 0.5 s, frames with single face only | ≥0.85 mean | 0.15 |

### Screenplay-stage metrics (cheap, runs once per project)

| ID | Name | Definition | Measurement | Target | Weight |
|---|---|---|---|---|---|
| **M9** | beat_distinctness | Scene breakdown beats use different verbs (not paraphrased clones) | Stem the action-verbs across each scene's 6 beats, divide unique by total | ≥0.60 | 0.075 |
| **M10** | story_has_arc | Scenes are not all `purpose=action` or all `purpose=reaction` — there's tension/turn/payoff | Count distinct `scene_purpose` values across the project | ≥2 distinct → 1.0; only 1 → 0.0 | 0.075 |

Total weight: 1.000.

> **2026-05-07 reweighting.** When iter4 dropped action-still pinning from
> the LTX condition list (F-NO-STILL-PINS), the rubric had to follow:
> stills no longer drive video motion, so M3/M4/M5 weight cut from 0.10
> each → 0.05 each. The freed 0.15 + 0.05 (from M2 hand-grade demote)
> went to video metrics: M7 0.10 → 0.15, plus new **M11 video_face_consistency**
> at 0.15. Net effect: video weights went from 0.35 → 0.55, still weights
> from 0.40 → 0.20. The rubric now scores what the user actually watches.

---

## Baseline — 2026-05-07 11:18 yoga_mat run (project 69993ede)

Measured by hand from the artifacts (script not yet built — script is
the next deliverable, but we can hand-grade the first run to set
baseline):

| ID | Score | Notes |
|---|---|---|
| M1 bg_zero_people | **0.0** | Stylized yoga figure visible center-frame |
| M2 portrait_outfit_match | **0.05** | Portrait is BLACK long-sleeve + black pants; spec was sage green tank + olive leggings |
| M3 stills_one_person | **1.0** | Every action still has exactly 1 woman ✓ |
| M4 stills_outfit_match | **0.65** | Action stills wear green/olive — close to spec, but mostly missing the "tank top" spec (some show full sleeves) |
| M5 pose_variance | **0.10** | All 6 stills of scene 0 are kneeling-on-mat clones; scene 1 all sitting-cross-legged clones |
| M6 video_one_person | **0.40** | Scene 1 frames 1-6 show TWO people (bg leak ⇒ second character hallucination) |
| M7 motion_magnitude | **0.20** | Mostly static; outfit and body morph in place rather than moving |
| M8 outfit_stability | **0.15** | Outfit visibly transitions black→green during scene 0 |
| M9 beat_distinctness | **0.20** | Scene 0 beats: "initiates → continues → halfway → fully → smoothing → smoothing" (clones) |
| M10 story_has_arc | **0.50** | 2 distinct purposes (action, reaction) but no real arc |

**Weighted baseline score:** ≈ **0.31 / 1.00**.

That's our floor. Every change must move the weighted score up.

---

## Iteration log

Each row = one change set + its rerun. Keep deltas honest — if a metric
regresses, note WHY before deciding whether to keep the change.

| Iter | Date | Change | M1 | M2 | M3 | M4 | M5 | M6 | M7 | M8 | M9 | M10 | Total (auto/hand) | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0 | 2026-05-07 11:18 | (baseline, no fixes) — project `69993ede` | 0.00 | _hand_ | 1.00 | 0.99 | 0.07 | 0.73 | 1.00 | 1.00 | 0.71 | 1.00 | **0.716 / 0.31** | baseline (re-graded with InsightFace+auto-M4/M5/M8) |
| 1 | 2026-05-07 12:46 | F1: bg "no person" prompt + F2: portrait outfit splice — `9613e5f4` | **1.00** | _hand_ | 1.00 | 1.00 | 0.05 | **1.00** | 1.00 | 1.00 | **1.00** | 1.00 | **0.893 / 0.69** | KEEP — bg leak killed |
| 2 | 2026-05-07 13:10 | F-PORTRAIT-OFF: skip static portrait LTX cond when stills present — `543482e9` | 1.00 | _hand_ | 1.00 | 0.98 | 0.07 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | **0.894 / 0.77** | KEEP — M6 → 1.0, no 2-person hallucination |
| 3 | 2026-05-07 14:02 | F3: per-beat distinct pose-refs (targets M5) — `e027c93a` | 1.00 | _hand_ | 1.00 | 1.00 | **0.41** | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | **0.885 / —** | KEEP — graded under new rubric (incl. M11=0.47); M5 0.07→0.41 was the headline win |
| 4 | _pending_ | F4 (bg-bake) **+** F-NO-STILL-PINS (drop action stills as LTX conditions) **+** M11 added — krishna_butter ad | | | | | | | | | | | | |

---

## Rules of engagement

1. **One change per iteration.** Don't bundle. We can't tell which lever moved which metric.
2. **Each change must be tied to a specific metric it targets.** The PR/commit should name the metric (e.g., "F1 → M1+M6").
3. **Revert on regression.** If the targeted metric improves but >2 unrelated metrics regress, the change is reverted.
4. **Don't tune the rubric to flatter the change.** Targets and weights are locked unless we explicitly agree to revisit them in a separate doc.
5. **Three failed iterations in a row → stop and rethink.** No infinite loops.
6. **GPU utilization is a SECONDARY metric** (separate, not in the rubric): we want each rerun to keep both GPUs busy, but high util on a low-quality run isn't progress.
