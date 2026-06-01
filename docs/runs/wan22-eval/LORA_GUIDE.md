# Wan 2.2 LoRA guide — when each one gets used

Plain-English summary of how the Wan22 pipeline picks a "style filter" (LoRA) for each scene of your ad.

## How it works in one sentence

The pipeline reads each scene's prompt, figures out **what kind of scene it is** (closeup, action, dramatic, etc.), and **which way the camera frames the subject** (closeup, medium, wide). Those two answers pick the LoRA + weight + whether to run face restoration afterward.

## The 5 LoRAs we actually use

### 🎬 `crush_it` — the default "ad polish"

Punchy, cinematic color grade. Saturated, slightly contrasty. Looks like a modern commercial.

**Used for:** running, walking, crowds, generic closeups, dancing — basically anything that doesn't need a stronger style. **This is the workhorse.**

**Weight:** 0.5 (subtle polish).

### 🌅 `hstoric_color` — the "golden hour / fire" filter

Warm, golden-orange, sepia-leaning grade. Makes things feel like sunset or candlelight.

**Used for:**
- Scenes that explicitly involve **fire or flame** (chef cooking, candles, flames) → at full strength (1.0)
- **Historical / period** scenes (medieval, ancient) → at full strength (1.0)

**Why:** It dramatically pops fire/flame colors and gives period scenes the warm vintage tone.

### 🎥 `zackdfilms` — the "epic cinematic" filter

Heavy contrast, dramatic lighting, dust + light beams. Like a movie-trailer LUT.

**Used for:**
- **Dramatic / war / hero** scenes — soldiers, samurai, knights, sword fights, battlefields
- At full strength (1.0) for full cinematic epic look

### 🎨 `oil_painting` — the "editorial fashion" filter

Painterly brush texture across the frame. Looks like a magazine spread or art piece.

**Used for:**
- **Fashion editorial** scenes — model, runway, handbag, designer
- At half strength (0.5) for subtle painterly feel

### 💧 `aether_splash` — the "wet / water" filter

Adds wet/glossy/spray look to whatever's in frame.

**Used for:**
- **Water-themed** scenes — splashes, rain, drinks
- At full strength (1.0)
- ⚠️ Only when prompt explicitly involves water — otherwise it adds out-of-place wet artifacts

### ⛔ no LoRA — the "leave it alone" option

Used for **dancing** and **walking** scenes — motion clarity matters more than mood, and any LoRA blurs the motion.

## Scene-type cheat sheet

| If the scene is about… | LoRA picked | Weight | Face restoration? |
|---|---|---|---|
| A chef cooking with flames | `hstoric_color` | strong (1.0) | no (closeup) |
| A runner / sprinter / jogger | `crush_it` | mild (0.5) | yes (wide shot) |
| A coffee/portrait/face closeup | `crush_it` | mild (0.5) | no (closeup) |
| A model with a handbag / fashion | `oil_painting` | mild (0.5) | no (medium shot) |
| A dancer | none | — | depends on framing |
| A medieval knight / samurai / battle | `zackdfilms` | strong (1.0) | yes (wide shot) |
| A crowd / rally / protest | `crush_it` | mild (0.5) | yes (wide shot) |
| Rain / splashes / drinks pouring | `aether_splash` | strong (1.0) | no (closeup) |
| Someone walking | none | — | no |
| A historical / period setting | `hstoric_color` | strong (1.0) | no (medium) |
| Anything else | `crush_it` | mild (0.5) | depends on framing |

## Face restoration (CodeFormer) — when does it run?

**Only on wide shots**, never on closeups. The rule:

- **Closeup** in the prompt → no face restoration (the face is already big enough; restoration over-processes it)
- **Wide shot / from afar / panoramic** → face restoration runs (the face is small and needs help)
- **Medium** → no by default

So a wide-shot runner gets face restoration (face is tiny in frame), but a closeup of the same runner does not (face is already clear).

## What this means in practice for your 10 ads

Each ad's 5 scenes get classified independently. So within a single ad, scene 1 might be a closeup (no LoRA boost, no post-process), and scene 4 might be a wide shot (gets `crush_it` + face restoration). The pipeline figures it out scene-by-scene.

For example, the chef-plating ad will probably mostly use:
- Macro closeups of hands / tweezers / olive oil → no LoRA boost, no face restoration
- The wide "wait staff lifting the dish" shot → `crush_it` + face restoration

And the samurai-style ad (or any war ad) will lean on `zackdfilms` at full strength for the dramatic battlefield scenes.

## What we DON'T use (and why)

- `aether_punch` — invisible in our tests. Skipped.
- `woven_fabric` — looks like a watermark/noise overlay on most scenes. Skipped (except theoretical historical tapestry, which we don't generate).
- `lightning_a14b` — architecturally incompatible with the 5B model. Will never work.

## How it picks programmatically — the 4 steps

When the pipeline asks Wan22 to render scene N, this happens:

### Step 1 — break the prompt into words

```python
prompt = "A male chef in his 40s plates a fine-dining dish in a stainless steel kitchen..."
words  = ["a", "male", "chef", "in", "his", "plates", "a", "fine", "dining", ...]
```

### Step 2 — pick the scene type

Walks down the catalog's `tag_index` (most-specific first). The **first** tag list with any matching word wins.

```yaml
tag_index:
  closeup_with_fx:        [flame, fire, spark, blaze]        ← checked 1st (most specific)
  water_splash_fx:        [water, rain, drink, splash]
  dramatic_cinematic_war: [war, battle, soldier, sword, samurai, knight, armor]
  historical_period:      [historical, period, ancient, medieval]
  editorial_fashion:      [purse, handbag, runway, editorial, fashion, designer]
  crowd_mass_scene:       [crowd, rally, chant, protest]
  dancing_high_motion:    [dance, dancer, spin, twirl, ballet]
  closeup_portrait:       [closeup, portrait, headshot]
  walking_locomotion:     [walk, stroll]
  action_running:         [run, sprint, jog, athletic]       ← checked last (most generic)
```

Match rule: a word counts if it **equals a tag** *or* **equals tag + {s, es, ed, ing}**. So `running` matches `run`, `walked` matches `walk`. But `warm` does **not** match `war` — fixes the "warm pendant lighting" trap.

For our chef prompt: no flame/fire/water words → no early match → falls through to `closeup_portrait` (the default fallback).

### Step 3 — pick the shot type

Same word-matching against `shot_index`. If nothing matches, falls back to the scene's `default_shot`.

```yaml
shot_index:
  closeup: [closeup, portrait, headshot, face, talking]
  wide:    [wide, panoramic, aerial, "from afar", "in the distance"]
  medium:  [medium, "waist up", torso]
```

Chef prompt has `closeup` and `shallow depth-of-field` → matches **closeup**.

### Step 4 — look up the LoRA + decide post-process

```yaml
scene_map:
  closeup_portrait:
    primary: { lora: crush_it, weight: 0.5 }
    default_shot: closeup
    ...
```

So `(scene_type=closeup_portrait, shot_type=closeup) → crush_it @ 0.5, no post-process`.

Post-process rule (one line):
```python
do_post_process = (shot_type == "wide")
```

### Step 5 — hand off to the renderer

The provider builds a subprocess command:

```bash
python wan22_generate.py \
    --prompt "..." \
    --lora-id crush_it \
    --lora-file crush_it_5b.safetensors \
    --lora-weight 0.5 \
    --height 480 --width 832 --num-frames 121 --num-inference-steps 40
```

And `wan22_generate.py` loads it with two lines of diffusers:

```python
pipe.load_lora_weights("crush_it_5b.safetensors", adapter_name="crush_it")
pipe.set_adapters(["crush_it"], adapter_weights=[0.5])
```

That's it. No LLM, no database, no per-project state. Just text → keyword match → catalog lookup → safetensors load.

### Why keyword match and not an LLM classifier?

- Deterministic — same prompt always picks the same LoRA. Repeatable across runs.
- Cheap — runs in microseconds, no API call.
- Auditable — every line in `tag_index` is visible; you can add a tag and know exactly which scene types will start matching it.
- Replaceable — `classify()` returns a 4-tuple; swapping in an LLM classifier is a 10-line change. We just don't need it for the current catalog.

## Where this lives

- The full catalog with files + tags: [`lora_catalog.yaml`](lora_catalog.yaml)
- The full technical writeup with comparison frames + per-LoRA verdicts: [`SUMMARY.md`](SUMMARY.md)
- The provider code that does the selection at runtime: [`backend/app/providers/video/wan22_provider.py`](../../../backend/app/providers/video/wan22_provider.py)
