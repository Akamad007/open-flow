"""Curated library of pre-rendered human pose-reference photos.

The library is a directory of generic-person, full-body, head-to-toe
photos under `storage/pose_library/`, each with a label and a list of
action keywords. Looking up a pose for a scene becomes a regex match
against the action description — no per-scene SD3.5 t2i call required.

Used by `pose_refs.generate_for_scene`: library hit → skip SD3.5 entirely;
miss → fall back to per-scene generation.

The library is built once by `backend/lora_training/build_pose_library.py`.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app.config import settings as cfg

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PoseEntry:
    label: str
    photo_path: Path
    keywords: tuple[str, ...]


_MANIFEST_NAME = "manifest.json"


def _library_dir() -> Path:
    return cfg.storage_root / "pose_library"


def _load_manifest() -> list[PoseEntry]:
    p = _library_dir() / _MANIFEST_NAME
    if not p.exists():
        return []
    try:
        raw = json.loads(p.read_text())
    except Exception as e:
        logger.warning("pose_library manifest unreadable: %s", e)
        return []
    out: list[PoseEntry] = []
    for row in raw:
        photo = _library_dir() / row["photo"]
        if not photo.exists():
            continue
        out.append(PoseEntry(
            label=row["label"],
            photo_path=photo,
            keywords=tuple(k.lower() for k in row.get("keywords", [])),
        ))
    return out


_CACHE: Optional[list[PoseEntry]] = None


def reload() -> None:
    """Reload the manifest (call after rebuilding the library)."""
    global _CACHE
    _CACHE = None


def _entries() -> list[PoseEntry]:
    global _CACHE
    if _CACHE is None:
        _CACHE = _load_manifest()
    return _CACHE


# Demographic detector — when the action text contains one of these
# tokens, lookup is restricted to entries whose label has the matching
# prefix. Falls back to all entries if no demographic-prefixed entry
# matches keywords.
_DEMO_SIGNALS = {
    "woman_": (
        "woman", "women", "she", "her", "girl", "lady", "female",
        "mom", "mother", "wife", "daughter",
    ),
    "kid_": (
        "kid", "kids", "child", "children", "boy", "girl", "young",
        "toddler", "baby", "son", "daughter",
    ),
}


def _demographic_prefix(text: str) -> Optional[str]:
    """Return 'woman_' or 'kid_' if the text strongly implies that
    demographic, else None. 'kid' wins over 'woman' if both signals
    present (e.g. 'young girl' is a kid)."""
    for prefix in ("kid_", "woman_"):
        for sig in _DEMO_SIGNALS[prefix]:
            if re.search(rf"\b{re.escape(sig)}\b", text):
                return prefix
    return None


_VERB_SUFFIX_RE = re.compile(r"(ing|ed|es|s)$")


def _stem(word: str) -> str:
    """Strip a trailing verb suffix and un-double the final consonant
    so 'sitting' → 'sit', 'running' → 'run', 'jumping' → 'jump',
    'leaps' → 'leap', 'watched' → 'watch'. Conservative: requires
    result ≥ 3 chars to avoid mangling short words like 'is' or 'as'."""
    s = _VERB_SUFFIX_RE.sub("", word)
    # Un-double trailing consonant pairs ("sitt" → "sit", "runn" → "run").
    if len(s) >= 4 and s[-1] == s[-2] and s[-1] not in "aeiou":
        s = s[:-1]
    return s if len(s) >= 3 else word


_TOKEN_RE = re.compile(r"\b[\w'-]+\b")
_STOP_WORDS = frozenset({
    # Articles, common prepositions, conjunctions, auxiliaries — these
    # frequently confuse the bidi-prefix matcher (e.g. "to" prefix-matches
    # "toe" and "touch", "in" matches "into" / "inside" / "instant").
    "a", "an", "the", "to", "of", "in", "on", "at", "by", "for", "with",
    "and", "or", "but", "is", "are", "was", "were", "be", "been", "as",
    "it", "its", "this", "that", "these", "those", "from", "into", "up",
    "down", "out", "over", "under", "off", "so",
})


def _stems(text: str) -> list[str]:
    """Tokenize, lowercase, stem, and drop short stop-words. Stop words
    bias the bidi-prefix matcher (e.g. 'to' would match 'toe' / 'touch')."""
    return [
        _stem(t) for t in _TOKEN_RE.findall(text.lower())
        if t not in _STOP_WORDS
    ]


_MIN_PREFIX_STEM_LEN = 4


def _stem_match(text_stem: str, kw_stem: str) -> bool:
    """Match policy: exact equality always counts. Prefix match (in either
    direction) only counts when BOTH stems are ≥4 chars — otherwise short
    keywords like 'hi' / 'hello' would prefix-match common words like
    'his' / 'he' and produce nonsense routing (kneeling action matched
    waving_hello because 'hi' ⊂ 'his fingers')."""
    if text_stem == kw_stem:
        return True
    if len(text_stem) < _MIN_PREFIX_STEM_LEN or len(kw_stem) < _MIN_PREFIX_STEM_LEN:
        return False
    return text_stem.startswith(kw_stem) or kw_stem.startswith(text_stem)


def _score(entry: PoseEntry, text: str) -> int:
    """Bidirectional stem-prefix scoring weighted by keyword specificity.

    Each keyword token must match SOME token in the text via _stem_match.
    Multi-word keywords require all tokens match (any order, any position
    — so 'kicks ball' hits 'kicks the ball'). Cross-form match is
    symmetric so 'meditate' ↔ 'meditating' work both directions.
    Single-word kw scores 1; n-word kw scores n.

    Stem-equivalent keywords within an entry score once, not N times —
    'stretches' / 'stretching' / 'stretched' all collapse to ('stretch',)
    so they do not unfairly outweigh entries that use a single canonical
    verb form."""
    text_stems = _stems(text)
    s = 0
    counted: set[tuple[str, ...]] = set()
    for kw in entry.keywords:
        kw_stems = tuple(_stems(kw))
        if not kw_stems or kw_stems in counted:
            continue
        weight = len(kw_stems)
        all_match = all(
            any(_stem_match(ts, ks) for ts in text_stems) for ks in kw_stems
        )
        if all_match:
            counted.add(kw_stems)
            s += weight
    return s


async def match_with_llm(action_text: str, llm) -> Optional[PoseEntry]:
    """LLM-driven pose selection. Sends the action description + the full
    list of available pose labels (with their keyword summaries) and asks
    the LLM to pick the single best label. Returns the matching PoseEntry
    on success, None on any failure — callers should fall back to the
    deterministic keyword matcher (`match`) when this returns None.

    Cost: ~1.5K input tokens per scene against the small LLM model
    (~$0.0005/scene with gpt-5.4-nano)."""
    entries = _entries()
    if not entries or not action_text.strip():
        return None

    label_lines = [
        f"- {e.label}: {', '.join(e.keywords[:8]) if e.keywords else '(no keywords)'}"
        for e in entries
    ]
    valid_labels = {e.label for e in entries}

    system_prompt = (
        "You select the best-matching pose label from a curated library given a scene action description. "
        "Pose labels are full-body human-pose photo references; pick the one whose physical action best "
        "represents what the subject is DOING in the scene (the primary verb / posture, not setting or "
        "clothing).\n\n"
        "Demographic-prefixed labels (woman_*, kid_*) are gender/age-specific. If the action clearly "
        "describes a woman or female subject, prefer woman_* when an equivalent exists; if a child, prefer "
        "kid_*; otherwise pick the generic (no-prefix) variant. If nothing fits well, choose the closest "
        "neutral standing/walking variant.\n\n"
        "Available pose labels (label: keyword summary):\n"
        + "\n".join(label_lines) + "\n\n"
        "Output STRICT JSON only: {\"label\": \"<chosen_label>\"} — no prose, no explanation."
    )
    user_message = f"Action description:\n{action_text.strip()}"

    try:
        result = await llm.complete_json(
            system_prompt=system_prompt, user_prompt=user_message, max_tokens=64,
        )
    except Exception as e:
        logger.warning("LLM pose-match request failed: %s", e)
        return None

    chosen = (result.get("label") or "").strip()
    if not chosen:
        return None
    if chosen not in valid_labels:
        logger.warning(
            "LLM picked unknown pose label '%s' (action=%r) — falling through",
            chosen, action_text[:80],
        )
        return None
    for e in entries:
        if e.label == chosen:
            return e
    return None


def match(action_text: str) -> Optional[PoseEntry]:
    """Return the pose-library entry whose keywords best match the
    action text. Demographic-aware: when the text contains gendered or
    age-specific cues ('she', 'kid', 'young girl'), the lookup is
    restricted to that demographic's entries before falling back to all
    entries. Returns None if nothing matches or the library is empty."""
    if not action_text:
        return None
    text = action_text.lower()
    demo = _demographic_prefix(text)

    def _best_in(pool: list[PoseEntry]) -> Optional[PoseEntry]:
        best: tuple[int, PoseEntry] | None = None
        for e in pool:
            sc = _score(e, text)
            if sc == 0:
                continue
            if best is None or sc > best[0]:
                best = (sc, e)
        return best[1] if best else None

    entries = _entries()
    if demo:
        scoped = [e for e in entries if e.label.startswith(demo)]
        hit = _best_in(scoped)
        if hit is not None:
            return hit
    # No demographic, or demographic pool had no keyword hit — fall back
    # to all entries.
    return _best_in(entries)
