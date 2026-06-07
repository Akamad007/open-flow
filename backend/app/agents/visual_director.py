"""Visual Director Agent — generates the cinematic video_prompt for one
or many scenes in a single LLM call.

After the LLM returns, the structured output is validated; on failure the
agent re-prompts with the failed checks until it passes (≤2 retries).

`run()` — single-scene path (used as the fallback for scenes that failed
validation inside a batch).
`run_batch()` — N-scenes-per-call path used by the orchestration stage.
"""

from typing import Any

from app.agents.base import AgentResult, BaseAgent
from app.agents.scene_prompt_validator import WORD_CAP, validate_scene_prompt

MAX_RETRIES = 5
BATCH_SIZE = 50


def _truncate_to_word_cap(text: str, cap: int = WORD_CAP) -> str:
    """Last-resort: hard-truncate a prompt to the word cap at the nearest
    sentence boundary <= cap. Used only when MAX_RETRIES LLM passes all
    overshot — guarantees no over-cap prompt ever reaches Wan22's UMT5 cliff."""
    words = text.split()
    if len(words) <= cap:
        return text
    head = " ".join(words[:cap])
    # Backtrack to last sentence end (., !, ?) so the prompt doesn't cut
    # mid-thought. If no sentence break in last 40 words, just hard-cut.
    for sep in (". ", "! ", "? "):
        cut = head.rfind(sep)
        if cut > 0 and (cap - len(head[:cut].split())) < 40:
            return head[:cut + 1].strip()
    return head.strip()


def _adjacent_block(prev: dict | None, nxt: dict | None) -> str:
    parts: list[str] = []
    if prev:
        parts.append(f"- Previous scene visual: {prev.get('visual_summary', 'N/A')}")
        if prev.get('video_prompt'):
            parts.append(f"- Previous scene prompt: {prev['video_prompt'][:300]}...")
    if nxt:
        parts.append(f"- Next scene visual: {nxt.get('visual_summary', 'N/A')}")
    return "\n".join(parts)


def _format_chars(chars: list[dict], image_provided: bool = False) -> str:
    if not chars:
        return "  (no characters)"
    out = []
    for c in chars:
        if image_provided:
            # Identity is locked by the reference image fed to the video model.
            # Listing appearance here invites the LLM to write it into the prompt.
            out.append(
                f"  - {c.get('canonical_name', 'Unknown')}  "
                f"(reference image provided — use the name only)"
            )
        else:
            out.append(
                f"  - {c.get('canonical_name', 'Unknown')}:\n"
                f"    Physical: {c.get('physical_description', 'N/A')}\n"
                f"    Clothing: {c.get('clothing_description', 'N/A')}\n"
                f"    NOTE: depict with the exact skin tone and ethnicity above."
            )
    return "\n".join(out)


_IMAGE_PROVIDED_RULE = (
    "⚠️ CHARACTER REFERENCE IMAGE PROVIDED — KEEP A SHORT IDENTITY TAG IN THE PROMPT.\n"
    "The video model is conditioned on a starting-frame image, but Wan22's\n"
    "UMT5 text encoder still steers identity on each per-second beat. With\n"
    "NO mention of the character in the text, the look drifts over the scene\n"
    "(face slips, color shifts, accessories vanish). With a FULL appearance\n"
    "description it fights the image and produces double-rendered identity.\n"
    "The sweet spot is a SHORT identity tag — 5–9 words anchoring the\n"
    "1–2 most distinctive traits — repeated on every beat.\n"
    "- DIM 2 CONTENT line: \"[Style]. [Name] the [short-tag] in [Environment]\n"
    "  [Action].\" Example tags:\n"
    "    \"Bal Krishna the chubby sky-blue toddler with peacock-feather topknot\"\n"
    "    \"Tom the lanky blue-grey cat\"  \"Brushy the bright blue toothbrush mascot\"\n"
    "- Repeat the same short-tag on EVERY per-second beat — never collapse to\n"
    "  pronoun or name-only (\"she does X\", \"Tom does X\"). Always include the\n"
    "  color/material anchor (\"sky-blue Krishna\", \"blue-grey Tom\").\n"
    "- DO NOT add new appearance details not already in the canonical\n"
    "  character block — don't invent clothing/colors. Pick the 1–2 most\n"
    "  distinctive traits and repeat them verbatim.\n"
    "- Forbidden: paragraphs of description, ethnicity, height/build,\n"
    "  full clothing breakdown, facial-feature lists. Keep the tag tight.\n"
)

_CHAR_NO_IMAGE_RULE_HEAD = (
    "⚠️ NO REFERENCE IMAGE FOR THE CHARACTER(S) — describe each character's\n"
    "appearance EXPLICITLY in DIM 2 and every per-second beat. The text\n"
    "prompt is the ONLY identity signal the video model gets, so writing\n"
    "just the name (\"Jerry darts behind the chair\") gives the model nothing\n"
    "to render — it must read \"Jerry the tiny mustard-brown mouse with\n"
    "round black eyes darts behind the chair\".\n"
    "- LEAD each character with their dominant color/material + size +\n"
    "  species/role (e.g. \"Tom the lanky blue-grey cat with a pink nose\";\n"
    "  \"Jerry the tiny mustard-brown mouse with round black eyes\";\n"
    "  \"Brushy the bright blue toothbrush mascot with big white eyes\").\n"
    "- Repeat the distinguishing tag in EVERY per-second beat — never\n"
    "  collapse to a pronoun, name-only reference, or \"the figure\".\n"
    "- Use the Physical / Clothing fields from the character block above\n"
    "  verbatim — don't invent new traits, but DO surface them prominently.\n"
)
_MULTI_CHAR_POSITION_BLOCK = (
    "- MULTIPLE CHARACTERS — place each character explicitly in frame:\n"
    "  screen position (left / right / center / foreground / mid-ground /\n"
    "  background) AND position relative to the other (\"Tom on the left,\n"
    "  Jerry on the right perched on the counter edge\"). Repeat the\n"
    "  position every per-second beat so staging doesn't drift.\n"
)


def _critique_block(critique_feedback: dict | None, scene_index: int) -> str:
    if not critique_feedback:
        return ""
    issues = critique_feedback.get("issues", [])
    suggestions = critique_feedback.get("suggestions", [])
    scene_issues = [i for i in issues
                    if i.get("scene_index") == scene_index or i.get("scene_index") is None]
    if not (scene_issues or suggestions):
        return ""
    out = "\n\n⚠️ CRITIQUE FEEDBACK — YOU MUST ADDRESS THESE ISSUES:\n"
    for i in scene_issues:
        out += f"- [{i.get('severity','?').upper()}] {i.get('issue_type','')}: {i.get('description','')}\n"
    if suggestions:
        out += "\nSUGGESTIONS:\n" + "\n".join(f"- {s}" for s in suggestions) + "\n"
    return out + "\nRevise the prompt to FIX these specific issues.\n"


def _per_second_block(per_second_plan: list[dict], duration: float) -> str:
    if per_second_plan:
        lines = "\n".join(
            f"    {b.get('second','?')}s: {b.get('action','')} | camera: {b.get('camera','')}"
            for b in per_second_plan
        )
        return f"\nPER-SECOND PLAN (from scene planner):\n{lines}\n"
    return f"\nPER-SECOND PLAN: (write one beat per second for all {int(duration)} seconds)\n"


def _correction_hint(report_errors: list[str]) -> str:
    if not report_errors:
        return ""
    over_cap_line = ""
    for e in report_errors:
        # Validator format: "video_prompt has 273 words; cap is 250"
        if "words; cap is" in e:
            try:
                wc = int(e.split("has")[1].split("words")[0].strip())
                over_by = wc - WORD_CAP
                over_cap_line = (
                    f"\n  → You wrote {wc} words. Hard limit is {WORD_CAP}. "
                    f"You MUST cut at least {over_by + 5} words (target ≤ {WORD_CAP - 5}). "
                    f"Wan22's UMT5 encoder truncates beyond ~330 tokens — over-cap prompts "
                    f"silently lose the last beats. Shorten per-second beats, drop redundant "
                    f"style adjectives, but KEEP the character's identity tag on every beat."
                )
            except (ValueError, IndexError):
                pass
    return ("\n\n⚠️ PREVIOUS ATTEMPT FAILED VALIDATION — fix these and re-emit:\n"
            + "\n".join(f"  - {e}" for e in report_errors)
            + over_cap_line
            + "\n")


def _format_product_block(product: dict | None, role: str | None) -> str:
    if not product:
        return "  (no product in this scene)"
    role_phrasing = {
        "hero": "extreme close-up on the product, character's hand entering frame from one side",
        "holding": "the character grips/holds the product naturally during the action",
        "background": "the product sits in frame on a counter/shelf/surface, clearly visible",
    }.get((role or "holding").lower(), "the character grips/holds the product naturally during the action")
    return (
        f"  - {product.get('canonical_name', 'product')}:\n"
        f"    Visual: {product.get('physical_description', 'N/A')}\n"
        f"    Marks : {product.get('brand_marks', 'N/A')}\n"
        f"    Colors: {product.get('color_palette', 'N/A')}\n"
        f"    Role  : {role or 'holding'}\n"
        f"    Beat  : {role_phrasing}\n"
        f"    NOTE  : depict by VISUAL DESCRIPTION ONLY — never write the brand name, "
        f"\"logo\", \"label text\", \"wordmark\" or any negative-prompt-banned term."
    )


def _build_user_prompt(scene: dict, characters: list[dict], all_characters: list[dict],
                       previous_scene: dict | None, next_scene: dict | None,
                       story_summary: str, pacing_notes: str, style_lock: str,
                       critique_feedback: dict | None, validator_errors: list[str],
                       product: dict | None = None, product_role: str | None = None) -> str:
    duration = scene.get('duration_seconds', 6.0)
    n_sec = int(duration)
    scene_index = scene.get("order_index", 0)
    relevant = [c for c in characters
                if c.get("canonical_name", "") in scene.get("character_names", [])]
    image_provided = bool(scene.get("character_image_provided")) and bool(relevant)
    image_provided_block = (
        f"\n{_IMAGE_PROVIDED_RULE}\n" if image_provided else ""
    )
    char_no_image_block = ""
    if relevant and not image_provided:
        head = _CHAR_NO_IMAGE_RULE_HEAD
        if len(relevant) > 1:
            head = head + _MULTI_CHAR_POSITION_BLOCK
        char_no_image_block = f"\n{head}\n"

    return f"""Generate a structured cinematic video prompt for this scene using the 6-Dimension Framework.

🎯🎯🎯 WORD BUDGET — RICHER IS BETTER 🎯🎯🎯
`video_prompt` TARGET: **210-250 words**. Validator REJECTS over 320.
Use the room: pack each character bible (~60-90w) and setting line (~30-45w) with concrete sensory nouns. Each per-second beat ~16-20w with one sensory detail (light, fabric, dust, breath).
Sparse prompts (<170w) render generic; richer prompts with specific nouns render sharper.
Be specific, NOT padded — noun-phrases > adjective-stacks. Cut articles and hedges, but add concrete sensory detail.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STORY CONTEXT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Summary  : {story_summary or 'N/A'}
Pacing   : {pacing_notes or 'N/A'}

⚠️ STYLE LOCK (must be reflected verbatim in dim_style and the assembled video_prompt — DO NOT paraphrase):
  "{style_lock or 'cinematic documentary, natural lighting, warm earth tones, shallow depth of field, film grain, reverent mood'}"

SCENE INFO
- Index    : {scene_index}
- Duration : {duration}s
- Purpose  : {scene.get('scene_purpose', 'N/A')}
- Visual   : {scene.get('visual_summary', 'N/A')}
- Excerpt  : {scene.get('source_excerpt', 'N/A')}
- Location : {scene.get('location_name', 'N/A')}
- Audio    : {scene.get('audio_alignment_notes', 'N/A')}
{_per_second_block(scene.get("per_second_plan", []), duration)}
CHARACTERS IN THIS SCENE (use @label in dim_input):
{_format_chars(relevant, image_provided=image_provided)}
{image_provided_block}{char_no_image_block}
⚠️ CHARACTER SCOPE:
- Render the characters listed above (could be one, two, or none — empty → no humans in the prompt).
- NEVER copy character descriptions from other scenes.
- Keep each character's identity stable across all per-second beats — don't swap who's who mid-scene.

PRODUCT IN SCENE (use @ProductImage in dim_input when present):
{_format_product_block(product, product_role)}

FULL CAST (consistency reference only — do NOT include in this scene's prompt):
{_format_chars(all_characters)}

CONTINUITY (HARD RULE — scenes must read as ONE continuous take):
- From previous: {scene.get('continuity_from_previous', 'N/A')}
- To next      : {scene.get('continuity_to_next', 'N/A')}
{_adjacent_block(previous_scene, next_scene)}
- The `0–1s:` beat MUST resume the EXACT action and pose the previous scene ended on
  (use the same primary verb — e.g. if previous ended "running stride", this opens
  "still mid-stride down the street", not a new action like "tightening laces").
- The final beat (`End:`) MUST set up the next scene's opening — match its starting
  action so the cut from this scene to the next is invisible.
- No fades, no cuts to black, no establishing re-shots. Camera/lighting/wardrobe stay
  identical across the boundary unless `continuity_from_previous` explicitly says otherwise.
{_critique_block(critique_feedback, scene_index)}{_correction_hint(validator_errors)}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
6-DIMENSION FRAMEWORK
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DIM 1 INPUT — @CharacterName / @SceneBackground references and roles.
DIM 2 CONTENT — [Style]. [Character: exact appearance] in [Environment] [Action]. Quote any dialogue. Include ambient sound.
DIM 3 STYLE — visual style + lighting + color tone + texture + atmosphere. Use the style_lock verbatim.
DIM 4 CAMERA — concrete shot rules ("slow dolly-in from wide to medium close-up"). No adjectives.
DIM 5 STRUCTURE (PER-SECOND, MANDATORY, scene is {n_sec}s):
  Write ONE beat per second. Keep each character's identity stable across beats — don't swap who's who mid-scene. NO `[CharName]` brackets. EXACT format:
    0–1s: action + camera
    1–2s: action + camera
    ...
    {n_sec - 1}–{n_sec}s: action + camera
    End: held frame.
DIM 6 ASSEMBLED PROMPT — combine 2–5 into ONE paragraph TARGETING 210-250 words (validator ceiling 320; Wan22 UMT5 cliff is ~330–350 tokens — do NOT cross). Pack character bibles with concrete attributes (60-90w each), setting with named props/light/weather (30-45w), and 5 beats with sensory detail each (16-20w). Every per-second timestamp from DIM 5 MUST appear verbatim. NEVER write the words "logo", "subtitle", "watermark", or "title card" in DIM 6 (they're forbidden by the negative prompt).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Return ONLY valid JSON with these exact fields:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{{
  "dim_input": "<@asset labels and roles>",
  "dim_content": "<style + character + environment + action + dialogue>",
  "dim_style": "<style_lock verbatim + texture/atmosphere>",
  "dim_camera": "<shot size + angle + movement>",
  "camera_angle": "<explicit angle/framing>",
  "dim_structure": "<per-second beats with [CharName] brackets>",
  "scene_breakdown": "<DIM 5 verbatim, one line per second, with [CharName] brackets>",
  "video_prompt": "<DIM 6 assembled prompt TARGET 210-250 words (ceiling 320; ≈ 325 tokens — Wan22 UMT5 cliff is ~330–350 tokens; do NOT cross), present tense, all per-second timestamps embedded verbatim>",
  "negative_prompt": "text, subtitles, watermark, logo, title card, letters, words, folk art, static camera, frozen, jitter, flickering, temporal inconsistency, blurry, distorted, mirror, reflection, mirrored surface, vanity mirror, double face, reflected character",
  "continuity_guardrails": "<what must stay consistent with adjacent scenes>",
  "continues_from_previous": <true | false — true ONLY if same location AND same lighting AND same framing AND same pose AND no implied cut; false otherwise. Default false. See "CONTINUITY DECISION" section.>
}}
"""


def _build_batched_user_prompt(contexts: list[dict[str, Any]]) -> str:
    """Pack N scenes into one user message. The model returns a JSON object
    with a `scenes` array of N visual_director outputs in input order."""
    first = contexts[0]
    style_lock = first.get("style_lock") or (
        "cinematic documentary, natural lighting, warm earth tones, "
        "shallow depth of field, film grain, reverent mood"
    )
    story_summary = first.get("story_summary", "") or "N/A"
    pacing_notes = first.get("pacing_notes", "") or "N/A"
    all_characters = first.get("all_characters") or first.get("characters", [])

    header = f"""You are batching scene prompts. Generate the 6-Dimension visual prompt for EACH scene below.

🎯🎯🎯 WORD BUDGET — RICHER RENDERS BETTER 🎯🎯🎯
Each scene's `video_prompt` field TARGETS **210-250 words**. Validator ceiling: 320 (321+ = REJECTED).
- Use the room: character bibles 60-90w each with concrete attributes, setting 30-45w with named props/light/weather, 5 beats with one sensory detail each (16-20w/beat).
- Sparse <170w prompts render GENERIC; richer specific-noun prompts render SHARPER.
- Be specific, not padded. Noun-phrases > adjective-stacks. Cut articles + hedges + "also/then/and" chains, but add concrete sensory anchors (light catching cloth, dust in shafted light, wet stone, ash on feet).
- The 6-Dimension framework is a CHECKLIST — fold style/character/camera into the 5-section template (style line / character bibles / Setting: / 5 beats / closing).
This applies to EVERY scene in the batch, every time.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SHARED PROJECT CONTEXT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Story    : {story_summary}
Pacing   : {pacing_notes}

⚠️ STYLE LOCK (must appear verbatim in EVERY scene's dim_style and video_prompt — do NOT paraphrase):
  "{style_lock}"

FULL CAST (consistency reference across all scenes — only include in each scene's prompt the characters actually in that scene):
{_format_chars(all_characters)}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
6-DIMENSION FRAMEWORK (apply per scene; per-second count uses each scene's own duration)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DIM 1 INPUT — @CharacterName / @SceneBackground references and roles.
DIM 2 CONTENT — [Style]. [Character: exact appearance] in [Environment] [Action]. Quote any dialogue. Include ambient sound.
DIM 3 STYLE — visual style + lighting + color tone + texture + atmosphere. Use the style_lock verbatim.
DIM 4 CAMERA — concrete shot rules ("slow dolly-in from wide to medium close-up"). No adjectives.
DIM 5 STRUCTURE — for each scene of duration D seconds, write ONE beat per second (0–1s, 1–2s, …, (D-1)–Ds). Keep each character's identity stable across beats — don't swap who's who mid-scene. NO `[CharName]` brackets. End with "End: held frame."
DIM 6 ASSEMBLED PROMPT — combine 2–5 into ONE paragraph TARGETING 210-250 words (ceiling 320; ≈ 325 tokens — Wan22 UMT5 cliff is ~330–350 tokens; do NOT cross). Use the room: rich character bibles (60-90w each), packed setting line (30-45w), 5 beats with sensory detail (16-20w/beat). Every per-second timestamp from DIM 5 MUST appear verbatim. NEVER write "logo", "subtitle", "watermark", "title card" in DIM 6.

⚠️ CHARACTER SCOPE: each scene renders the characters listed in its block below (could be one, two, or none). Never copy descriptions from other scenes.
⚠️ CONTINUITY (HARD): each scene's `0–1s:` beat must resume the EXACT action/pose the previous scene ended on; the final beat must set up the next scene's opening. No fades, cuts to black, or re-establishing shots.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SCENES TO GENERATE — {len(contexts)} total
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🎯 REMINDER: each scene's `video_prompt` TARGETS 210-250 words (ceiling 320). Pack with concrete sensory nouns — sparse <170w prompts render generic. Be specific, not padded.
"""

    blocks = []
    for ctx in contexts:
        scene = ctx.get("scene", {})
        duration = scene.get("duration_seconds", 6.0)
        n_sec = int(duration)
        idx = scene.get("order_index", 0)
        chars = ctx.get("characters", [])
        relevant = [c for c in chars
                    if c.get("canonical_name", "") in scene.get("character_names", [])]
        product = ctx.get("product")
        product_role = ctx.get("product_role")
        prev = ctx.get("previous_scene")
        nxt = ctx.get("next_scene")
        critique_feedback = ctx.get("critique_feedback")
        validator_errors = ctx.get("validator_errors", [])

        image_provided = bool(scene.get("character_image_provided")) and bool(relevant)
        image_provided_block = (
            f"\n{_IMAGE_PROVIDED_RULE}\n" if image_provided else ""
        )
        char_no_image_block = ""
        if relevant and not image_provided:
            head = _CHAR_NO_IMAGE_RULE_HEAD
            if len(relevant) > 1:
                head = head + _MULTI_CHAR_POSITION_BLOCK
            char_no_image_block = f"\n{head}\n"

        blocks.append(f"""
╔═══ SCENE {idx} ═══╗
- Duration : {duration}s ({n_sec} per-second beats required)
- Purpose  : {scene.get('scene_purpose', 'N/A')}
- Visual   : {scene.get('visual_summary', 'N/A')}
- Excerpt  : {scene.get('source_excerpt', 'N/A')}
- Location : {scene.get('location_name', 'N/A')}
- Audio    : {scene.get('audio_alignment_notes', 'N/A')}
{_per_second_block(scene.get("per_second_plan", []), duration)}
CHARACTER IN THIS SCENE (use @label in dim_input):
{_format_chars(relevant, image_provided=image_provided)}
{image_provided_block}{char_no_image_block}
PRODUCT IN SCENE (use @ProductImage in dim_input when present):
{_format_product_block(product, product_role)}

CONTINUITY:
- From previous : {scene.get('continuity_from_previous', 'N/A')}
- To next       : {scene.get('continuity_to_next', 'N/A')}
{_adjacent_block(prev, nxt)}
{_critique_block(critique_feedback, idx)}{_correction_hint(validator_errors)}
""")

    schema = """
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OUTPUT — return EXACTLY this JSON shape (one entry per SCENE block above, in the same order):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{
  "scenes": [
    {
      "scene_index": 0,
      "dim_input": "<@asset labels and roles>",
      "dim_content": "<style + character + environment + action + dialogue>",
      "dim_style": "<style_lock verbatim + texture/atmosphere>",
      "dim_camera": "<shot size + angle + movement>",
      "camera_angle": "<explicit angle/framing>",
      "dim_structure": "<per-second beats>",
      "scene_breakdown": "<DIM 5 verbatim, one line per second>",
      "video_prompt": "<DIM 6 assembled prompt TARGET 210-250 words (ceiling 320; ≈ 325 tokens — Wan22 UMT5 cliff is ~330–350 tokens; do NOT cross), present tense, all per-second timestamps embedded verbatim>",
      "negative_prompt": "text, subtitles, watermark, logo, title card, letters, words, folk art, static camera, frozen, jitter, flickering, temporal inconsistency, blurry, distorted, mirror, reflection, mirrored surface, vanity mirror, double face, reflected character",
      "continuity_guardrails": "<what must stay consistent with adjacent scenes>",
      "continues_from_previous": <true | false — true ONLY if same location AND same lighting AND same framing AND same pose AND no implied cut; default false>
    },
    ... one object per scene, in the same order as the SCENE blocks above ...
  ]
}
"""
    return header + "\n".join(blocks) + schema


class VisualDirectorAgent(BaseAgent):
    """Creates the cinematic generation prompt for a single scene."""

    async def run_batch(self, contexts: list[dict[str, Any]]) -> list[AgentResult]:
        """Generate prompts for a batch of scenes in a single LLM call.

        Returns one AgentResult per input context, in input order. Scenes
        that fail validation (or aren't returned by the LLM) get retried
        individually via `run()`."""
        if not contexts:
            return []

        scene_indices = [c.get("scene", {}).get("order_index", "?") for c in contexts]
        self.logger.info(
            "Batched visual prompt: %d scenes (%s) in one LLM call",
            len(contexts), scene_indices,
        )
        system_prompt = self._load_prompt_template("visual_director.txt")
        user_prompt = _build_batched_user_prompt(contexts)
        # Per-scene budget × batch size, capped so we don't blow the model ceiling.
        max_tokens = min(3500 * len(contexts), 16000)

        try:
            response = await self.llm.complete_json(
                system_prompt=system_prompt, user_prompt=user_prompt,
                temperature=0.4, max_tokens=max_tokens,
            )
        except Exception as e:
            self.logger.exception("Batched visual prompt LLM call failed")
            # Fall back to per-scene singletons so the project still progresses.
            return [await self.run(ctx) for ctx in contexts]

        scenes_out = response.get("scenes")
        if not isinstance(scenes_out, list):
            self.logger.warning(
                "Batched response missing 'scenes' array — falling back to singletons"
            )
            return [await self.run(ctx) for ctx in contexts]

        # Map LLM outputs back to inputs by scene_index when present, else
        # positional fallback.
        by_index: dict[int, dict] = {}
        positional: list[dict] = []
        for entry in scenes_out:
            if not isinstance(entry, dict):
                continue
            si = entry.get("scene_index")
            if isinstance(si, int):
                by_index[si] = entry
            positional.append(entry)

        # Pass 1: classify each scene as "ok" (validated batch result) or "needs retry".
        # We collect retries with their position so we can run them all in parallel.
        import asyncio as _asyncio
        results: list[AgentResult | None] = [None] * len(contexts)
        retry_positions: list[int] = []
        retry_ctxs: list[dict[str, Any]] = []

        for pos, ctx in enumerate(contexts):
            scene = ctx.get("scene", {})
            idx = scene.get("order_index")
            duration = scene.get("duration_seconds", 6.0)
            style_lock = ctx.get("style_lock", "")
            data = by_index.get(idx) if isinstance(idx, int) else None
            if data is None and pos < len(positional):
                data = positional[pos]

            if not data or not data.get("video_prompt"):
                self.logger.warning(
                    "Batched: scene %s missing in response — queued for parallel retry", idx,
                )
                retry_positions.append(pos)
                retry_ctxs.append(dict(ctx))
                continue

            report = validate_scene_prompt(
                video_prompt=data.get("video_prompt", "") or "",
                negative_prompt=data.get("negative_prompt", "") or "",
                scene_breakdown=data.get("scene_breakdown", "") or "",
                duration_seconds=duration,
                style_lock=style_lock,
            )
            if report.ok:
                self.logger.info(
                    "Batched: scene %s ok (%d chars)",
                    idx, len(data.get("video_prompt", "")),
                )
                data["validator_errors"] = []
                results[pos] = AgentResult(success=True, data=data)
            else:
                # Over-cap-only: truncate inline — no extra LLM call. Only a
                # real validation error (style/beats/negatives) is worth a retry.
                vp = data.get("video_prompt", "") or ""
                cap_only = bool(report.errors) and all("words; cap is" in e for e in report.errors)
                if cap_only and vp:
                    data["video_prompt"] = _truncate_to_word_cap(vp, WORD_CAP)
                    data["validator_errors"] = []
                    results[pos] = AgentResult(success=True, data=data)
                    self.logger.info("Batched: scene %s truncated to cap inline (no retry)", idx)
                else:
                    self.logger.warning(
                        "Batched: scene %s failed validation (%s) — queued for parallel retry",
                        idx, "; ".join(report.errors),
                    )
                    ctx_retry = dict(ctx)
                    ctx_retry["validator_errors"] = report.errors
                    retry_positions.append(pos)
                    retry_ctxs.append(ctx_retry)

        # Pass 2: run ALL single-scene retries CONCURRENTLY via asyncio.gather.
        # Each self.run() makes its own LLM call with its own retry loop, so this
        # turns a serial M×N wait into one M-wide parallel wait.
        if retry_ctxs:
            self.logger.info(
                "Batched: firing %d scene retries in parallel", len(retry_ctxs),
            )
            retried = await _asyncio.gather(
                *[self.run(rc) for rc in retry_ctxs], return_exceptions=True
            )
            for pos, res in zip(retry_positions, retried):
                if isinstance(res, BaseException):
                    self.logger.exception(
                        "Parallel retry for scene at pos %d raised", pos, exc_info=res,
                    )
                    results[pos] = AgentResult(success=False, errors=[str(res)])
                else:
                    results[pos] = res

        return [r if r is not None else AgentResult(success=False, errors=["unfilled slot"])
                for r in results]

    async def run(self, context: dict[str, Any]) -> AgentResult:
        scene = context.get("scene", {})
        scene_index = scene.get("order_index", 0)
        duration = scene.get('duration_seconds', 6.0)
        style_lock = context.get("style_lock", "")
        critique_feedback = context.get("critique_feedback")

        self.logger.info(
            "Generating visual prompt for scene %d%s",
            scene_index, " [CRITIQUE CORRECTION PASS]" if critique_feedback else ""
        )
        system_prompt = self._load_prompt_template("visual_director.txt")

        validator_errors: list[str] = []
        last_result: dict | None = None
        for attempt in range(MAX_RETRIES + 1):
            user_prompt = _build_user_prompt(
                scene=scene,
                characters=context.get("characters", []),
                all_characters=context.get("all_characters", context.get("characters", [])),
                previous_scene=context.get("previous_scene"),
                next_scene=context.get("next_scene"),
                story_summary=context.get("story_summary", ""),
                pacing_notes=context.get("pacing_notes", ""),
                style_lock=style_lock,
                critique_feedback=critique_feedback,
                validator_errors=validator_errors,
                product=context.get("product"),
                product_role=context.get("product_role"),
            )
            try:
                last_result = await self.llm.complete_json(
                    system_prompt=system_prompt, user_prompt=user_prompt,
                    temperature=0.4, max_tokens=3500,
                )
            except Exception as e:
                self.logger.exception("Visual prompt LLM call failed for scene %d", scene_index)
                return AgentResult(success=False, errors=[str(e)])

            report = validate_scene_prompt(
                video_prompt=last_result.get("video_prompt", "") or "",
                negative_prompt=last_result.get("negative_prompt", "") or "",
                scene_breakdown=last_result.get("scene_breakdown", "") or "",
                duration_seconds=duration,
                style_lock=style_lock,
            )
            if report.ok:
                self.logger.info(
                    "Visual prompt scene %d ok (%d chars, attempt %d)",
                    scene_index, len(last_result.get("video_prompt", "")), attempt + 1,
                )
                last_result["validator_errors"] = []
                return AgentResult(success=True, data=last_result)

            validator_errors = report.errors
            # Over-cap word count is the one error retrying does NOT fix — the LLM
            # keeps overshooting and we truncate anyway. So truncate NOW instead of
            # burning MAX_RETRIES LLM calls. (Only when the cap is the ONLY error.)
            video_prompt = last_result.get("video_prompt", "") or ""
            cap_only = bool(validator_errors) and all("words; cap is" in e for e in validator_errors)
            if cap_only and video_prompt:
                last_result["video_prompt"] = _truncate_to_word_cap(video_prompt, WORD_CAP)
                last_result["validator_errors"] = []
                self.logger.info(
                    "Visual prompt scene %d: truncated to cap on attempt %d (no retries wasted)",
                    scene_index, attempt + 1,
                )
                return AgentResult(success=True, data=last_result)
            self.logger.warning(
                "Visual prompt scene %d failed validation (attempt %d): %s",
                scene_index, attempt + 1, "; ".join(validator_errors),
            )

        # Out of retries. If the only remaining failure is over-cap words,
        # hard-truncate to WORD_CAP at the nearest sentence boundary so the
        # downstream model never sees an over-cap prompt. Other validation
        # errors (style mismatch, missing beats) fall through as warnings.
        if last_result is not None:
            video_prompt = last_result.get("video_prompt", "") or ""
            cap_errors = [e for e in validator_errors if "words; cap is" in e]
            if cap_errors and video_prompt:
                original_wc = len(video_prompt.split())
                truncated = _truncate_to_word_cap(video_prompt, WORD_CAP)
                new_wc = len(truncated.split())
                self.logger.warning(
                    "Visual prompt scene %d: hard-truncated %d → %d words after %d failed retries",
                    scene_index, original_wc, new_wc, MAX_RETRIES + 1,
                )
                last_result["video_prompt"] = truncated
                last_result["truncated_from_words"] = original_wc
                # Re-validate so other errors (if any) flow through as warnings.
                report = validate_scene_prompt(
                    video_prompt=truncated,
                    negative_prompt=last_result.get("negative_prompt", "") or "",
                    scene_breakdown=last_result.get("scene_breakdown", "") or "",
                    duration_seconds=duration, style_lock=style_lock,
                )
                validator_errors = report.errors
            last_result["validator_errors"] = validator_errors
            return AgentResult(success=True, data=last_result, warnings=validator_errors)
        return AgentResult(success=False, errors=validator_errors or ["LLM produced no result"])
