"""Structural validators for ScenePrompt outputs from the visual director.

Run after every visual_director call. Failure → re-prompt with the failed
checks injected as corrective feedback.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

WORD_CAP = 320  # validator-reject ceiling. Target is ≈240 (see memory feedback_prompt_word_cap_220 — updated 2026-05-29). User wants richer prompts; cap is permissive because gpt-nano can't reliably stay under 260 when given rich bibles.
CANONICAL_NEGATIVES = {
    "text", "subtitles", "watermark", "logo", "letters",
    "static camera", "frozen", "jitter", "flickering",
    "blurry", "distorted",
}
# Words that, if present in the positive video_prompt, contradict the
# canonical negatives and produce on-screen text/logos LTX cannot render.
FORBIDDEN_IN_POSITIVE = {"logo", "watermark", "title card", "subtitle"}

# Match `0–1s`, `0-1s`, etc., regardless of what follows (a colon, a
# `[CharName]:` bracket, or whitespace). Keeping the regex liberal here
# lets the visual director use the per-second character attribution
# `[Farmer]:` syntax without tripping the validator.
_TIMESTAMP_RE = re.compile(r"(\d+)\s*[–\-]\s*(\d+)\s*s\b", re.IGNORECASE)


@dataclass
class ValidationReport:
    ok: bool
    errors: list[str]
    warnings: list[str]

    def as_feedback(self) -> str:
        return "; ".join(self.errors)


def _seconds_covered(text: str) -> set[int]:
    """Return the set of seconds for which the text has a `N–Ms:` marker."""
    out: set[int] = set()
    for a, b in _TIMESTAMP_RE.findall(text or ""):
        try:
            ai, bi = int(a), int(b)
        except ValueError:
            continue
        if bi == ai + 1:
            out.add(ai)
    return out


def _has_style_lock(video_prompt: str, style_lock: str) -> bool:
    if not style_lock:
        return True  # nothing to enforce
    # Match if any 3+ word phrase from the lock appears verbatim, case-insensitive.
    needle = style_lock.lower().strip().rstrip(".")
    hay = (video_prompt or "").lower()
    if needle and needle in hay:
        return True
    # Fallback: at least 60% of style_lock tokens (>3 chars) must appear.
    tokens = [t for t in re.split(r"[\s,]+", needle) if len(t) > 3]
    if not tokens:
        return True
    hits = sum(1 for t in tokens if t in hay)
    return hits / len(tokens) >= 0.6


def validate_scene_prompt(
    *,
    video_prompt: str,
    negative_prompt: str,
    scene_breakdown: str,
    duration_seconds: float,
    style_lock: str,
) -> ValidationReport:
    errors: list[str] = []
    warnings: list[str] = []

    vp = (video_prompt or "").strip()
    if not vp:
        errors.append("video_prompt is empty")
        return ValidationReport(ok=False, errors=errors, warnings=warnings)

    n_sec = max(1, round(duration_seconds))

    # Word cap
    wc = len(vp.split())
    if wc > WORD_CAP:
        errors.append(f"video_prompt has {wc} words; cap is {WORD_CAP}")

    # Per-second timestamp coverage in video_prompt
    covered = _seconds_covered(vp)
    missing = [i for i in range(n_sec) if i not in covered]
    if missing:
        errors.append(
            f"video_prompt missing per-second timestamps for second(s) "
            f"{missing} (expected 0–{n_sec - 1})"
        )

    # scene_breakdown coverage — count `N–Ms` markers in it. The visual
    # director sometimes emits the breakdown as one string with inline
    # timestamps and sometimes as newline-separated lines; both are fine
    # so long as every second is represented.
    sb_covered = _seconds_covered(scene_breakdown or "")
    sb_missing = [i for i in range(n_sec) if i not in sb_covered]
    if sb_missing:
        errors.append(
            f"scene_breakdown missing per-second markers for second(s) "
            f"{sb_missing} (need 0–{n_sec - 1})"
        )

    # Style-lock embedding
    if not _has_style_lock(vp, style_lock):
        errors.append(
            f"video_prompt does not embed the project style_lock (\"{style_lock}\")"
        )

    # Negative prompt canonical anti-list coverage
    neg_lower = (negative_prompt or "").lower()
    missing_neg = [t for t in CANONICAL_NEGATIVES if t not in neg_lower]
    if missing_neg:
        errors.append(
            f"negative_prompt missing canonical terms: {sorted(missing_neg)}"
        )

    # Positive/negative contradiction
    vp_lower = vp.lower()
    overlap = [t for t in FORBIDDEN_IN_POSITIVE if t in vp_lower]
    if overlap:
        errors.append(
            f"video_prompt references on-screen text/logo terms {overlap} "
            f"that are simultaneously negated. Remove them."
        )

    return ValidationReport(ok=not errors, errors=errors, warnings=warnings)
