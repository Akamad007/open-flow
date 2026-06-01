"""Tests for the private helpers in app.agents.story_analyst."""

from __future__ import annotations

from app.agents.story_analyst import (
    STYLE_LOCK_MAX_WORDS,
    _build_user_prompt,
    _validate_style_lock,
)


def test_validate_style_lock_empty_string_errors():
    errors = _validate_style_lock("")
    assert errors
    assert any("empty" in e for e in errors)


def test_validate_style_lock_whitespace_only_errors():
    errors = _validate_style_lock("   \n\t  ")
    assert errors
    assert any("empty" in e for e in errors)


def test_validate_style_lock_30_words_exceeds_cap():
    style_lock = " ".join(["word"] * 30)
    errors = _validate_style_lock(style_lock)
    assert errors
    msg = " ".join(errors)
    assert "30" in msg
    assert str(STYLE_LOCK_MAX_WORDS) in msg


def test_validate_style_lock_15_words_passes():
    style_lock = " ".join(["word"] * 15)
    errors = _validate_style_lock(style_lock)
    assert errors == []


def test_build_user_prompt_includes_target_duration_when_provided():
    prompt = _build_user_prompt(
        story_text="A farmer kneels in dry soil.",
        target_duration=12.5,
        corrective_hint=None,
    )
    assert "TARGET TOTAL DURATION" in prompt
    assert "12.5" in prompt


def test_build_user_prompt_omits_duration_block_when_none():
    # When target_duration is None, the leading "TARGET TOTAL DURATION: <N> seconds"
    # block (with concrete number) must not appear; the JSON template's
    # back-reference to the phrase is allowed.
    prompt = _build_user_prompt(
        story_text="Story.", target_duration=None, corrective_hint=None,
    )
    assert "TARGET TOTAL DURATION:" not in prompt
    assert "Pacing notes MUST describe how to fill" not in prompt


def test_build_user_prompt_includes_corrective_hint_when_provided():
    prompt = _build_user_prompt(
        story_text="Story.",
        target_duration=10.0,
        corrective_hint="style_lock too long",
    )
    assert "PREVIOUS ATTEMPT FAILED VALIDATION" in prompt
    assert "style_lock too long" in prompt


def test_build_user_prompt_omits_corrective_hint_when_none():
    prompt = _build_user_prompt(
        story_text="Story.", target_duration=10.0, corrective_hint=None,
    )
    assert "PREVIOUS ATTEMPT FAILED VALIDATION" not in prompt
