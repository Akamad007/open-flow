# Save Soil ad — scene-bleed analysis (project `e4c13437`)

**TL;DR:** Scenes 2, 3, and 4 all render almost the same shot — Sadhguru walking
from behind on the cracked field. Three independent bugs combine to produce this:

1. **Strict character-name match** drops scenes 0 and 3 from the action-stills
   pipeline (their LLM-emitted names "Farmer" / "Child" don't match the canonical
   "Farmer (unseen, hands only)" / "Child (unseen, hands only)" with parens).
2. **Cascading last-frame conditioning** when a scene has no action stills.
   Scenes with no character-conditioning rely entirely on `--condition-image`
   (the last frame of the previous scene), which propagates content forward
   indefinitely.
3. **`video_prompt` hallucinates Sadhguru into scenes that aren't about him.**
   Scene 3's `video_prompt` opens with "The adult South Asian man with medium
   warm brown skin… white turban… white robe kneels…" even though the scene's
   `visual_summary` is "earthworms move and a child's hand presses a sapling
   into rich, dark earth." The prompt-generation stage carried Sadhguru
   description forward by template inertia.

---

## What was supposed to happen

| Scene | Duration | Visual summary | Character |
|------:|----------|----------------|-----------|
| 0 | 6s | Farmer's dusty hands sifting parched, cracked soil | Farmer (hands only) |
| 1 | 6s | Sadhguru walks slowly across the dying field | Sadhguru |
| 2 | 6s | Sadhguru kneels and opens hands over cracked earth | Sadhguru |
| 3 | 6s | Earthworms move; child's hand presses sapling into rich earth | Child (hands only) |
| 4 | 6s | Sadhguru faces camera, then end-card with logo | Sadhguru |

## What actually rendered (sampled at start / mid / end of each scene's MP4)

| Scene | Frame 0 | Frame 30 | Frame 60 | Visual reality |
|------:|---------|----------|----------|----------------|
| 0 | empty cracked field | empty cracked field | hands sifting soil | OK — environment-led, hand action emerges late |
| 1 | one hand dropping dust | hand+robe split | robe walking | scene 0 content bleeds in; switches to Sadhguru mid-shot |
| 2 | similar robe walking | similar robe walking | robe walking | basically scene 1 continued |
| 3 | robe walking (no child, no worms) | robe walking | robe walking | wrong content — should be earthworms+child |
| 4 | robe walking | robe walking | robe walking | wrong content — should be Sadhguru facing camera |

All scenes 2-4 also have **garbled subtitle text** burned into the frame —
LTX hallucinating English text from the negative-prompt cue.

---

## Root cause #1 — character-name fuzzy match was missing at run time

**Evidence (celery log):**
```
[2026-05-05 00:06:17] Scene 0 references unknown character 'Farmer' — skipping link
[2026-05-05 00:06:17] Scene 3 references unknown character 'Child' — skipping link
```

DB confirms: scenes 0 and 3 have **0 characters** linked.
Project has these character rows:
```
Sadhguru
Farmer (unseen, hands only)
Child (unseen, hands only)
```

The scene_planner LLM emitted shortened forms `"Farmer"` and `"Child"`. The
strict lowercase-exact match in `_build_lookups` ([scene_planning.py:35](backend/app/orchestration/stages/scene_planning.py#L35))
failed because the canonical names contain `(unseen, hands only)`.

**Consequence:** scenes 0 and 3 had `primary_char = None`, so
`generate_all` ([action_stills.py:246](backend/app/agents/image_pregen/action_stills.py#L246))
skipped them. No action stills exist on disk for scenes 0 or 3 — confirmed:
```
$ ls scene_actions/.../scene_000* 2>/dev/null  # empty
$ ls scene_actions/.../scene_003* 2>/dev/null  # empty
```

**Fix:** fuzzy resolver added at
[scene_planning.py:35-94](backend/app/orchestration/stages/scene_planning.py#L35-L94)
*after* this run. It tries exact → paren-stripped → substring. Verified working:
`'Farmer' → <Farmer (unseen, hands only)>`. Will only take effect on the next run.

---

## Root cause #2 — cascading last-frame conditioning when stills are absent

[scene_video.py:104-121](backend/app/orchestration/stages/scene_video.py#L104-L121)
selects the conditioning input by priority:

```
if last_frame:    return last_frame, no char, no bg, no actions  ← takes over completely
elif background: return background, char, bg, actions
elif actions/char: ...
else: scene_ref or none
```

When a scene has **no action stills** (scenes 0 and 3), the only available
conditioning is the last frame of the previous scene's video, which **fully
overrides** character / background / action conditioning per the rules above.

The chain in this run:
```
scene 0 → scene 1: last_frame = frame 60 of scene 0 (hands sifting soil)
                   → scene 1 starts with hand visible, transitions to robe
scene 1 → scene 2: last_frame = robe walking
                   → scene 2 looks the same
scene 2 → scene 3: last_frame = robe walking; scene 3 has NO action stills
                   → scene 3 inherits "Sadhguru robe walking" entirely
scene 3 → scene 4: last_frame = robe walking; scene 4 has stills BUT
                   `_select_conditioning` returns last_frame ONLY (drops actions)
                   → scene 4 also looks like robe walking
```

**This is the dominant cause of "scenes 2-4 all look the same".**

**Possible fixes:**

- A. When scene has explicit action stills, don't let `last_frame` override them
  — pass both, let LTX weight via `--scene-action-images` strength.
- B. When scene has no character link AND scene description differs strongly
  from the previous scene's, drop the last-frame conditioning entirely (use
  bg + scene_ref instead).
- C. Add a "soft anchor" frame: composite the new scene's expected character
  portrait onto the location plate and use *that* as the condition image
  instead of the previous video's last frame.

Option A is the smallest change and likely the right first move.

---

## Root cause #3 — `video_prompt` hallucinates Sadhguru into off-topic scenes

The visual_director's `video_prompt` for scene 3 reads:

> "Cinematic documentary transition. The adult South Asian man with medium warm
> brown skin, deep-set steady eyes, dark eyebrows, a neatly wrapped white turban,
> and a flowing layered white robe **kneels on**…"

This is *Sadhguru's* description, copy-pasted verbatim from scene 2's prompt.
The scene's `visual_summary` is "earthworms move and a child's hand presses a
sapling into rich, dark earth" — no Sadhguru required. Yet the prompt opens
with him.

Scene 3's `camera_angle` is also wrong: *"ground-level medium-wide shot then
tighter medium shot, **Sadhguru centered and fully visible**"* — Sadhguru
explicitly named in a scene that shouldn't have him.

**Why this happens:** the visual_director ([visual_director.py](backend/app/agents/visual_director.py))
generates each scene's prompt with the full character list as context. Without
explicit instruction to *omit* characters who aren't in this scene's
`character_names`, the LLM defaults to the most prominent character it knows.

**Fix:** in the visual_director user prompt, pass *only the characters linked
to THIS scene* (not the full project list), and add a hard rule: "Do not
mention any character not in this scene's character_names list."

---

## Root cause #4 — text/subtitles burning into frames

Frames from scenes 2-4 show garbled text overlays (`I sturve us aymath`,
`a vrysir s`, etc.). The LTX prompt's `negative_prompt` should reject text
overlays, but evidently doesn't strongly enough — and the visual_director's
`negative_prompt` field already includes "text, subtitles, watermark…", so
this is a model-level issue.

**Fix candidates:**
- Strengthen negative prompt: *"text, subtitles, captions, watermark, logo,
  letters, words, alphabet characters, English text, gibberish text"*
- Lower CFG / guidance scale on LTX (text is often a guidance artifact)
- Crop final video to remove burned-in subtitle band (last resort)

---

## Why the previous run's "Sadhguru morphs into child" doesn't appear here

Different bug, same family. In the previous project, scene 4 had `Child` linked
(somehow), so action stills DID generate but used scene 3's last still
(Sadhguru) as img2img init → identity bleed.

In *this* run, character-name match failed entirely → no stills → fully
last-frame-driven → all scenes 3-4 are simply scene 2's visual continuation.
Same end result (last 2-3 scenes look identical) via a different path.

---

## Action plan — status

| # | Fix | File | Status |
|---|-----|------|--------|
| 1 | Fuzzy character/location name match — exact → paren-stripped → substring | [scene_planning.py:35-94](backend/app/orchestration/stages/scene_planning.py#L35-L94) | ✅ **Done** |
| 2 | Don't let `last_frame` silently override action stills/character — only fall back to it when nothing else is available | [scene_video.py:104-130](backend/app/orchestration/stages/scene_video.py#L104-L130) | ✅ **Done** |
| 3 | Visual director: hard scope rule — only describe characters in THIS scene's `character_names`; never carry characters across scenes | [visual_director.py:85-95](backend/app/agents/visual_director.py#L85-L95) | ✅ **Done** |
| 4 | Cross-scene char-change reset — when scene N's character differs from scene N-1's, drop the img2img chain so still 0 starts from new char's portrait | [action_stills.py:163-170](backend/app/agents/image_pregen/action_stills.py#L163-L170) | ✅ **Done** |
| 5 | Location consolidation — story_analyst targets 1-3 locations max for short ads; scene_planner reuses; defensive backstop inherits prev location when null/unknown | [story_analyst.py:30](backend/app/agents/story_analyst.py#L30), [scene_planner.py:75-76](backend/app/agents/scene_planner.py#L75-L76), [scene_planning.py:117-128](backend/app/orchestration/stages/scene_planning.py#L117-L128) | ✅ **Done** |
| 6 | Skip action stills for scenes with no linked character (instead of silently falling back to "first project char" — that produced Sadhguru-shaped earthworms) | [action_stills.py:43-52](backend/app/agents/image_pregen/action_stills.py#L43-L52) | ✅ **Done** |
| 7 | Tighten negatives in scene_action stills: "off-center, edge of frame, neutral pose, text, subtitles, watermark…" | [scene_action_portrait.txt](backend/app/prompts/scene_action_portrait.txt) | ✅ **Done** |
| 8 | Visual director `max_tokens` 1500→3500 + JSON-repair fallback so a truncated response recovers earlier fields instead of hard-failing | [visual_director.py:164](backend/app/agents/visual_director.py#L164), [openai_provider.py:17-65](backend/app/providers/llm/openai_provider.py#L17-L65) | ✅ **Done** |
| 9 | DB enum migration `scene_action_seq` so the new per-second asset type is allowed by Postgres | [alembic a1b2c3d4e5f6](backend/alembic/versions/a1b2c3d4e5f6_add_scene_action_seq_asset_type.py) | ✅ **Done** |
| 10 | Bg-removal saves transparent canonical PNG + opaque sidecar — LTX gets character cutouts as multi-image conditioning, never opaque mismatched scenes | [action_stills.py:107-130](backend/app/agents/image_pregen/action_stills.py#L107-L130), [scene_compositor.py](backend/app/utils/scene_compositor.py) | ✅ **Done** |
| 11 | Strengthen LTX negative prompt against burned-in text artifacts (gibberish English text overlays) | [visual_director.py](backend/app/agents/visual_director.py) negative_prompt default | ⏳ **Open** — currently relies on the LLM-emitted negative; consider a hardcoded baseline appended at the LTX provider level |
| 12 | Per-scene visual-distinctiveness instruction — force scene_planner to differentiate consecutive scenes by camera/time/subject if action is similar | [scene_planner.py](backend/app/agents/scene_planner.py) | ⏳ **Open** — only matters if scenes still feel repetitive after fixes #1-#10 |

## Things deliberately NOT done (rolled back as over-engineering)

- 7-framing system (`extreme_close_up`…`extreme_wide`) per-still dimension/strength manipulation, `is_major_framing_jump` chain reset on extreme_close_up, `subject_position` field, framing prefix injection — all of this added prompt bloat and made stills unpredictable. Reverted to stable defaults: 768×1024, strength 0.35 (first still) / 0.55 (rest), single seed pattern. The `_framing.py` module is deleted.
- `iterate_pipeline.py` autonomous improvement loop and `measure_project.py` scoring — useful tooling but not in active use; left in `scripts/` if you want them later.

## Verification

After all fixes, the next e2e run should produce:

- ≤3 location backgrounds (consolidation rule)
- 0 scenes with `character_names` but `scene.characters` empty (fuzzy match)
- 0 scenes whose `video_prompt` mentions a character not in `character_names` (scope rule)
- Distinct conditioning per scene — no "robe walking" repetition (last_frame no longer dominates)
- Cross-scene char changes (Sadhguru → Child) reset the img2img chain (no morphing identity)

If issues remain, focus first on items #11 (text artifacts in LTX output) and #12 (consecutive-scene distinctiveness), both of which are currently open.

## Reproduction commands

```bash
# Sample frames per scene
PROJ=e4c13437-790d-42a9-bdef-5bed6566873a
BASE=/home/akash/PycharmProjects/video-app/backend/storage
for SCN in 000 001 002 003 004; do
  VID=$(ls $BASE/videos/$PROJ/scene_${SCN}_*.mp4 | head -1)
  ffmpeg -y -i "$VID" -vf "select=eq(n\,0)+eq(n\,30)+eq(n\,60),scale=320:-1" \
    -frames:v 3 -vsync 0 /tmp/scene_${SCN}_%d.png
done

# Inspect DB
docker exec video-app-db-1 psql -U storyvideouser -d storyvideo -c \
  "SELECT s.order_index, s.location_id, COUNT(sc.character_id) AS chars \
   FROM scenes s LEFT JOIN scene_characters sc ON sc.scene_id=s.id \
   WHERE s.project_id='$PROJ' GROUP BY s.id ORDER BY s.order_index;"
```
