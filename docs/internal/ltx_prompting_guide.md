# Video Prompt Engineering Guide
## LTX-Video 0.9.8 + Seedance 2.0 Techniques Combined

> Sources: Lightricks official README · Seedance 2.0 Prompt Library (ByteDance) · LTX Studio docs  
> Updated: May 2026

---

## PART 1 — The 6-Dimension Framework (from Seedance, applies to LTX-Video)

Write prompts across 6 layers. You don't need all 6 — skip what you don't need.

| # | Dimension | Key Question | Skip? |
|---|---|---|---|
| 1 | **Input** | What reference images/videos are used? | ✓ optional |
| 2 | **Content** | What is happening in the scene? | ❌ required |
| 3 | **Style** | What does it look and sound like? | ✓ optional |
| 4 | **Camera** | How is the scene filmed? | ✓ optional |
| 5 | **Structure** | What is the timeline/sequence? | ✓ optional |
| 6 | **Edit** | What needs to change from a reference? | ✓ optional |

---

### Dimension 1 — INPUT (Reference Assets)

Use `@` to tag reference images. In our pipeline, character and background images are passed as `LTXVideoCondition` objects, so reference them in the prompt with descriptive `@` labels.

**Standard format:**
```
@[Asset A] as [use case], @[Asset B] for [use case]
```

**Examples:**
```
@CharacterImage as the instructor's appearance, @SceneRef as the environment
@Image1 as first frame, @Video1 for camera movement, @Audio1 for background music
```

**For multi-character scenes:**
```
@InstructorImage as the lead teacher's appearance,
@StudentImage1 as the first student (woman in blue),
@StudentImage2 as the second student (man in grey),
@CourtyardImage as the environment
```

---

### Dimension 2 — CONTENT (The Narrative Core)

This describes ONLY the story. No camera, no timeline. What is the actor doing on set?

| Element | What to Write |
|---|---|
| Style | Film / Documentary / Commercial / Animation |
| Character | Who? Identity / Appearance / Current state |
| Environment | Where? Lighting / Time of day / Weather |
| Action | What is happening? How exactly? |
| Mood/Vibe | Calm / Tense / Warm / Reverent |
| Dialogue | What is said? |
| Sound Effects | Ambient sounds, footsteps, crowd |

**Standard format:**
```
[Style]. @[Asset] [Character: appearance] in [Environment] is [Action].
[Character] with [Emotion] says "[Lines]". Background: [Sound Effects].
```

**Example (single character):**
```
Documentary cinematic style. The instructor from @InstructorImage — a woman in her 30s,
dark hair tied back, white linen kurta — stands in the sunlit yoga shala at the Isha Foundation.
She slowly lifts both arms overhead in Tadasana, palms pressing together at the peak.
Her expression is calm and focused. Birdsong in the background. Morning mist drifting.
```

---

### Dimension 3 — STYLE (Look and Sound)

Sets the visual tone and audio mood. Give the video ONE clear identity.

- **Visual style**: Portrait photography / Film / Documentary / Commercial
- **Lighting**: Golden hour / Rembrandt / Soft diffused / Hard shadows
- **Color tone**: Warm amber / Cool blue / Muted earth tones / High contrast
- **Texture**: Film grain / Sharp clarity / Soft glow / Deep focus
- **Atmosphere**: Reverent / Serene / Luxurious / Raw / Ethereal
- **Music**: Soft sitar / Ambient drone / Orchestral / Nature sounds

**Example for Isha Yoga:**
```
Visual Style: Cinematic documentary, warm film photography
Lighting: Golden hour horizontal light, soft god rays through open walls
Color Tone: Warm amber and earth tones, slightly muted, natural
Texture: Subtle film grain, deep focus, rich layering
Atmosphere: Reverent, serene, deeply grounded, unhurried
Music: Soft ambient drone, occasional temple bell, nature sounds
```

---

### Dimension 4 — CAMERA (How It's Filmed)

**RULE: Use rules, not adjectives.**

❌ Don't write: `"cinematic"` `"high quality"` `"epic feel"`  
✅ Do write: `"one-take"` `"slow dolly-in"` `"cut to close-up"`

| Element | Options |
|---|---|
| Shot size | Extreme wide / Wide / Medium / Close-up / Extreme close-up |
| Angle | Eye level / High angle / Low angle / POV / Bird's eye |
| Movement | Static / Pan / Tilt / Dolly in / Dolly out / Tracking / Crane |
| Rules | One-take / No cuts / Match cut / Hard cut |
| Speed | Slow / Steady / Fast / Gradual acceleration |

**Standard format:**
```
From [angle], [movement] to [shot size], using [rules].
```

**Examples:**
```
Wide establishing shot slowly dollying in to medium close-up, one-take, no cuts.

From eye level, slow pan right tracking the instructor as she walks between students.

Cut from wide shot of the courtyard to extreme close-up of hands in Namaste position.

From low angle, tilt up slowly revealing the full height of the yoga shala pillars 
and the misty mountain beyond. Steady, no cuts.
```

---

### Dimension 5 — STRUCTURE (Timeline)

For scenes with multiple beats or character interactions, break into timestamped segments.

**Standard format:**
```
0–Xs: [Content + Camera]
X–Ys: [Content + Camera] (transition note)
Y–Zs: [Content + Camera] (emotional shift or plot point)
Ending: [Freeze / Fade / Linger]
```

**Example — Yoga advertisement (9s at 8fps = 73 frames):**
```
0–3s: Wide shot. Dawn. The Isha Yoga Center courtyard, empty except for one instructor
      in white standing at her mat, eyes closed. Mist drifts through pine trees.
      Camera: Wide establishing, slowly push in.

3–6s: The instructor opens her eyes and begins Surya Kriya — arms sweeping wide overhead
      in the first of 21 steps. Her body is precise, unhurried.
      Camera: Cut to medium shot, then slow track right alongside her.

6–9s: Extreme close-up of her feet grounding into the stone floor.
      Then cut wide to reveal 12 students behind her, all moving in perfect unison.
      Camera: Fast cut, then pull back dramatically to reveal the group.

End: Hold on wide shot. Golden light floods the courtyard.
     Fade slowly to black.
```

---

### Dimension 6 — EDIT (Modifying Existing Videos)

For when you want to change something from a reference video.

| Type | Use |
|---|---|
| Extend | Add more seconds continuing from the last frame |
| Partial Edit | Change specific element (hair, clothing, product) |
| Replace | Swap character or object, keep scene |
| Re-plot | Keep characters and environment, rewrite story |

**Standard format:**
```
[Action] @Video1 ([Extend by Xs / Re-plot / Replace A with B]),
[New details], while keeping the original [style/camera/character].
```

---

## PART 2 — Multi-Character Prompting

### The Core Rule

Distinguish characters by **distinct visible properties**, never abstract labels:

| ❌ Avoid | ✅ Use |
|---|---|
| `"Character A"` | `"the instructor in white with dark hair"` |
| `"Person 1 and Person 2"` | `"the tall student in grey linen"` |
| `"they interact"` | `"she demonstrates; he mirrors her stance, three feet to her right"` |

---

### Multi-Character Prompt Structures

#### Structure 1 — Two Characters, Sequential Action

```
[Shot type]. [Environment]. [Character 1: appearance] [action].
Then [Character 2: appearance] [response action].
[Their spatial relationship]. [Camera]. [Lighting].
```

**Example — Teacher + Student:**
```
Medium shot, slow push-in. Stone courtyard of the Isha Foundation at dawn, mist rolling through tall pines.
A female instructor in white kurta, dark hair tied back, demonstrates Virabhadrasana —
warrior stance, strong and rooted, gaze locked on the horizon.
Beside her, three feet to the right, a male student in grey linen, short curly hair,
mirrors the pose — his extended arms trembling slightly as he finds balance.
Camera tracks between them. Golden morning light from the east.
```

#### Structure 2 — Group Scene, One Featured Individual

```
[Wide shot]. [Environment]. [Group: number, clothing, formation, synchronized action].
[Single individual from group: appearance + specific moment].
[Camera movement]. [Lighting]. [Tone].
```

**Example — Class at Isha:**
```
Wide establishing shot slowly dollying in. Main shala of the Isha Foundation —
open stone walls, wooden pillars, forest visible beyond.
Twelve students in white kurtas stand in neat rows on dark mats,
moving through Surya Kriya in perfect unison, bodies sweeping through each position.
In the third row, a young woman with long braided hair closes her eyes between positions,
a quiet smile crossing her face as breath and movement align.
The instructor, white robes, hands clasped behind back, walks slowly between rows without speaking.
Camera pulls back further to reveal the full courtyard and misty mountains beyond.
Pure golden hour light flooding through the open walls.
```

#### Structure 3 — Complex Multi-Character (from Seedance example, adapted)

This is the most powerful structure. Note how each character has appearance + reference + explicit action:

**Original Seedance example (anime, 3 reference images):**
```
The game features a colorful manga style, reminiscent of Jujutsu Kaisen.
The positioning of the two characters and their surrounding environment are shown in @Image1.
First shot: Yuuta Otsukoku (@Image3) stands amidst the ruins, looking at Sukuna (@Image2),
and coldly utters: "Domain unfolds." Screen turns pure black, displaying four large white characters.
Second shot: Camera zooms out, revealing a large amount of flowing blue magical energy.
Countless dilapidated crosses and swords rise from the ground (@Image1).
Third shot: One of the swords automatically flies into Otsukoku's hand, releasing blue magical energy.
```

**Adapted for our Yoga pipeline (3 reference images):**
```
Cinematic documentary style. The positioning of the instructor and students is shown in @SceneRef.
First shot: The senior instructor (@InstructorImage) stands at the front of the shala,
eyes closed, as the morning bell rings once. She opens her eyes and says quietly: "Begin."
Second shot: Twelve students (@StudentGroupImage) rise in unison from seated position,
flowing into the first movement of Surya Kriya — twelve bodies, one breath.
Third shot: Camera pushes slowly toward the instructor's face —
her expression is not one of authority, but of deep participation.
```

#### Structure 4 — Timestamped Multi-Character Drama

This is the most detailed and controllable format. From the Seedance cat drama example:

**Original (4 reference characters, 15 seconds):**
```
0–4s: On a cold rainy night, a white cat sits by a trash can. Her fur is wet and she looks weak
and heartbroken. She looks toward a luxury car nearby. Inside the car, a blue cat gently feeds
tuna to a Siamese cat in his arms, while the Siamese cat enjoys it proudly.
The white cat's eyes fill with tears as she realizes she has been betrayed.
Music: sad piano with rain sounds.

4–8s: The white cat suddenly stands up in the rain and her eyes change from weak to cold.
A lightning flash cuts to a luxury dressing room. Now the white cat is clean and elegant.
She wears a silk robe and puts on a pearl necklace while looking into the mirror
with a quiet smile of revenge. Music shifts to epic beats and orchestra.

8–11s: In a bright ballroom, the white cat enters with a black cat prince.
She wears a purple lace dress and looks confident. The blue cat sees her from afar
and freezes with regret. The Siamese cat notices his reaction and becomes angry and jealous.
Music: elegant orchestral waltz.

11–13s: The Siamese cat walks toward the white cat with a glass of wine and pretends to slip
to spill it on her. The white cat quickly avoids the wine and slaps the Siamese cat.
The Siamese cat falls to the floor and the glass breaks while the crowd gasps.

13–15s: The white cat calmly looks down, then turns away and walks out with the black cat prince.
Guests move aside for her while the blue cat watches with regret.
The Siamese cat sits on the floor in shame. Music rises into a powerful victory theme.
```

**What makes this work:** Each timestamp specifies environment + every character + their action + camera + music. Nothing is vague.

---

## PART 3 — 7 Video Style Templates (Verbatim from Seedance Library)

### 1. Cinematic Mastery
```
Cinematic film style. ___ (main character) in ___ (location).
Camera ___ (camera movement).
Lighting ___ (lighting style).
___ (main action happening).
Atmosphere: ___ (fog / rain / dramatic light).
End with ___ (epic final shot).
```

**Real working example:**
```
The camera follows a man in black fleeing rapidly, pursued by a crowd.
The shot transitions to a side-tracking view. In panic, the man crashes into a fruit stand
by the roadside, quickly scrambles up, and continues running amidst the chaotic sounds of the crowd.
```

### 2. Anime & Animation
```
Anime style animation. ___ (character description).
Location: ___ (fantasy place / city / battlefield).
The character ___ (action or attack).
Energy / effects: ___ (light, magic, particles).
End with ___ (dramatic anime pose).
```

### 3. AI Short Series (Multi-Character Drama)
```
___ style. ___ (character) in ___ (place / time / mood).
___ (what happens / action).
___ (extra emotion or atmosphere).
Dialogue:
___ says, "___."
___ replies, "___."
End with ___ (final shot / subtitle / fade to black).
```

### 4. Commercial / Advertisement
```
Luxury commercial style.
A ___ (product) placed on ___ (surface / environment).
Camera ___ (slow rotation / macro shot).
Lighting ___ (soft light / dramatic light).
The product ___ (main highlight moment).
End with ___ (brand style final shot).
```

**Real working example:**
```
The figure within the painting wears a sheepish expression, glancing furtively left and right
before leaning out of the frame. Swiftly, they reach out, grab a can of cola, and take a sip,
their face lighting up with an expression of pure satisfaction. Just then, the sound of
approaching footsteps is heard; the figure in the painting hurriedly places the cola back.
At that moment, a Western cowboy picks up the glass containing the cola and walks away.
Finally, the camera pushes forward; the screen slowly fades to pure black background,
illuminated solely by a spotlight shining down on the canned cola.
Artistic subtitles appear: "Cola — A Taste You Can't Miss!"
```

### 5. Viral / Social Media
```
Social media viral video style.
___ (character or animal) in ___ (normal situation).
Suddenly ___ (unexpected event).
Reaction: ___ (funny or exaggerated reaction).
End with ___ (meme moment).
```

### 6. Realistic Vlog / UGC
```
UGC smartphone video style.
___ (person) recording themselves in ___ (daily place).
They talk about ___ (product / experience).
Natural lighting. Slight handheld camera movement.
End with ___ (casual closing moment).
```

**Real working example (just 16 words!):**
```
engaging ugc ad video of a young white woman in her bathroom talking about
how she uses the reset undereye patches putting them on.
```

### 7. Creative VFX
```
Experimental VFX style.
___ (object or character) made of ___ (particles / light / liquid).
The object ___ (transforms / explodes / reforms).
Visual effects: ___ (particles / energy waves / abstract motion).
End with ___ (final abstract visual).
```

---

## PART 4 — Isha Yoga Prompt Toolkit

Ready-to-use prompts optimised for our pipeline:

### Scene: Opening (Dawn Arrival)
```
Wide establishing shot, slowly dollying in. Dawn at the Isha Yoga Center, Coimbatore.
The Dhyanalinga dome is visible through morning mist. Stone courtyard, open shala,
wooden pillars casting long shadows.
The instructor (@InstructorImage) — a woman in white kurta, dark hair tied back —
walks barefoot across the stone, unrolling a dark mat in silence.
She sits, closes her eyes, takes one long breath.
Camera: Wide to medium, one continuous push. No cuts.
Lighting: Pre-dawn blue-grey, gradually warming to gold.
Sound: Single temple bell, birdsong, distant forest.
```

### Scene: Surya Kriya (Group Practice)
```
0–3s: Wide shot. Twelve students in white, standing in rows, facing east.
      The instructor at the front lifts both arms slowly overhead — the group follows.
      Camera: Wide, slowly pulling back to reveal the full shala.

3–6s: Medium shot tracking the instructor's precise movement through the first positions.
      Arms sweeping, spine lengthening, breath visible in the cool air.
      Camera: Track alongside, eye level.

6–9s: Cut to close-up of hands in Namaste, then quick cut to feet grounding on stone.
      Then wide again — the whole group moving in perfect unison.
      Camera: Match cut from close-up to wide.

Lighting throughout: Golden hour warming gradually. Film grain texture.
```

### Scene: Transformation Moment (Student)
```
Medium shot. A young student (@StudentImage) — short curly hair, grey linen —
kneeling at his mat in the Isha shala. He is struggling with a seated forward fold,
breath shallow, face tight with effort.
Then something releases — he exhales long, his spine curls forward gently,
forehead approaching the mat. His face changes: the struggle drains away.
A quiet revolution, visible only in the softening of his jaw.
Camera: Slow push-in from medium to close-up on his face. One-take.
Lighting: Warm sidelight. Slight film grain.
```

### Scene: Closing / CTA
```
The final frame: all twelve students in Savasana, bodies still on their mats,
the entire shala bathed in golden afternoon light.
The instructor (@InstructorImage) walks slowly between them, not speaking.
She stops at the edge of the shala, looks out at the Velliangiri mountains.
Camera: Wide shot, very slowly crane up until we see the full courtyard from above.
Hold five seconds. Then fade to black.
Text fades in: "Isha Hatha Yoga. Classical Yoga. Transmitted with integrity."
"ishafoundation.org"
```

---

## PART 5 — Quick Reference

### Prompt Quality Checklist
- [ ] Present tense, active verbs
- [ ] Characters described by appearance, not abstract labels
- [ ] Camera described by rules, not adjectives ("dolly in" not "cinematic")
- [ ] Under 200 words for single scene
- [ ] Timestamped if multi-beat scene
- [ ] Sound/music noted
- [ ] Environment described with surface, depth, time of day

### Negative Prompt (copy-paste)
```
worst quality, inconsistent motion, blurry, jittery, distorted, folk art,
Madhubani, painting, cartoon, illustration, watermark, text overlay,
duplicate persons, identity swap, morphing face, extra limbs, disfigured,
overexposed, harsh shadows, static, low resolution
```

### Key Parameters (copy-paste)
```python
guidance_scale=5.0          # dev non-distilled model
guidance_rescale=0.7        # anti-overexposure
decode_timestep=0.05        # VAE micro-denoise
decode_noise_scale=0.025    # decode noise
image_cond_noise_scale=0.0  # tightest character lock
num_inference_steps=40      # quality generation
```

### Condition Stacking Order
```python
conditions = [
    LTXVideoCondition(image=scene_bg,   frame_index=0, strength=0.85),  # environment first
    LTXVideoCondition(image=char2_img,  frame_index=0, strength=0.85),  # secondary char
    LTXVideoCondition(image=char1_img,  frame_index=0, strength=1.0),   # hero char LAST
]
```
