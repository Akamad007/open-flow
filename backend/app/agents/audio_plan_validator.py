"""Structural validators for the AudioDirectorAgent's output.

These run after the LLM call. Failures become re-prompt feedback; warnings
are surfaced to result_json so reviewers can see them in the UI.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Words/phrases that imply on-screen text/logos. The visual stage forbids
# these in the negative_prompt; the audio stage must not request them.
_TEXT_DEMANDS_RE = re.compile(
    r"\b(logo\s+appears|title\s+card|text\s+(appears|on\s+screen)|"
    r"caption|subtitle|on-screen\s+(logo|text|title))\b",
    re.IGNORECASE,
)

WORDS_PER_SECOND = 2.0  # 120 wpm
WORD_BUDGET_TOLERANCE = 0.20  # ±20%


@dataclass
class AudioPlanReport:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def as_feedback(self) -> str:
        return "; ".join(self.errors)


def _word_count(text: str) -> int:
    return len((text or "").split())


def _check_no_on_screen_text(plan: dict) -> list[str]:
    out: list[str] = []
    for field_name in ("full_story_narration_text", "full_story_dialogue_plan",
                       "ambience_progression_notes", "sound_transition_notes"):
        value = plan.get(field_name) or ""
        if _TEXT_DEMANDS_RE.search(value):
            out.append(
                f"{field_name} requests on-screen text/logo "
                f"(visual stage forbids this; remove or reword)"
            )
    for i, seg in enumerate(plan.get("timing_map") or []):
        if _TEXT_DEMANDS_RE.search(seg.get("transition_note") or ""):
            out.append(f"timing_map[{i}].transition_note requests on-screen text/logo")
    return out


def _check_timing_map(plan: dict, n_scenes: int,
                      scene_durations: list[float]) -> list[str]:
    tm = plan.get("timing_map") or []
    if not tm:
        return ["timing_map is missing or empty"]
    errors: list[str] = []

    # Per-scene coverage: every scene_index 0..n-1 must have ≥1 segment.
    seen_scenes = {seg.get("scene_index") for seg in tm}
    missing = [i for i in range(n_scenes) if i not in seen_scenes]
    if missing:
        errors.append(f"timing_map missing scene_index entries: {missing}")

    # Per-scene total window must match scene duration ±0.3s.
    sums: dict[int, float] = {}
    for seg in tm:
        i = seg.get("scene_index")
        s = float(seg.get("audio_segment_start") or 0)
        e = float(seg.get("audio_segment_end") or 0)
        if e <= s:
            errors.append(
                f"timing_map scene {i}: end ({e}) ≤ start ({s})"
            )
        sums[i] = sums.get(i, 0.0) + (e - s)
    for i, total in sums.items():
        if 0 <= i < n_scenes:
            expected = scene_durations[i]
            if abs(total - expected) > 0.3:
                errors.append(
                    f"timing_map scene {i}: covered {total:.2f}s; "
                    f"scene duration is {expected:.2f}s (max ±0.3s)"
                )
    return errors


def validate_audio_plan(
    plan: dict,
    *,
    target_duration_s: float,
    scene_durations: list[float],
    no_on_screen_text: bool = True,
) -> AudioPlanReport:
    errors: list[str] = []
    warnings: list[str] = []

    narration = plan.get("full_story_narration_text") or ""
    if not narration.strip():
        errors.append("full_story_narration_text is empty")
        return AudioPlanReport(ok=False, errors=errors, warnings=warnings)

    # Word-budget gate
    target_words = target_duration_s * WORDS_PER_SECOND
    actual_words = _word_count(narration)
    if target_words > 0:
        delta = abs(actual_words - target_words) / target_words
        if delta > WORD_BUDGET_TOLERANCE:
            errors.append(
                f"narration is {actual_words} words for {target_duration_s:.1f}s "
                f"target (~{int(target_words)} words at {WORDS_PER_SECOND} wps); "
                f"deviation {delta:.0%} exceeds ±{int(WORD_BUDGET_TOLERANCE * 100)}%"
            )

    # On-screen text contradiction
    if no_on_screen_text:
        errors.extend(_check_no_on_screen_text(plan))

    # Timing-map structural sanity
    errors.extend(_check_timing_map(plan, len(scene_durations), scene_durations))

    return AudioPlanReport(ok=not errors, errors=errors, warnings=warnings)
