# LTX-Video: Multi-Character Prompting & Conditioning Deep Guide

> **Source**: Lightricks official README, LTX Studio documentation, community research (May 2026)  
> **Model**: LTX-Video 0.9.8-dev 13B (`LTXConditionPipeline`)

---

## 1. Official Lightricks Prompt Formula (from GitHub README)

> *"Focus on detailed, chronological descriptions of actions and scenes. Include specific movements, appearances, camera angles, and environmental details — all in a single flowing paragraph. Start directly with the action. Think like a cinematographer describing a shot list. Keep within 200 words."*

### The 7-Step Structure (official order)

| Step | What to Write | Example |
|---|---|---|
| 1. **Main action** | One sentence, what is happening | `"A yoga instructor flows through Surya Kriya on a sunlit stone courtyard."` |
| 2. **Movements & gestures** | Specific physical motion details | `"Her arms rise in a slow arc overhead, palms pressing together at the peak."` |
| 3. **Character appearances** | Age, clothing, hair, features — precise | `"She wears white cotton kurta, dark hair tied back, calm focused expression."` |
| 4. **Background & environment** | Location, surfaces, depth | `"The Dhyanalinga dome rises in the misty background through tall trees."` |
| 5. **Camera angles & movement** | Shot type + how camera moves | `"Wide shot slowly dollying in, then cutting to close-up of hands in Namaste."` |
| 6. **Lighting & colors** | Time of day, quality, color | `"Golden hour sunlight streams horizontally across the courtyard, warm amber tones."` |
| 7. **Changes or events** | What transitions or shifts occur | `"Mist drifts across the frame as the class ends and students bow their heads."` |

---

## 2. Multi-Character Scene Prompting

### The Core Challenge
LTX-Video is a DiT (Diffusion Transformer) model — it does not have native named character slots. Multi-character consistency requires **both** strong image conditioning **and** precise prompt engineering working together.

### Method 1 — Identify Characters by Appearance (not name)

Always distinguish characters by their **distinct visual properties**, not abstract labels like "Character A":

```
✅ GOOD:
"The instructor in white, a tall woman with dark hair tied back, demonstrates the pose 
while a student in grey, a younger man with short curly hair, mirrors her movement 
beside her."

❌ BAD:
"Character A and Character B practice yoga together."
"The instructor and the student do poses."
```

### Method 2 — Camera Separation (most reliable)

Instead of forcing two characters in one shot, use camera work to handle them separately:

```
Scene 1 prompt:
"Close-up shot of the instructor's hands and feet in Tadasana pose, 
white clothing, sunlit stone floor, golden hour light, camera slowly tilts up 
to reveal her calm face and the mountain horizon behind her."

Scene 2 prompt (same clip, student's response):
"Medium shot of a young male student in grey linen, curly hair, 
mirroring the Tadasana pose beside his mat, slight tremor in his raised arms 
as he finds balance, expression shifting from concentration to quiet stillness."
```

### Method 3 — Environment-First Wide Shot (for group scenes)

When multiple characters MUST appear together, establish environment first, then bring in characters:

```
✅ GOOD MULTI-CHARACTER PROMPT:
"Wide cinematic shot of a sunlit yoga shala at the Isha Foundation, stone floors 
and wooden pillars, early morning mist. Eight students in white clothing stand 
in rows on their mats, all moving through Surya Kriya in perfect unison — 
arms sweeping overhead, spines lengthening. A single instructor in white 
walks between the rows, correcting alignment with a gentle touch. 
Camera slowly pulls back to reveal the full courtyard and the misty mountains beyond. 
Morning birds audible. Pure stillness and effort coexisting."
```

### Method 4 — Sequential Action (call and response)

Structure the prompt so characters act one after the other, not simultaneously:

```
"Medium shot in a quiet yoga studio. The instructor, a woman in her 40s 
with greying hair and white robes, demonstrates child's pose — she folds 
forward slowly, forehead lowering to the mat, arms extended. 
Then she rises and nods. A student across from her, a teenage girl 
in blue leggings, attempts the same movement, tentative at first, 
then finding ease as her breath slows."
```

---

## 3. Character Description Formula

Always include all 5 components when describing a character in a prompt:

```
[age range] + [distinctive feature] + [clothing: color + material] + [posture/body state] + [action verb]
```

**Examples:**

| ✅ Strong Character Description | ❌ Weak |
|---|---|
| `"a woman in her 30s with dark hair in a bun, white linen kurta, standing tall in mountain pose"` | `"a yoga instructor"` |
| `"a teenage boy with short curly hair, grey cotton shirt, kneeling carefully on his mat"` | `"a student"` |
| `"an elderly man, white beard, saffron shawl, seated cross-legged in stillness"` | `"an old yogi"` |

**Isha Yoga specific:**
- Instructors: `"trained Isha Hatha Yoga teacher in white cotton kurta, calm and precise"`
- Students: `"student of diverse background in comfortable loose clothing, bare feet on stone"`

---

## 4. Prompt Templates — Ready to Use

### Single Character (instructor demonstration)
```
[Shot type]. [Environment]. [Instructor: appearance + clothing]. 
[Specific pose or action with physical precision]. 
[Camera movement]. [Lighting]. [Atmosphere/mood].
```

**Example:**
```
"Medium tracking shot. Sunlit open-air yoga shala at the Isha Foundation, 
Velliangiri mountains in the soft-focus background. A woman in her 30s, 
dark hair tied back, white kurta and loose trousers, stands in Tadasana — 
feet grounded, arms lifting slowly from her sides in a wide arc overhead, 
palms pressing together. Camera slowly pushes in on her face. 
Early morning golden light streams in from the east. Serene, focused, alive."
```

### Two Characters — Teacher and Student
```
"[Shot type]. [Environment]. [Character 1: appearance + action]. 
[Character 2: appearance + response action]. 
[Their spatial relationship]. [Camera movement]. [Lighting]. [Mood]."
```

**Example:**
```
"Wide shot then slow push-in. Stone courtyard of the Isha Yoga Center at dawn. 
A female instructor in white, dark hair tied, demonstrates Virabhadrasana — 
strong warrior stance, gaze locked on the horizon. Beside her, three feet away, 
a male student in grey linen, short curly hair, mirrors the pose — 
his body slightly less certain, a gentle tremor in his extended arms. 
Camera moves slowly between them. Mist rolls through the pine trees behind. 
Morning light, cool blue-gold."
```

### Group Class Scene
```
"[Wide camera shot]. [Environment description]. 
[Group description: number, clothing, formation]. 
[Synchronized action]. [One featured individual: appearance + specific moment]. 
[Camera movement]. [Lighting]. [Emotional tone]."
```

**Example:**
```
"Wide establishing shot slowly dolly-in. The main shala of the Isha Foundation, 
wooden pillars, stone floor, open sides facing the misty forest. 
Twelve students in white kurtas stand in neat rows on dark mats — 
they move through Surya Kriya in absolute unison, bodies sweeping through 
21 positions with rhythmic precision. In the third row, a young woman 
with long braided hair closes her eyes between positions, a quiet smile 
crossing her face as breath and movement align. Instructor walks between 
rows, hands clasped behind back. Golden hour flooding through the open walls. 
Total absorption. Peace that is not passivity."
```

---

## 5. What to Avoid

| ❌ Avoid | ✅ Instead |
|---|---|
| `"sad instructor"` | `"instructor with eyes slightly downcast, a long pause before speaking"` |
| `"the characters interact"` | `"she extends her hand, he takes it, both bow their heads"` |
| `"cinematic"`, `"epic"`, `"high quality"` | Describe the elements that CREATE that quality |
| Abstract labels: `"Character A"`, `"Person 1"` | Physical descriptors: `"the woman in white"`, `"the elderly man with white beard"` |
| Keyword lists: `"yoga, zen, peaceful, light"` | Single flowing paragraph with chronological action |
| Overly complex backgrounds (dense brick, fine mesh) | Clean surfaces: stone, wood, earth, sky |
| Simultaneous complex character interaction | Sequential actions: one character acts, then the other responds |

---

## 6. Conditioning Strategy Summary (for `ltx_generate.py`)

When passing multiple images to `LTXConditionPipeline`:

```python
conditions = [
    # 1. Scene/background — lowest strength, establishes environment
    LTXVideoCondition(image=scene_ref,  frame_index=0, strength=0.85),

    # 2. Secondary character (if present)
    LTXVideoCondition(image=char2_img,  frame_index=0, strength=0.85),

    # 3. Primary character — LAST = highest influence
    LTXVideoCondition(image=char1_img,  frame_index=0, strength=1.0),
]
```

**Prompt + Image alignment rule**: The prompt must describe what's **in** the images.  
If the instructor in the image has dark hair and white clothing — say so in the prompt.  
The model uses both signals together; mismatches cause drift.

---

## 7. IC-LoRA Control Models (for advanced character lock)

Lightricks officially released IC-LoRA models for precise control:

| LoRA | Purpose | HuggingFace |
|---|---|---|
| `LTX-Video-ICLoRA-detailer-13b-0.9.8` | Enhances texture + character detail | `Lightricks/LTX-Video-ICLoRA-detailer-13b-0.9.8` |
| `LTX-Video-ICLoRA-depth-13b-0.9.7` | Depth-based structure control | `Lightricks/LTX-Video-ICLoRA-depth-13b-0.9.7` |
| `LTX-Video-ICLoRA-pose-13b-0.9.7` | Pose skeleton control | `Lightricks/LTX-Video-ICLoRA-pose-13b-0.9.7` |
| `LTX-Video-ICLoRA-canny-13b-0.9.7` | Edge-based composition control | `Lightricks/LTX-Video-ICLoRA-canny-13b-0.9.7` |

> **Not yet integrated in our pipeline** — future work for strict identity consistency.

---

## 8. Negative Prompt for Yoga/Clean Scenes

```python
NEGATIVE_PROMPT = (
    "worst quality, inconsistent motion, blurry, jittery, distorted, "
    "folk art, Madhubani, painting, cartoon, illustration, watermark, "
    "text overlay, duplicate persons, identity swap, morphing face, "
    "extra limbs, disfigured, overexposed, neon, dark, harsh shadows"
)
```

---

## 9. Quick Reference Cheat Sheet

```
PROMPT FORMULA:
[Shot type] + [Environment] + [Primary character: age/clothing/feature + action] 
+ [Secondary character if any: same format + response] 
+ [Camera movement] + [Lighting] + [Mood] 
= Under 200 words. Single paragraph. Present tense. Active verbs.

KEY NUMBERS:
- guidance_scale      : 5.0  (dev model, non-distilled)
- guidance_rescale    : 0.7
- decode_timestep     : 0.05
- decode_noise_scale  : 0.025
- image_cond_noise_scale : 0.0  (tightest character lock)
- num_inference_steps : 40
- char condition strength : 1.0
- bg condition strength   : 0.85
```

---

## 10. Implementation: Auto-Inject Character Appearance Into Prompts

**Planned improvement for our pipeline**: When the video_prompt generator writes each scene prompt, it should auto-prepend the character's physical appearance from the DB asset, so prompt + image always align.

```python
# In generate_video_prompt (LLM call), prepend character context:
char_context = f"Primary character: {character.description or character.name}"
final_prompt = f"{char_context}. {scene_prompt}"
```

This ensures the LLM always includes the character's actual appearance in the generated prompt, not a generic description.
