# ControlNet OpenPose Implementation Plan

**Goal:** Force the still-generation step to actually render the body
composition the scene requires (full-body for walking, kneeling pose for
soil-touching, hands-only for closeup actions) instead of SD3.5 defaulting to
upper-body portraits regardless of prompt wording.

**Status:** Not started — multi-day work, concrete next-session task.
**Last updated:** 2026-05-05

---

## 1. Why this matters (the actual problem)

Across the last ~10 runs, the dominant remaining quality bug is:

> The LLM writes a prompt that clearly describes a full-body action ("Sadhguru
> kneels and lifts soil from the cracked earth, full body visible"), but
> SD3.5 Medium renders him from waist-up only. The action verb ("kneels",
> "lifts") gets rendered as a vibe (slightly lowered shoulders, hand near
> mouth) instead of as actual body kinematics.

We've already verified — by surfacing the LLM's prompt next to the still in
the UI ([fix #2](#)) — that **the LLM is writing the right prompt**. The
problem is downstream: **SD3.5 ignores composition cues from text alone**.
Models trained on internet image data have a strong bias toward portraits and
upper-body shots because that's what most stock human imagery looks like.

Pure prompt engineering cannot fix this. We need to give SD3.5 a **structural
constraint** — a stick-figure pose that the model has to fit the character
into. That's exactly what ControlNet OpenPose does.

**Concrete examples from recent Save Soil runs:**

| Scene intent | What SD3.5 actually rendered | Body parts that should have been visible |
|---|---|---|
| Sadhguru walks across the dying field | Head + shoulders, no legs | Both legs in mid-stride |
| Sadhguru kneels and lifts lifeless soil | Sitting/leaning torso, no knees, no hands on soil | Knees on ground, hands cupping soil |
| Farmer sifting cracked earth | Chest-up, hands holding small clump | Both hands, fingers spread, full forearms |
| Child pressing sapling into soil | A face emerging from blurred shape | Two hands pressing down, sapling visible |

In every case, the LLM prompt explicitly named the action and the relevant
body parts. SD3.5 ignored them and gave us a generic portrait composition.

---

## 2. What ControlNet OpenPose actually does

ControlNet is an architectural addition to a diffusion model that takes a
**second, structural input** alongside the prompt and forces the output to
respect that structure. OpenPose is a specific kind of structural input:
a stick-figure skeleton showing where the body's joints are positioned in
the frame.

**Input to ControlNet OpenPose:**
- Standard text prompt (same as today)
- A pose image — colored stick figure with 18-25 keypoints (head, shoulders,
  elbows, wrists, hips, knees, ankles)

**Output:**
- An image where the rendered character's body **matches the skeleton**.
  Walking pose → SD renders walking. Kneeling pose → SD renders kneeling.
  Hands forward → SD renders hands forward.

**Strength control:**
- ControlNet weight (0.0-1.0) decides how strict the pose constraint is.
  Strict (0.9-1.0) = exact pose match, less prompt freedom for face/clothing.
  Loose (0.4-0.6) = pose suggestion, more prompt freedom.

**Key property:** ControlNet decouples *composition* from *appearance*. The
prompt drives skin/clothing/style; the pose image drives body composition.
This is exactly the separation we need.

---

## 3. Landscape survey — what's actually available

ControlNet support varies wildly by base model. We need to pick the
combination that minimizes engineering effort while producing acceptable
quality.

### Option A — Stay on SD3.5, use community ControlNet
- **Status:** Stability AI released *official* ControlNets for SD3.5 in
  late 2024: **Canny, Depth, Blur**. There is **no official OpenPose
  ControlNet for SD3.5** as of writing.
- **Community alternatives:** A few Hugging Face users have trained
  pose-conditioned ControlNet variants for SD3.5, but they're underbaked —
  small training datasets, inconsistent results, no commercial backing.
- **Verdict:** Risky. Quality is unproven. Maintenance burden is high.

### Option B — Add SDXL as a parallel still-generation backend
- **Status:** SDXL has the most mature ControlNet ecosystem. Multiple
  high-quality OpenPose ControlNets (`thibaud/controlnet-openpose-sdxl-1.0`,
  `xinsir/controlnet-openpose-sdxl-1.0`) with thousands of users.
- **Implementation:** Add SDXL as a second image provider alongside SD3.5.
  Use SDXL+ControlNet for action stills (where pose matters); keep SD3.5
  for character portraits (where pose doesn't matter as much).
- **Verdict:** **Recommended.** Lowest-risk path. Mature tooling.

### Option C — Switch entirely to Flux + Flux ControlNet
- **Status:** XLabs released Flux ControlNet Union which includes pose
  conditioning. Flux has noticeably better human anatomy than SD3.5/SDXL.
- **Implementation:** Replace SD3.5 with Flux dev or Flux schnell for stills.
  Flux is heavier (12GB+ VRAM for fp16) so might require quantization.
- **Verdict:** Highest quality ceiling, but biggest scope of change. Defer to
  Phase 2 unless Option B underperforms.

**Recommendation for Phase 1: Option B (SDXL + OpenPose ControlNet) for
action stills only.** Keep SD3.5 for character portraits.

---

## 4. Where do the pose images come from?

This is the part most people miss. ControlNet needs a stick figure as input.
We have three options:

### Option α — LLM picks from a fixed pose library
Maintain a curated set of ~30 named pose presets (`walking_left`,
`kneeling_facing_camera`, `reaching_forward`, `lifting_overhead`, etc.)
stored as PNG skeletons. The LLM picks one based on the scene's action verb.

**Pros:** Deterministic, fast, no extra ML at inference time.
**Cons:** Limited variety; bizarre actions ("riding a bicycle backwards") fall
through to the closest match, which may be wrong.

### Option β — LLM emits keypoint coordinates, we render the skeleton
Prompt the LLM with: *"Output an array of (x, y) coordinates for each of
these 18 OpenPose keypoints to depict the action: head, neck, shoulders, ..."*
Then render the skeleton at runtime via PIL.

**Pros:** Unlimited variety; tightly coupled to scene description.
**Cons:** LLMs are bad at spatial coordinates; output is unreliable.
Significant prompt engineering needed. Failed attempts produce garbage poses.

### Option γ — Use a reference image + DWPose preprocessor
For each scene, find a reference image that matches the action (from a stock
library, Unsplash, or even a quick web search). Run DWPose (an OpenPose
implementation) on the reference image to extract a skeleton. Use that
skeleton as ControlNet input.

**Pros:** Real human poses, high-fidelity skeletons. Lots of variety.
**Cons:** Requires curating or fetching reference images. Adds latency.
Copyright considerations on reference images.

**Recommendation: Phase 1 ships Option α (pose library) for the most common
action verbs. Phase 2 adds Option γ for actions that aren't in the library.
Skip Option β entirely — LLMs and 2D coordinates don't mix.**

---

## 5. Pose library — what verbs to cover initially

Audit of action verbs used across the last 30 generated projects, ranked by
frequency:

| Pose preset | Covers verbs |
|---|---|
| `standing_neutral_full_body` | standing, waiting, listening, observing |
| `walking_forward` | walking, approaching, advancing |
| `walking_away` | walking away, departing, leaving |
| `running_forward` | running, sprinting, chasing |
| `kneeling_facing_camera` | kneeling, praying, examining low |
| `kneeling_three_quarter` | kneeling sideways, picking up, working ground |
| `sitting_cross_legged` | meditating, sitting on floor |
| `sitting_chair` | sitting at table, dining |
| `lying_down` | sleeping, falling, resting |
| `reaching_forward` | reaching, offering, handing |
| `lifting_overhead` | lifting, raising, celebrating |
| `lifting_chest_height` | carrying, holding object |
| `embracing` | hugging, holding child |
| `pointing` | pointing, indicating, directing |
| `looking_up` | looking at sky, awe, inspiration |
| `head_in_hands` | despair, exhaustion, contemplation |
| `arms_crossed` | confident, defensive, waiting |
| `hands_on_hips` | confident, surveying |
| `gesture_speaking` | talking, explaining, expressing |
| `bow_namaste` | greeting, prayer, respect |

**~20 presets cover ~85% of action verbs in the dataset.** Generate them
once, commit to repo, ship.

For close-up actions (hands-only, face-only, object-only) we **don't need
pose control** — the LLM prompt handles those fine because they're already
the kind of shot SD3.5 defaults to. Only mid/wide body shots need pose.

---

## 6. Architecture changes

### New files / modules
| File | Purpose |
|---|---|
| `backend/app/providers/image/sdxl_pose_provider.py` | New `ImageProvider` impl — wraps SDXL+ControlNet OpenPose. Same interface as `SD35ImageProvider`. |
| `backend/app/agents/image_pregen/_pose_library.py` | Maps pose preset names → skeleton PNG paths. |
| `backend/app/prompts/pose_picker.txt` | System prompt for the pose-picker LLM agent. |
| `backend/app/agents/pose_picker.py` | New agent: scene + action_desc → pose preset name. |
| `assets/poses/*.png` | The actual stick-figure skeletons (~20 PNGs, 1024×1024 each). |
| `sdxl_pose_generate.py` | New GPU subprocess script (mirrors `ltx_generate.py` / `chatterbox_generate.py` pattern). Loads SDXL + ControlNet + pose, generates image. |

### Modified files
| File | Change |
|---|---|
| `backend/app/agents/image_pregen/action_stills.py` | Call `pose_picker` first, then route to `sdxl_pose_provider` (for action stills) or `sd35_provider` (for character portraits). |
| `backend/app/config.py` | Add `image_provider_action_stills: str = "sdxl_pose"` (so we can A/B easily). |
| `requirements.txt` | Add `controlnet_aux` (skeleton renderer), pin `diffusers` version. |

### Inference flow (proposed)

```
scene description
    ↓
pose_picker LLM
    ├──→ pose_preset = "kneeling_facing_camera"
    ↓
load assets/poses/kneeling_facing_camera.png  (the stick figure)
    ↓
SDXL + ControlNet OpenPose
    ├── prompt: "Sadhguru in white robe, weathered features, kneeling..."
    ├── pose:   <stick figure>
    ├── controlnet_strength: 0.7
    ↓
output PNG (character now actually in kneeling pose)
    ↓
existing pipeline (bg removal → save → LTX)
```

### Subprocess pattern
SD3.5 already runs as a subprocess (`generate_sd35.py` in `~/sd35-medium/`).
We add a parallel subprocess `sdxl_pose_generate.py` that gets invoked the
same way. This keeps GPU memory clean (SDXL model unloads after each call).

---

## 7. Phased implementation plan

### Phase 1 — Minimum viable (estimated: 2-3 days)

**Day 1: Pose library + LLM picker**
- [ ] Generate 20 named pose skeleton PNGs. Use Stable Diffusion + manual
  curation, or scrape from existing OpenPose datasets. ~3 hours.
- [ ] Write `pose_picker.py` agent + system prompt. Single LLM call returning
  `{"pose_preset": "...", "reason": "..."}`. ~2 hours.
- [ ] Unit-test pose_picker against 20 sample scene descriptions to verify
  it picks reasonable presets. ~1 hour.

**Day 2: SDXL+ControlNet subprocess + provider**
- [ ] Write `sdxl_pose_generate.py` (mirror of `ltx_generate.py`). Loads
  SDXL base + ControlNet OpenPose model. Accepts `--prompt`,
  `--negative-prompt`, `--pose-image`, `--controlnet-strength`, `--output`.
  ~4 hours (most of this is figuring out diffusers SDXL+ControlNet API).
- [ ] Write `SdxlPoseImageProvider`. Implements the existing
  `ImageProvider` interface. Calls the subprocess. ~2 hours.
- [ ] Add config flag `image_provider_action_stills = "sdxl_pose"`. ~30 min.

**Day 3: Pipeline wiring + first end-to-end test**
- [ ] Update `action_stills._generate_one_still` to:
  1. Call pose_picker for this scene.
  2. Route through `sdxl_pose_provider` instead of `sd35_provider`.
  3. Pass pose image + controlnet_strength.
  ~3 hours.
- [ ] Run preview pipeline, sample stills, compare composition vs current
  baseline. ~2 hours.
- [ ] Iterate on controlnet_strength until quality matches target. ~3 hours.

**Phase 1 deliverable:** action stills consistently render the named action
verb with correct body composition. The 20-preset library covers ~85% of
real scenes. Misses fall back to existing SD3.5 path silently.

### Phase 2 — Quality polish (estimated: 1-2 days)

**Day 4: Vision-critic feedback loop**
- [ ] Extend the vision-LLM critic ([fix #8](#)) to grade pose match
  specifically. New field: `pose_matches_action: bool`.
- [ ] When critic flags pose mismatch, automatically re-pick pose preset and
  regenerate that single still. ~3 hours.

**Day 5: Reference-image pose extraction (Option γ)**
- [ ] Integrate DWPose preprocessor (`pip install controlnet_aux`).
- [ ] When LLM picks "custom" pose (not in library), require a reference
  image input from the user (or a search step). Run DWPose on it. Use the
  extracted skeleton. ~5 hours.

**Phase 2 deliverable:** library covers 100% of scenes. Misses can be
resolved with a single reference image. Critic auto-corrects bad poses.

### Phase 3 — Optional (estimated: 2-3 days)

- Switch from SDXL to Flux + Flux ControlNet for higher base-model quality.
- Add per-character pose calibration (Sadhguru's robe drapes differently in
  walking pose vs younger characters).
- Animated pose interpolation between start-of-scene and end-of-scene
  skeletons for smoother LTX motion.

---

## 8. Risks and mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| SDXL adds significant VRAM pressure (12GB+ models) | Medium | Use SDXL Lightning / Turbo (4-8 step distilled) — runs in 6GB. Trade quality for VRAM. |
| ControlNet weights conflict with our existing SD3.5 setup | Low | Subprocess isolation (separate `sdxl_pose_generate.py`) means no shared model state. |
| Pose library doesn't cover an action → silent fallback to portrait | High in early runs | Vision-critic flags it; we add the missing pose to library. Self-correcting. |
| LLM picks wrong pose preset for the action | Medium | Vision-critic catches it; pose-picker can be retried. Cost is one wrong still. |
| 20 hand-curated pose images take longer than 3 hours | Medium | Buy a pose library (CivitAI, Mixamo) — there are public domain pose packs. ~$20-50 saves a day. |
| Body proportions of stick figure don't match character (tall vs short) | Low | ControlNet matches *pose*, not proportions. Character height drift is the same as today. |
| ControlNet at strength=0.7 fights the prompt's clothing/style descriptors | Low | Tunable via `controlnet_strength`. Test 0.4-0.9 sweep. |

---

## 9. Test plan

### Unit tests
- `pose_picker.py`: feed 20 sample scene descriptions, assert a reasonable
  pose preset is picked. Stubbed LLM with deterministic responses.
- `sdxl_pose_provider.py`: mock subprocess, verify command-line args are
  built correctly (prompt, pose-image path, controlnet strength).
- `_pose_library.py`: verify all 20 named presets resolve to a real PNG file.

### Integration tests
- Stub LTX/SD3.5 → run full image_pregen with the SDXL pose provider →
  verify each scene gets a still that matches the picked pose preset.

### Quality validation (manual)
- Run preview e2e with the same Save Soil prompt before and after ControlNet.
- Inspect each scene's still: does the body composition match the action
  verb in `scene.visual_summary`?
- Compare: % of scenes where SD3.5 alone got composition right vs % where
  SDXL+ControlNet got it right. Target: 85%+ correct (vs current ~30%).

### Quality regression
- Keep an SD3.5-only fallback flag on. If SDXL pose path produces worse
  results on simple scenes, we can A/B per-project until we've tuned it.

---

## 10. Cost & resource estimate

**One-time costs:**
- Engineer time: 3-5 days for Phases 1+2.
- VRAM: SDXL base + ControlNet OpenPose ≈ 8-10 GB at fp16. We have a 12 GB
  GPU; runs but with sequential offload. SDXL Lightning brings it to ~6 GB.
- Disk: SDXL base (~7 GB), ControlNet (~2.5 GB), pose library PNGs (~5 MB).
  Total ~10 GB additional storage.
- Optional pose pack purchase: $20-50.

**Per-run costs:**
- Inference time: SDXL Lightning at 4-8 steps takes ~6-10 sec per still. SD3.5
  Medium at 95 steps takes ~50 sec. **Net 3-5x faster per still even with
  the ControlNet overhead.**
- Pose-picker LLM call: 1 cheap call per still. ~$0.0002.
- VRAM peak unchanged (subprocess isolation).

**Net effect:**
- Per-scene image_pregen time: probably **decreases** (SDXL faster than SD3.5).
- Per-scene quality: significantly increases for action shots.
- Iteration speed: same (preview mode unaffected).

---

## 11. Acceptance criteria (Phase 1 done when…)

- [ ] 20 pose presets exist as committed PNG files
- [ ] `pose_picker` agent reliably picks the right preset for canonical
      verbs in 18+/20 unit tests
- [ ] Preview pipeline runs end-to-end with SDXL+ControlNet for action stills
- [ ] On a fresh Save Soil run, **at least 4 of 5 scenes** show the correct
      body composition (legs visible for walking, knees on ground for
      kneeling, hands forward for reaching, etc.)
- [ ] No regression on character-portrait quality (still uses SD3.5)
- [ ] All existing tests pass (current: 149/149)

---

## 12. Open questions for the human

1. **Do we want SDXL or Flux as the base?** Flux has better humans but is
   heavier (12 GB+). SDXL is ~10 GB and well-trodden. **Default
   recommendation: SDXL Lightning for speed + quality balance.**

2. **How many pose presets is enough?** 20 covers 85% per the audit. 50
   covers ~95% but doubles the curation effort. **Default: 20 for Phase 1,
   expand only when vision-critic shows misses.**

3. **What's the controlnet_strength default?** 0.7 is the conservative
   sweet spot. Higher = more rigid pose, less prompt fidelity. **Default:
   0.7, expose as config flag for A/B.**

4. **Should we pose-control the character portrait too?** Argument for: even
   the portrait could lean upper-body. Argument against: portraits are pure
   identity references, no scene action. **Default: no — portraits stay on
   plain SD3.5.**

5. **Is it worth buying a pose pack?** ~$30 saves probably half a day of
   curation. **Default: yes, if a clean public-domain pack exists.**

---

## 13. What this does NOT solve

ControlNet OpenPose fixes **body composition**. It does NOT fix:

- LTX-Video's own motion generation quality (separate fix: bump
  `ltx_inference_steps`, switch to Wan-Video / HunyuanVideo)
- Burned-in subtitle artifacts (separate fix: already mitigated by
  prompt sanitizer + hardcoded text-rejection negative)
- Cross-scene character identity drift (separate fix: IP-Adapter +
  reference image + already-deployed character-change chain reset)
- Color/style drift across scenes (separate fix: already-deployed
  `style_lock` + lower visual_director temperature)
- Audio sync issues (separate fix: scene timing + audio_director changes)

ControlNet is a focused win on one specific axis. Don't expect it to fix
unrelated problems — that's how we ended up with the 7-framing rabbit hole
last time.

---

## 14. Recommendation

**Do Phase 1 (3 days) as the next dedicated work session.** Phase 1 alone
will materially fix the "Sadhguru waist-up walking" problem on every run.
Phase 2 is opportunistic — add it when a real scene falls outside the pose
library and the vision critic catches it.

Defer Phase 3 indefinitely. Switching to Flux is a separate evaluation; we
don't need to bundle it with pose control.
