"""Tests for app.agents.scene_prompt_validator.validate_scene_prompt."""

from __future__ import annotations

from app.agents.scene_prompt_validator import (
    CANONICAL_NEGATIVES,
    WORD_CAP,
    validate_scene_prompt,
)


def _full_negative() -> str:
    return ", ".join(sorted(CANONICAL_NEGATIVES))


def _per_second_prompt(n: int, style_lock: str = "") -> str:
    """Build a video_prompt with `0–1s:`, `1–2s:` ... timestamps for n seconds."""
    parts = [f"{i}–{i + 1}s: subject acts naturally" for i in range(n)]
    if style_lock:
        parts.append(style_lock)
    return ". ".join(parts)


def test_timestamps_with_character_bracket_pass():
    """`0–1s [Farmer]: …` is the format the visual director emits when ≥2
    characters are in scene. The validator must accept it."""
    style_lock = "warm cinematic golden-hour palette"
    vp = (
        "0–1s [Farmer]: hands crumble soil. "
        "1–2s [Sadhguru]: walks across the field. "
        "2–3s [Sadhguru]: kneels and lifts soil. "
        f"{style_lock}."
    )
    sb = "\n".join(f"{i}–{i + 1}s [Sadhguru]: line {i}" for i in range(3))
    report = validate_scene_prompt(
        video_prompt=vp,
        negative_prompt=_full_negative(),
        scene_breakdown=sb,
        duration_seconds=3,
        style_lock=style_lock,
    )
    assert report.ok, report.errors


def test_valid_prompt_with_all_timestamps_and_style_lock_ok():
    style_lock = "warm cinematic golden-hour palette with soft grain"
    vp = _per_second_prompt(4, style_lock=style_lock)
    sb = "\n".join(f"{i}–{i + 1}s: line {i}" for i in range(4))
    report = validate_scene_prompt(
        video_prompt=vp,
        negative_prompt=_full_negative(),
        scene_breakdown=sb,
        duration_seconds=4.0,
        style_lock=style_lock,
    )
    assert report.ok is True
    assert report.errors == []


def test_missing_timestamps_reports_seconds():
    # 4-second scene but only seconds 0 and 1 covered
    vp = "0–1s: subject. 1–2s: subject continues. " + \
        "warm cinematic golden-hour palette with soft grain"
    sb = "\n".join(f"{i}–{i + 1}s: line {i}" for i in range(4))
    report = validate_scene_prompt(
        video_prompt=vp,
        negative_prompt=_full_negative(),
        scene_breakdown=sb,
        duration_seconds=4.0,
        style_lock="warm cinematic golden-hour palette with soft grain",
    )
    assert report.ok is False
    joined = " ".join(report.errors)
    assert "missing per-second timestamps" in joined
    assert "2" in joined and "3" in joined


def test_word_cap_exceeded_reports_error():
    style_lock = "warm cinematic golden-hour palette with soft grain"
    filler = " ".join(["word"] * (WORD_CAP + 50))
    vp = _per_second_prompt(4, style_lock=style_lock) + " " + filler
    sb = "\n".join(f"{i}–{i + 1}s: line {i}" for i in range(4))
    report = validate_scene_prompt(
        video_prompt=vp,
        negative_prompt=_full_negative(),
        scene_breakdown=sb,
        duration_seconds=4.0,
        style_lock=style_lock,
    )
    assert report.ok is False
    assert any(f"cap is {WORD_CAP}" in e for e in report.errors)


def test_negative_missing_canonical_terms_lists_them():
    style_lock = "warm cinematic golden-hour palette with soft grain"
    vp = _per_second_prompt(2, style_lock=style_lock)
    sb = "\n".join(f"line {i}" for i in range(2))
    report = validate_scene_prompt(
        video_prompt=vp,
        negative_prompt="text, blurry",  # most canonical terms absent
        scene_breakdown=sb,
        duration_seconds=2.0,
        style_lock=style_lock,
    )
    assert report.ok is False
    err_text = " ".join(report.errors)
    assert "missing canonical terms" in err_text
    # A few specific canonicals should appear in the listed-missing set.
    for term in ("watermark", "logo", "static camera", "frozen"):
        assert term in err_text


def test_positive_negative_contradiction_logo_in_video_prompt():
    style_lock = "warm cinematic golden-hour palette with soft grain"
    # 'logo' is forbidden in the positive prompt because the negative
    # forbids on-screen logos.
    vp = (
        "0–1s: subject acts. 1–2s: the company logo glows on screen. "
        + style_lock
    )
    sb = "line 0\nline 1"
    report = validate_scene_prompt(
        video_prompt=vp,
        negative_prompt=_full_negative(),
        scene_breakdown=sb,
        duration_seconds=2.0,
        style_lock=style_lock,
    )
    assert report.ok is False
    assert any("logo" in e and "negated" in e for e in report.errors)


def test_empty_style_lock_skips_style_lock_error():
    vp = _per_second_prompt(2)
    sb = "0–1s: line 0\n1–2s: line 1"
    report = validate_scene_prompt(
        video_prompt=vp,
        negative_prompt=_full_negative(),
        scene_breakdown=sb,
        duration_seconds=2.0,
        style_lock="",
    )
    # No style_lock-related error even though there's no anchor in vp.
    assert all("style_lock" not in e for e in report.errors)
    assert report.ok is True
