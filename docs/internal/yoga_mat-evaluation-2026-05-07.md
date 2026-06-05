# yoga_mat Evaluation — 2026-05-07 11:18 run

Project: `69993ede-cdba-40c4-b22b-cc53e1197709`
Final: `backend/storage/renders/.../final_render.mp4` — 576×1024, 12fps, 12.0s.
Verdict: **horrible.** Pipeline ran end-to-end without crashing, but output is unusable as an ad.

---

## What's broken (ranked by severity)

### 1. Background contains a person

The bg image (`sun-dappled_wooden_yoga_studio_floor.png`) has a literal stylized
human figure in tree pose painted into the empty studio. Despite the negative
prompt explicitly listing `people, characters, person, human, no characters
no people empty scene`, SD3.5 ignored it.

**Why:** the positive prompt contains *"for a head-to-toe standing person to
be composited in later"* and *"yoga studio"*. SD3.5 weights early positive
tokens far above negatives. The literal word "person" in the positive plus
"yoga studio" (a category strongly associated with human poses) overpowered
the negative.

**Downstream damage:** LTX was conditioned with this bg as an anchor at the
mid-frame. It read the painted figure as a real character. Scene 1's first 3
seconds show **two people** — a tall standing woman behind a seated woman
who appears to materialize. The bg leak became a visible second-character
hallucination in the final video.

### 2. Character outfit drift mid-clip

Story-analyst-defined outfit: *"sage green tank top, olive yoga leggings,
barefoot."*

What rendered:
- **Portrait** (`woman_in_her_30s.png`): black long-sleeve top, black pants,
  black chunky boots. SD3.5 ignored the entire clothing description.
- **Action stills** (s00..s05): green tank + olive leggings — closer to spec
  but still not matching the portrait.
- **LTX scene 0**: opens with character in BLACK at frame 0, transitions to
  green tank by frame 6. Outfit visibly changes mid-clip because LTX
  interpolates between the (wrong) portrait conditioning and the (correct)
  action-still conditioning. The wardrobe morphs on screen.

### 3. Static, near-identical action stills → no real motion in video

The visual_director generated 6 nearly-identical beat descriptions for scene
0:
```
0–1s: initiates unrolling mat + low-angle wide shot
1–2s: continues unrolling smoothly + low-angle wide shot
2–3s: mat halfway unrolled, hands visible + low-angle wide shot
3–4s: mat fully unrolled, hands smoothing + slow dolly-in
4–5s: hands smoothing texture + medium close-up
5–6s: hands finish smoothing, she pauses + medium close-up
```

InstantID + OpenPose then produced 6 nearly-identical kneeling poses (all
with the same pose-ref skeleton, since pose_ref is generated ONCE per scene).
LTX has no kinetic targets to interpolate between, so the resulting "motion"
is mostly the character morphing in place rather than actually moving.

The pose-library matcher gave us `sitting_bench` and `woman_sitting_floor`
— **both static poses**. Then we asked for 6 stills of "unrolling a mat"
all anchored to the same skeleton. There was never going to be motion.

### 4. Screenplay has no narrative arc

12-second story summary: *"A woman unrolls a yoga mat, then sits and says
'start where you are.'"*

That's not an ad — it's a screensaver. No hook, no problem, no emotional
turn, no product reveal, no payoff. The scene_planner is generating
"lifestyle moments" instead of micro-narratives.

For a 12-second ad we need:
1. **Hook** (first 2-3s): something that *demands* attention — a beat of
   tension, a question, an unexpected visual.
2. **Turn** (3-9s): the hero/product/feeling that resolves the hook.
3. **Payoff** (9-12s): the line, the brand, the call to action.

What we got is 6 seconds of unrolling + 6 seconds of sitting still. Zero
arc.

### 5. LTX latent-upscale step disabled (output is 576×1024)

Output res is acceptable for mobile but soft on desktop. The 3-step LTX
upscale path is currently force-disabled because step 3 (refine at 2× pixel
res) OOMs on the 16 GiB GPU 0 even at small base resolutions.

Root cause: step 3 reuses the same FP8 transformer pipe (~13 GiB resident)
plus activations at 2× spatial dims (~4× the activation memory of step 1).
Total ~17+ GiB → OOM on a 16 GiB GPU.

**Fix path**: replace LTX's in-pipeline latent upscale with a separate
post-LTX upscale subprocess. After LTX exits, all 14 GiB free; a Real-ESRGAN
or even a fast `ffmpeg lanczos` pass at 1.78× → 2048×1152 fits comfortably
on either GPU.

### 6. (Done) Video gen is on the larger GPU
Confirmed: `ltx_provider.py` sets `CUDA_VISIBLE_DEVICES=0` with
`CUDA_DEVICE_ORDER=PCI_BUS_ID`, and GPU 0 is the 16 GiB 5070 Ti per
nvidia-smi. No fix needed — but worth a runtime assert.

---

## Fix plan (in implementation order)

### F1 — Background prompt: kill the "person" leak (30 min)

- Strip *"for a head-to-toe standing person to be composited in later"*
  from `_BG_FRAMING_PREFIX` in
  [backend/app/agents/image_pregen/prompts.py](backend/app/agents/image_pregen/prompts.py).
  Replace with neutral framing language (e.g. *"empty center area"*).
- Update `background_scene.txt` system prompt: explicitly forbid the words
  "yoga", "studio class", "fitness" when describing yoga settings — name
  the surface ("wood-floored room", "sun-dappled wooden interior") not the
  activity.
- Strengthen negative: prepend `(no humans), (no people), (no figures),
  (empty room)` with SD3.5 weighting.

### F2 — Outfit lock on character portrait too (30 min)

- Apply the same canonical-outfit splice we shipped for action stills,
  but to `build_character_prompt`. Today the LLM is free to paraphrase
  clothing on the portrait, then the splice forces it on the stills,
  causing the **portrait/still mismatch** that LTX morphs through.
- Better: serve the portrait via SD3.5 with an explicit
  `clothing_description` clause **late in the prompt** (high-attention
  position), no LLM paraphrase.

### F3 — Beat-distinct action stills (1 hr)

- Today: `pose_refs.generate_for_scene` returns ONE pose-ref per scene,
  and all 6 stills use that single skeleton. Result: 6 near-clones.
- Fix: per-second beat → per-second pose-ref. Either:
  a. Match each beat against the pose library separately (LLM picks one
     label per beat from the breakdown), or
  b. Drive per-beat skeleton variation from the LLM beat description
     (sit → kneel → reach → smooth → pause) by passing each beat through
     the LLM matcher independently.
- Without this change, LTX has no kinetic targets and the video stays
  near-static regardless of how good the screenplay is.

### F4 — Post-LTX upscale subprocess (1.5 hr)

- After `ltx_generate.py` exits, run a separate
  `upscale_video.py` subprocess in `ltx_provider.py` that scales the mp4
  ~1.8× via `ffmpeg -vf scale=W:H:flags=lanczos` (cheap, CPU-only) or
  Real-ESRGAN if cached. LTX subprocess freed all VRAM by then so OOM
  is impossible.
- Re-enable a config flag `LTX_POST_UPSCALE` (default true).
- Output target: 1024×1820 (≈1.8× from 576×1024) — fits 1080p portrait
  delivery with margin.

### F5 — Better screenplay (2-3 hr, biggest narrative win)

- Rewrite `scene_planner.txt` and `visual_director.txt` to:
  - Force an explicit hook/turn/payoff structure for any ad ≤ 30s.
  - Require each scene's `action_description` to contain a verb-driven
    moment of CHANGE, not a static state.
  - Reject scene plans where the breakdown beats are paraphrases of each
    other (e.g. "unrolling → continues unrolling → halfway unrolled").
- Inject a creative-direction LLM pass that reads the user prompt and
  emits a 12-word logline with hook/turn/payoff. Scene plan must satisfy
  the logline's structure.

### F6 — Loop: rerun yoga_mat → grade frames → fix → rerun

- Start running yoga_mat ad after each fix lands.
- Auto-extract 2 fps frames from each scene mp4.
- Visually grade: outfit consistency? motion variance? bg clean? scene
  has narrative? Iterate.

---

## Frame evidence (what was rendered)

| Frame | Time | What we see | What it should be |
|---|---|---|---|
| s0_01 | 0.5s | Woman in BLACK clothes standing on white mat | Kneeling, beginning unroll |
| s0_06 | 3.0s | Woman in green tank kneeling — outfit drifted | Mid-unroll, smoothing |
| s0_12 | 6.0s | Woman in skimpy sports bra in provocative back-arched pose | Subtle pose hold on mat |
| s1_01 | 0.5s | TWO PEOPLE — standing woman behind seated one | One woman cross-legged |
| s1_06 | 3.0s | TWO PEOPLE — tall figure morphing over seated one | One woman speaking |
| s1_12 | 6.0s | One woman cross-legged, OK | Same |

The two-person hallucination is direct fallout from the bg-leak (item 1).
The outfit drift is direct fallout from item 2. The static morphing
"motion" is direct fallout from item 3. The whole thing is unconvincing
because of item 4.
