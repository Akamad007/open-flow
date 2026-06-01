"""LLM-driven prompt builders for character / background / action stills."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from app.agents.image_pregen._constants import GENERIC_NEGATIVE, QUALITY_SUFFIX
from app.models.character import Character
from app.models.location import Location
from app.models.product import Product

logger = logging.getLogger(__name__)


def _load_template(filename: str) -> str:
    template_path = Path(__file__).parent.parent.parent / "prompts" / filename
    if not template_path.exists():
        logger.warning("Prompt template not found: %s", filename)
        return ""
    return template_path.read_text()


_PORTRAIT_FRAMING_PREFIX = (
    "full-body portrait head to toe in frame, both feet visible on the ground, "
    "neutral standing pose, three-quarter front view, full body shot, "
    "wide framing with headroom above and floor below the feet, "
)
_PORTRAIT_NEGATIVE_GUARD = (
    "bust shot, head-and-shoulders, head and shoulders, waist-up, half body, "
    "torso shot, close-up, cropped feet, cropped legs, cropped at waist, "
    "cropped at chest"
)
_CROPPING_TERMS_RE = re.compile(
    r"\b(?:bust|head[- ]and[- ]shoulders?|waist[- ]up|half[- ]body|torso[- ]shot|"
    r"close[- ]up|head[- ]shot|portrait[- ]shot|medium[- ]shot)\b",
    re.IGNORECASE,
)


def _force_full_body(prompt: str) -> str:
    """SD3.5 collapses to a torso shot when given a portrait prompt unless we
    bake the framing in deterministically. Strip any cropping terms the LLM
    may have leaked in, then prefix the canonical full-body framing phrase."""
    cleaned = _CROPPING_TERMS_RE.sub("", prompt or "")
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" ,.")
    return _PORTRAIT_FRAMING_PREFIX + cleaned


_NONHUMAN_KINDS = {"mascot", "creature", "object"}


def _is_nonhuman(char: Character) -> bool:
    return (getattr(char, "character_kind", None) or "human").strip().lower() in _NONHUMAN_KINDS


async def _build_nonhuman_portrait(llm, char: Character, story_summary: str) -> tuple[str, str]:
    """Portrait prompt for mascot/creature/object characters. Skips the human
    full-body framing prefix and the 'wearing {outfit}' splicer that make
    SD3.5 render a photoreal person for non-human subjects."""
    system_prompt = _load_template("character_portrait_nonhuman.txt")
    user_message = (
        f"STORY VISUAL STYLE (lead the prompt with this — match it exactly):\n"
        f"{story_summary or 'Modern cartoon style'}\n\n"
        f"Character name: {char.canonical_name}\n"
        f"Character kind: {char.character_kind or 'mascot'}\n"
        f"Body / physical description: {char.physical_description or 'not specified'}\n"
        f"Surface / appearance notes: {char.clothing_description or 'not specified'}\n\n"
        f"This subject is NOT a person. Do NOT add human clothing or human anatomy. "
        f"Render the body as described above, in the story's visual style."
    )
    try:
        result = await llm.complete_json(
            system_prompt=system_prompt, user_prompt=user_message, max_tokens=1024,
        )
        portrait_prompt = result.get("portrait_prompt", "")
        if not portrait_prompt:
            raise ValueError("Empty portrait_prompt from LLM")
        neg = result.get("negative_prompt", _NONHUMAN_NEGATIVE)
        return portrait_prompt, neg
    except Exception as e:
        logger.warning(
            "LLM non-human portrait prompt failed for %s, using fallback: %s",
            char.canonical_name, e,
        )
        parts = [story_summary or "cartoon style", char.canonical_name]
        if char.physical_description:
            parts.append(char.physical_description)
        if char.clothing_description:
            parts.append(char.clothing_description)
        parts.append("centered, plain neutral backdrop, soft even lighting, sharp focus")
        prompt = ", ".join(p.strip().rstrip(",") for p in parts if p and p.strip())
        return prompt, _NONHUMAN_NEGATIVE


_NONHUMAN_NEGATIVE = (
    "human figure, photoreal person, realistic human, man, woman, T-shirt, "
    "jeans, pants, sneakers, shoes, clothing, garments, dressed, wearing clothes, "
    "two feet on the ground, photorealistic, photograph, real-life photo, "
    + GENERIC_NEGATIVE
)


async def build_character_prompt(llm, char: Character, story_summary: str = "") -> tuple[str, str]:
    """Build SD3.5 portrait prompt. Branches on character_kind:
    - human: full-body human framing + outfit splice (the LLM is told to omit
      clothing words; the canonical outfit clause is spliced on at the end).
    - mascot/creature/object: skip human-anatomy guards + outfit splice, lead
      with the story's visual style so SD3.5 renders the actual non-human body."""
    if _is_nonhuman(char):
        return await _build_nonhuman_portrait(llm, char, story_summary)

    system_prompt = _load_template("character_portrait.txt")
    user_message = (
        f"STORY CONTEXT (use this to determine the visual style — DO NOT use folk art or painting styles unless the story is explicitly about that):\n"
        f"{story_summary or 'Modern setting — use contemporary, photorealistic or cinematic style'}\n\n"
        f"Character name: {char.canonical_name}\n"
        f"Physical description: {char.physical_description or 'not specified'}\n\n"
        f"⚠️ CLOTHING IS HANDLED BY THE SYSTEM. Do NOT describe clothing,\n"
        f"garments, colors-of-clothes, or footwear in your prompt. The\n"
        f"canonical outfit string is appended deterministically after your\n"
        f"output so the portrait and every action still wear the exact same\n"
        f"outfit. Describe identity (face, build, hair, eyes, expression)\n"
        f"and pose only.\n\n"
        f"Write a focused, vivid SD3.5 portrait prompt for this character that matches the story's visual style."
    )
    outfit = _canonical_outfit(char)
    try:
        result = await llm.complete_json(
            system_prompt=system_prompt, user_prompt=user_message, max_tokens=1024,
        )
        portrait_prompt = result.get("portrait_prompt", "")
        if not portrait_prompt:
            raise ValueError("Empty portrait_prompt from LLM")
        neg = result.get("negative_prompt", GENERIC_NEGATIVE)
        framed = _force_full_body(portrait_prompt)
        return _splice_outfit(framed, outfit), f"{_PORTRAIT_NEGATIVE_GUARD}, {neg}"
    except Exception as e:
        logger.warning(
            "LLM portrait prompt failed for %s, using fallback: %s", char.canonical_name, e,
        )
        parts = [char.canonical_name]
        if char.physical_description:
            parts.append(char.physical_description)
        prompt = ", ".join(p.strip().rstrip(",") for p in parts if p.strip())
        framed = _force_full_body(prompt.rstrip(".") + QUALITY_SUFFIX)
        return (
            _splice_outfit(framed, outfit),
            f"{_PORTRAIT_NEGATIVE_GUARD}, {GENERIC_NEGATIVE}",
        )


_PRODUCT_NEGATIVE = (
    "text, letters, words, wordmark, logo, watermark, label text, brand name, "
    "hand, finger, person, character, environment, scenery, blurry, deformed shape"
)


async def build_product_prompt(llm, prod: Product, story_summary: str = "") -> tuple[str, str]:
    """Hero shot for a branded SKU. Studio-flat — never cinematic; per-scene
    style is added later when the action stills are rendered."""
    system_prompt = _load_template("product_hero.txt")
    user_message = (
        f"PRODUCT TYPE         : {prod.canonical_name}\n"
        f"CATEGORY             : {prod.category or 'other'}\n"
        f"PHYSICAL DESCRIPTION : {prod.physical_description or 'not specified'}\n"
        f"BRAND MARKS (visual) : {prod.brand_marks or 'plain unbranded'}\n"
        f"COLOR PALETTE        : {prod.color_palette or 'natural product colors'}\n"
        f"HERO ANGLE           : {prod.hero_angle or 'three-quarter front, slight low angle'}\n\n"
        "Write a focused, clean SD3.5 product-hero prompt. Studio framing, "
        "neutral backdrop, soft product lighting. Describe brand marks visually "
        "(label band shape, embossing, color blocking) but NEVER write the brand "
        "name, the word 'logo', or any rendered text."
    )
    try:
        result = await llm.complete_json(
            system_prompt=system_prompt, user_prompt=user_message, max_tokens=512,
        )
        product_prompt = result.get("product_prompt", "")
        if not product_prompt:
            raise ValueError("Empty product_prompt from LLM")
        return product_prompt, result.get("negative_prompt", _PRODUCT_NEGATIVE)
    except Exception as e:
        logger.warning(
            "LLM product prompt failed for %s, using fallback: %s", prod.canonical_name, e,
        )
        parts = [
            f"{prod.canonical_name}",
            prod.physical_description or "branded product",
            f"colors: {prod.color_palette}" if prod.color_palette else "",
            f"{prod.brand_marks}" if prod.brand_marks else "",
            "studio product shot, neutral backdrop, soft product lighting, centered",
        ]
        prompt = ", ".join(p.strip().rstrip(",") for p in parts if p and p.strip())
        return prompt, _PRODUCT_NEGATIVE


# Deterministic framing prefix — every background is a natural cinematic
# establishing shot of the location. The character gets composited over
# the center at video time, so we DON'T force an empty central area
# (that made SD3.5 render weird geometric voids). Just "no people" so
# we don't double-up bodies after compositing.
_BG_FRAMING_PREFIX = (
    "landscape 16:9 cinematic establishing shot of the environment, "
    "natural scene composition, no people in frame"
)
_BG_FRAMING_NEGATIVE = (
    "person, people, human, figure, silhouette, subject, character, model, "
    "mannequin, statue, body, hands, feet"
)


async def build_background_prompt(llm, loc: Location, story_summary: str = "") -> tuple[str, str]:
    system_prompt = _load_template("background_scene.txt")
    bg_negative = GENERIC_NEGATIVE + ", people, characters, person, human, " + _BG_FRAMING_NEGATIVE

    user_message = (
        f"STORY CONTEXT (use this to determine the visual style — DO NOT use folk art or painting styles unless the story is explicitly about that):\n"
        f"{story_summary or 'Modern setting — use contemporary, photorealistic or cinematic style'}\n\n"
        f"Location name: {loc.name}\n"
        f"Description: {loc.description or 'not specified'}\n"
        "\nWrite a focused, vivid SD3.5 background environment prompt for this location that matches the story's visual style. "
        "Make it a natural cinematic establishing shot — like a real photograph of the place. "
        "No people in the frame. Standard landscape 16:9 framing."
    )
    try:
        result = await llm.complete_json(
            system_prompt=system_prompt, user_prompt=user_message, max_tokens=1024,
        )
        bg_prompt = result.get("background_prompt", "")
        if not bg_prompt:
            raise ValueError("Empty background_prompt from LLM")
        # Always prepend the deterministic framing — LLM may or may not honor
        # the non-negotiable instruction, so we guarantee it via prefix.
        bg_prompt = f"{_BG_FRAMING_PREFIX}, {bg_prompt}"
        neg = result.get("negative_prompt", bg_negative)
        if _BG_FRAMING_NEGATIVE not in neg:
            neg = neg.rstrip(", ") + ", " + _BG_FRAMING_NEGATIVE
        return bg_prompt, neg
    except Exception as e:
        logger.warning("LLM background prompt failed for %s, using fallback: %s", loc.name, e)
        parts = [_BG_FRAMING_PREFIX, loc.name]
        if loc.description:
            parts.append(loc.description)
        parts.extend(["wide establishing shot", "no characters no people empty scene"])
        prompt = ", ".join(p.strip().rstrip(",") for p in parts if p.strip())
        return prompt.rstrip(".") + QUALITY_SUFFIX, bg_negative


def _moment_label(second_idx: int, n_stills: int) -> str:
    if n_stills == 1:
        return "peak action moment"
    if second_idx == 0:
        return "scene entrance / opening beat (second 0)"
    if second_idx == n_stills - 1:
        return f"scene exit / final beat (second {second_idx}, last)"
    return f"mid-scene action continuation (second {second_idx} of {n_stills - 1})"


def _beat_hint(scene_breakdown: str, second_idx: int) -> str:
    lines = [l.strip() for l in (scene_breakdown or "").split("\n") if l.strip()]
    if not lines:
        return ""
    return lines[min(second_idx, len(lines) - 1)]


_FULL_BODY_GUARD = (
    "FULL-BODY HEAD-TO-TOE: the character must be entirely visible from head "
    "to feet — no cropping at the head, knees, or feet. Both feet on the "
    "ground (or off-ground if mid-jump/run) and clearly in frame. NO "
    "head-and-shoulders, NO bust shot, NO waist-up crop, NO hands-only macro, "
    "NO face close-up. Center the subject."
)

_ACTION_FRAMING_HINTS = (
    # Every action — regardless of verb — gets the same full-body guard plus
    # an action-specific anatomy reminder. The user's hard rule is head-to-toe
    # always, so close-ups are forbidden.
    (re.compile(r"\b(walk|stride|stroll|step|run|jog|sprint|march)\w*", re.IGNORECASE),
     _FULL_BODY_GUARD + " Both legs and feet must read clearly so the gait pose is unambiguous."),
    (re.compile(r"\b(kneel|crouch|squat|bend\s+down|bow)\w*", re.IGNORECASE),
     _FULL_BODY_GUARD + " Knees and feet must be visible so the kneeling/crouch pose reads."),
    (re.compile(r"\b(hand|finger|grip|hold|grasp|press|crumble|lift|pour)\w*", re.IGNORECASE),
     _FULL_BODY_GUARD + " Camera is pulled back to a wide full-body shot. Hands and fingers must "
     "still be anatomically correct (5 fingers per hand, no extra digits) but "
     "they are NOT a macro close-up — show the whole person performing the action."),
    (re.compile(r"\b(face|gaze|looks?\s+(into|at)|stare|smile|speak)\w*", re.IGNORECASE),
     _FULL_BODY_GUARD + " The face is visible at full-body distance (do NOT zoom in for a face close-up)."),
    (re.compile(r"\b(sit|stand|pose|portrait)\w*", re.IGNORECASE),
     _FULL_BODY_GUARD),
)


def _composition_guards_for(action: str) -> str:
    """Always emit the full-body guard (the user's hard rule) plus any
    action-specific anatomy reminders."""
    hints: list[str] = [_FULL_BODY_GUARD]
    for pat, hint in _ACTION_FRAMING_HINTS:
        if action and pat.search(action) and hint not in hints:
            hints.append(hint)
    return "\n".join(hints)


def _other_char_names(scene, primary_char) -> list[str]:
    """First-token names of every linked character on the scene that is NOT
    the primary. e.g. ['Child (implied)', 'Farmer (implied)'] → ['Child', 'Farmer']."""
    out: list[str] = []
    for c in (scene.characters or []):
        if c.id == primary_char.id:
            continue
        first = (c.canonical_name or "").split()[0].strip()
        if first and first not in out:
            out.append(first)
    return out


def _strip_other_chars(text: str, blocked: list[str]) -> str:
    """Remove references to other characters' names (and possessives) so the
    SD3.5 prompt builder can't be tempted to render a second person."""
    if not text or not blocked:
        return text
    out = text
    for name in blocked:
        out = re.sub(rf"\b{re.escape(name)}'s\b", "", out, flags=re.IGNORECASE)
        out = re.sub(rf"\b(?:the|a|an)\s+{re.escape(name)}\b", "", out, flags=re.IGNORECASE)
        out = re.sub(rf"\b{re.escape(name)}\b", "", out, flags=re.IGNORECASE)
    out = re.sub(r"\s+", " ", out)
    out = re.sub(r"\s+([.,;:!?])", r"\1", out)
    return out.strip(" ,.")


def _product_block(product: Product | None, role: str | None) -> str:
    if product is None:
        return ""
    role_phrasing = {
        "hero": "extreme close-up on the product as the visual focus, character's hand entering frame from one side",
        "holding": "the character grips the product naturally during the action",
        "background": "the product sits on a surface in frame, clearly visible",
    }.get((role or "holding").lower(), "the character grips the product naturally during the action")
    return (
        "\nPRODUCT IN FRAME (must appear in this still):\n"
        f"  Visual : {product.physical_description or 'not specified'}\n"
        f"  Marks  : {product.brand_marks or 'plain unbranded'}\n"
        f"  Colors : {product.color_palette or 'natural product colors'}\n"
        f"  Role   : {role or 'holding'} — {role_phrasing}\n"
        "  RULE   : describe the product BY VISUAL DESCRIPTION ONLY. NEVER write the brand name,\n"
        "           the word 'logo', 'label text', 'wordmark', or any rendered text.\n"
    )


def _scene_action_user_message(
    scene, primary_char, story_summary: str, second_idx: int, n_stills: int,
    corrective_hint: str | None = None,
    product: Product | None = None, product_role: str | None = None,
) -> str:
    """Build a STRICTLY character-and-action user message.

    The still gets background-removed; the location plate is composited
    separately at video time. So the still prompt should describe ONLY
    the character + their dress + the action they're performing — not the
    environment, not the lighting, not the cinematography.

    Inputs:
      - WHO     : character physical description + clothing
      - WHAT    : the single action visible AT THIS frozen instant

    Deliberately NOT passed:
      - environment / location  (bg is generated + composited separately)
      - lighting / time-of-day  (comes from the bg plate at video time)
      - cinematography / style  (same)
      - video_prompt / scene_breakdown / camera_plan  (timeline leaks)
    """
    p = scene.prompt
    beat = _beat_hint((p.scene_breakdown if p else "") or "", second_idx)
    primary_action = beat.strip(" :") or (p.action_description if p else "") or scene.visual_summary or ""
    primary_action = _strip_timeline_language(primary_action)
    blocked = _other_char_names(scene, primary_char)
    primary_action = _strip_other_chars(primary_action, blocked)
    framing = _composition_guards_for(primary_action)
    framing_block = f"\nFRAMING / POSE GUARDS (mandatory):\n{framing}\n" if framing else ""
    correction_block = (
        f"\n⚠️ A PRIOR ATTEMPT WAS REJECTED — fix these specifically:\n  {corrective_hint}\n"
        if corrective_hint else ""
    )
    ban_list = ", ".join(blocked) if blocked else "(none)"

    product_section = _product_block(product, product_role)

    return (
        f"⚠️ THIS IS AN ACTION STILL, NOT A PORTRAIT.\n"
        f"The character must be visibly performing the specific action below.\n"
        f"⚠️ FRAMING: ALWAYS full-body, head-to-toe, both feet visible. NO\n"
        f"head-and-shoulders, NO bust shot, NO waist-up crop, NO hands-only\n"
        f"macro, NO face close-up. The whole person — head, torso, legs, and\n"
        f"feet — must be in the frame at full-body distance.\n\n"
        f"⚠️ ONE PERSON ONLY — STRICT. The image MUST contain exactly ONE\n"
        f"human: {primary_char.canonical_name}. Do NOT render a second body,\n"
        f"second face, second pair of hands, or any other person — not even\n"
        f"partially in frame, not even off-screen-implied. NEVER name or\n"
        f"depict: {ban_list}. If the action below references another person\n"
        f"(e.g. 'child's hand'), reattribute that action to {primary_char.canonical_name}.\n\n"
        f"WHAT (the SINGLE action visible at this frozen instant — render verbatim,\n"
        f"performed by {primary_char.canonical_name} alone):\n"
        f"  {primary_action or 'standing'}\n"
        f"{framing_block}{correction_block}{product_section}\n"
        f"WHO (character identity — match exactly so identity reads through):\n"
        f"  Name     : {primary_char.canonical_name}\n"
        f"  Physical : {primary_char.physical_description or 'not specified'}\n\n"
        f"⚠️ CLOTHING IS HANDLED BY THE SYSTEM. Do NOT describe clothing,\n"
        f"garments, colors-of-clothes, or footwear in your prompt. The\n"
        f"canonical outfit string is appended deterministically after your\n"
        f"output so it is byte-identical across every still of every scene.\n\n"
        f"TASK: Write an SD3.5 prompt for ONE static image showing {primary_char.canonical_name} "
        f"alone performing the action above"
        f"{' WITH the product in frame as described' if product else ''}. "
        f"Lead with the ACTION + POSE + FRAMING, then the character description"
        f"{', then the product description (visual only — no brand name, no logo, no rendered text)' if product else ''}. "
        f"Describe ONLY the character{' + product' if product else ''} and their pose/action — "
        f"NOT clothing, NOT environment, NOT background, NOT lighting, NOT time of day, NOT cinematography "
        f"(clothing is spliced in by the system; the rest comes from the separate background plate). "
        f"Apply the FRAMING / POSE guards above verbatim. The still will be background-removed."
    )


_TIMELINE_PATTERNS = (
    re.compile(r"\b\d+[-–]\d+\s*s\b[:\s]*", re.IGNORECASE),  # "0-2s:" / "1–3s "
    re.compile(r"\bsecond\s+\d+\s*[-–]?\s*\d*\b", re.IGNORECASE),
    re.compile(r"\bbeat\s+\d+\b", re.IGNORECASE),
    re.compile(r"\bprogression\s+beat\b[^.]*\.", re.IGNORECASE),
)
_SEQUENCE_CONNECTORS = (
    re.compile(r"\bthen\b", re.IGNORECASE),
    re.compile(r"\bas\s+(?:the|he|she|they|it)\b", re.IGNORECASE),
    re.compile(r"\bwhile\s+(?:the|he|she|they|it)\b", re.IGNORECASE),
    re.compile(r"\bbegins?\s+to\b", re.IGNORECASE),
    re.compile(r"\bcontinues?\s+to\b", re.IGNORECASE),
    re.compile(r"\bafter(?:wards?)?\b", re.IGNORECASE),
    re.compile(r"\bsubsequently\b", re.IGNORECASE),
)


def _strip_timeline_language(text: str) -> str:
    """Remove timeline / sequence connectors so the LLM sees one moment, not
    a video timeline. Keeps the rest of the action description intact."""
    if not text:
        return text
    out = text
    for pat in _TIMELINE_PATTERNS:
        out = pat.sub("", out)
    for pat in _SEQUENCE_CONNECTORS:
        out = pat.sub(",", out)
    out = re.sub(r"\s+", " ", out)
    out = re.sub(r"\s+([.,;:!?])", r"\1", out)
    return out.strip(" ,.")


_PORTRAIT_BIASING_NEG_TERMS = (
    "off-center", "off center", "offcenter",
    "cropped face", "cropped feet", "cropped body", "cropped",
)


def _canonical_outfit(char: Character) -> str:
    """The exact clothing string spliced into every action-still prompt for
    this character. Returned verbatim — no LLM paraphrase, no per-still drift.
    Falls back to a stable placeholder so all stills share one outfit even
    when clothing_description is missing."""
    return (char.clothing_description or "neutral everyday clothing").strip()


# Garment vocabulary the LLM is instructed to omit but sometimes leaks
# through. We strip it from the LLM result so the canonical outfit clause
# we splice in is the only clothing copy in the prompt.
_CLOTHING_PHRASE_RE = re.compile(
    r"\b(?:wearing|dressed in|clad in|in a|in an)\s+[^,.\n]{1,80}?(?=[,.\n]|$)",
    re.IGNORECASE,
)


def _strip_clothing_phrases(prompt: str) -> str:
    """Best-effort scrub of LLM-leaked clothing fragments (e.g. 'wearing a
    red windbreaker'). Conservative: only drops obvious 'wearing X / in a Y'
    fragments — leaves descriptive sentences without those connectors alone."""
    out = _CLOTHING_PHRASE_RE.sub("", prompt or "")
    out = re.sub(r"\s{2,}", " ", out)
    out = re.sub(r"\s+([.,;:!?])", r"\1", out)
    return out.strip(" ,.")


def _splice_outfit(prompt: str, outfit: str) -> str:
    """Strip any clothing the LLM leaked, then append the canonical outfit
    clause verbatim. Outfit is byte-identical across every still so SD3.5
    sees the same clothing tokens every time."""
    base = _strip_clothing_phrases(prompt)
    return f"{base.rstrip(', .')}, wearing {outfit}"


def _scrub_negative(neg: str) -> str:
    """Remove negative-prompt terms that bias SD3.5 toward a centered
    medium portrait — the failure mode we want to escape. The LLM is
    instructed to omit them, but it sometimes still emits them."""
    parts = [p.strip() for p in (neg or "").split(",")]
    cleaned = [
        p for p in parts
        if p and not any(t in p.lower() for t in _PORTRAIT_BIASING_NEG_TERMS)
    ]
    return ", ".join(cleaned)


async def build_scene_action_prompt(
    llm, scene, primary_char, story_summary: str = "",
    second_idx: int = 0, n_stills: int = 1,
    corrective_hint: str | None = None,
    product: Product | None = None, product_role: str | None = None,
) -> dict:
    """Returns dict: {prompt, negative}."""
    system_prompt = _load_template("scene_action_portrait.txt")
    user_message = _scene_action_user_message(
        scene, primary_char, story_summary, second_idx, n_stills,
        corrective_hint=corrective_hint,
        product=product, product_role=product_role,
    )

    outfit = _canonical_outfit(primary_char)
    try:
        result = await llm.complete_json(
            system_prompt=system_prompt, user_prompt=user_message, max_tokens=512,
        )
        action_prompt = result.get("action_prompt", "")
        if not action_prompt:
            raise ValueError("Empty action_prompt from LLM")
        return {
            "prompt": _splice_outfit(action_prompt, outfit),
            "negative": _scrub_negative(
                result.get("negative_prompt", GENERIC_NEGATIVE)
            ),
        }
    except Exception as e:
        logger.warning(
            "LLM action prompt failed for scene %d still %d, using fallback: %s",
            scene.order_index, second_idx, e,
        )
        action_desc = (scene.prompt.action_description if scene.prompt else "") or ""
        parts = [
            primary_char.physical_description or primary_char.canonical_name,
            action_desc or scene.visual_summary or "performing action",
        ]
        prompt = ", ".join(p.strip().rstrip(",") for p in parts if p.strip())
        return {
            "prompt": _splice_outfit(prompt, outfit) + QUALITY_SUFFIX,
            "negative": GENERIC_NEGATIVE,
        }
