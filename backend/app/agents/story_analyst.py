"""
Story Analyst Agent — extracts structured information from raw story text.

Identifies: beats, characters, locations, emotional arcs, pacing,
project-wide style_lock (mandatory).
"""

from typing import Any

from app.agents.base import AgentResult, BaseAgent

STYLE_LOCK_MAX_WORDS = 25
MAX_RETRIES = 2
MAX_PRODUCTS = 1  # v1: at most one branded SKU per ad project
VALID_CHARACTER_KINDS = {"human", "mascot", "creature", "object"}


def _validate_style_lock(s: str) -> list[str]:
    errors: list[str] = []
    if not s or not s.strip():
        errors.append("style_lock is empty")
    elif len(s.split()) > STYLE_LOCK_MAX_WORDS:
        errors.append(f"style_lock has {len(s.split())} words (cap is {STYLE_LOCK_MAX_WORDS})")
    return errors


def _validate_characters(characters: list[dict] | None) -> list[str]:
    errs: list[str] = []
    for i, c in enumerate(characters or []):
        kind = (c.get("character_kind") or "").strip().lower()
        if kind and kind not in VALID_CHARACTER_KINDS:
            errs.append(
                f"characters[{i}].character_kind={kind!r} — must be one of "
                f"{sorted(VALID_CHARACTER_KINDS)}"
            )
    return errs


def _validate_products(products: list[dict] | None) -> list[str]:
    if not products:
        return []
    if len(products) > MAX_PRODUCTS:
        return [f"products has {len(products)} entries (cap is {MAX_PRODUCTS}) — pick the single hero SKU"]
    errs: list[str] = []
    for i, p in enumerate(products):
        if not (p.get("canonical_name") or "").strip():
            errs.append(f"products[{i}].canonical_name is empty")
        if not (p.get("physical_description") or "").strip():
            errs.append(f"products[{i}].physical_description is empty (needed for hero shot)")
    return errs


def _build_user_prompt(story_text: str, target_duration: float | None,
                      corrective_hint: str | None = None) -> str:
    duration_line = (
        f"TARGET TOTAL DURATION: {target_duration:.1f} seconds. "
        f"Pacing notes MUST describe how to fill exactly this duration.\n\n"
        if target_duration else ""
    )
    correction_block = (
        f"\nPREVIOUS ATTEMPT FAILED VALIDATION:\n  {corrective_hint}\n"
        f"Re-emit the JSON with this fixed.\n\n"
        if corrective_hint else ""
    )
    return f"""Analyze the following story and extract structured information for a video production pipeline.

{duration_line}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
INPUT — STORY TEXT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{story_text}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{correction_block}
LOCATION CONSOLIDATION (IMPORTANT):
- Output the FEWEST distinct locations the story actually needs.
- For a short ad (under 60s) target 1-3 locations TOTAL — never one per scene.
- Different camera angles or close-ups of the SAME physical place = ONE location.
- Different times-of-day at the same place = still ONE location (note time in description).
- Only create a new location when the action moves to a genuinely new physical place.
- Each background change costs visual continuity, so be parsimonious.

STYLE LOCK (MANDATORY):
- Required, non-empty, ≤{STYLE_LOCK_MAX_WORDS} words.
- One sentence covering: visual genre + lighting + color palette + texture + mood.
- No character names, no scene-specific words (it's project-wide).
- **DEFAULT STYLE — anime, exactly one of two flavors below.**
  Unless the story EXPLICITLY asks for a different visual style
  (e.g. "live-action documentary", "photoreal commercial", "watercolor",
  "claymation", "8-bit pixel art"), default the style_lock to ONE of:
    • Studio Ghibli / Mamoru Hosoda painterly hand-drawn 2D anime —
      soft watercolor backgrounds, gentle linework, warm natural light,
      emotive but restrained character animation. Pick this for emotional,
      lyrical, slice-of-life, narrative, or natural-world stories.
    • Shounen-action anime — bold cel-shaded 2D linework, dynamic
      speed-lines, saturated highlights, kinetic motion blur, dramatic
      chiaroscuro. Pick this for high-energy action, sport, combat,
      sci-fi, music-video, or thriller stories.
  Pick exactly one. Never blend the two, never pick Pixar / Simpsons /
  cel-shaded-3D / chibi / Saturday-morning-cartoon. Never default to
  photoreal / live-action / documentary unless the story text itself
  asks for that look.

OUTPUT — Return ONLY valid JSON:
{{
  "story_summary": "<2-3 sentences covering full arc>",
  "beats": [
    {{"beat_index": 0, "description": "<what happens>", "emotion": "<dominant emotion>"}}
  ],
  "characters": [
    {{
      "canonical_name": "<name or role>",
      "character_kind": "<human|mascot|creature|object — see CHARACTER KIND below>",
      "gender": "<male|female|non-binary|other (for non-human, use 'N/A' or character's apparent gender)>",
      "ethnicity": "<cultural origin (for non-human, use 'N/A' or 'cartoon character')>",
      "skin_tone": "<specific e.g. warm deep brown, light olive, medium tan (for non-human, the body color)>",
      "physical_description": "<height, build, hair, eyes, features — enough to recreate. For non-human: body shape, surface, distinguishing marks>",
      "clothing_description": "<materials, colors, cultural style. For mascots/objects with NO clothing, write the body/surface description here (e.g. 'no clothing; smooth blue toothbrush body with white bristles'). For creatures with no clothing, 'no clothing; natural fur/scales pattern'.>",
      "personality_notes": "<brief character essence>",
      "voice_notes": "<tone, accent, pace>"
    }}
  ],
  "locations": [
    {{"name": "<location>", "description": "<surfaces, lighting, time of day, atmosphere>"}}
  ],
  "products": [
    {{
      "canonical_name": "<branded SKU name, e.g. 'RedFizz Cola 12oz Bottle'>",
      "category": "<beverage|electronics|apparel|food|personal_care|other>",
      "physical_description": "<shape, size, material, dominant colors — enough to recreate>",
      "brand_marks": "<label band, embossing, wordmark visual style — described visually, NOT by brand name>",
      "color_palette": "<dominant colors of the product itself>",
      "hero_angle": "<best reference-shot angle, e.g. 'three-quarter front, slight low angle'>"
    }}
  ],
  "pacing_notes": "<overall rhythm fitting the TARGET TOTAL DURATION above>",
  "style_lock": "<MANDATORY one-sentence ≤{STYLE_LOCK_MAX_WORDS}-word project-wide visual anchor>"
}}

CHARACTER KIND (MANDATORY, exactly one of: human | mascot | creature | object):
- "human"    — a real person (any age, gender, ethnicity).
- "mascot"   — an anthropomorphized object/animal/abstract thing acting as a character with a face and personality (e.g. a smiling toothbrush, a friendly cloud, a dancing taco). MOST cartoon ad characters are mascots.
- "creature" — an animal or fantasy being depicted naturalistically (not anthropomorphized into an object-shaped mascot).
- "object"   — an inanimate hero subject that's the focus but has no face/personality (rare; usually the product entry should hold this instead).
- Pick the kind based on the visual rendering required. If the story says "a cheerful blue toothbrush mascot with eyes and a smile dances around" → kind=mascot, NOT human.
- This field decides which prompt template the image generator uses. A wrong kind produces a photoreal human when a cartoon mascot was wanted.

PRODUCTS RULE (HARD CAP {MAX_PRODUCTS}):
- A "product" is the central physical good the ad is selling or showcasing. Brand is OPTIONAL — a generic "cola bottle", "running shoe", "smartphone", "skincare serum dropper bottle" all count if they're the hero of the ad. Use a descriptive canonical_name (e.g. "frosted glass cola bottle", "orange running shoe") when no brand is given.
- If the ad has no central commercial good (a PSA / charity / awareness campaign / pure lifestyle vignette with no hero object), emit `"products": []`.
- Decision rule — ask: "Is the on-screen physical object what this ad is trying to sell?" If yes → extract it. If the ad is selling an idea / cause / behavior change → emit [].
- Examples that ARE products: a cola bottle in a beverage ad, a watch in a luxury watch ad, a backpack in an outdoor brand ad, a storybook in a kids' book ad.
- Examples that are NOT products: soil in a Save Soil PSA, a hand-pump in a clean-water charity ad, a yoga pose in a wellness lifestyle piece.
- AT MOST {MAX_PRODUCTS} entry. If the story mentions multiple goods, pick the single hero one.
"""


class StoryAnalystAgent(BaseAgent):
    """Analyzes raw story text and extracts a structured story graph."""

    async def run(self, context: dict[str, Any]) -> AgentResult:
        story_text = context.get("story_text", "")
        target_duration = context.get("target_duration")
        if not story_text.strip():
            return AgentResult(success=False, errors=["No story text provided"])

        self.logger.info("Analyzing story (%d chars, target=%s)", len(story_text), target_duration)
        system_prompt = self._load_prompt_template("story_analyst.txt")

        last_error: str | None = None
        for attempt in range(MAX_RETRIES + 1):
            user_prompt = _build_user_prompt(story_text, target_duration, last_error)
            try:
                result = await self.llm.complete_json(
                    system_prompt=system_prompt, user_prompt=user_prompt,
                    temperature=0.5, max_tokens=4096,
                )
            except Exception as e:
                self.logger.exception("Story analysis LLM call failed")
                return AgentResult(success=False, errors=[str(e)])

            errors = _validate_style_lock(result.get("style_lock", ""))
            errors += _validate_characters(result.get("characters"))
            errors += _validate_products(result.get("products"))
            if not errors:
                self.logger.info(
                    "Analysis complete: %d beats, %d characters, %d locations, %d products, style_lock=%d words",
                    len(result.get("beats", [])), len(result.get("characters", [])),
                    len(result.get("locations", [])), len(result.get("products", []) or []),
                    len(result.get("style_lock", "").split()),
                )
                return AgentResult(success=True, data=result)

            last_error = "; ".join(errors)
            self.logger.warning("Attempt %d: %s — retrying", attempt + 1, last_error)

        return AgentResult(success=False, errors=[f"style_lock validation failed after {MAX_RETRIES + 1} attempts: {last_error}"])
