"""Tests for app.agents.audio_plan_validator.validate_audio_plan."""

from __future__ import annotations

from app.agents.audio_plan_validator import (
    WORDS_PER_SECOND,
    validate_audio_plan,
)


def _narration_for(seconds: float) -> str:
    """Generate a narration whose word count exactly matches the target."""
    return " ".join(["word"] * int(seconds * WORDS_PER_SECOND))


def _valid_plan(scene_durations, narration_text=None):
    target = sum(scene_durations)
    narration = narration_text if narration_text is not None else _narration_for(target)
    timing_map = []
    for i, dur in enumerate(scene_durations):
        timing_map.append({
            "scene_index": i,
            "audio_segment_start": 0.0,
            "audio_segment_end": dur,
            "transition_note": "",
        })
    return {
        "full_story_narration_text": narration,
        "full_story_dialogue_plan": "",
        "ambience_progression_notes": "",
        "sound_transition_notes": "",
        "timing_map": timing_map,
    }


def test_valid_plan_ok():
    durations = [3.0, 4.0]
    plan = _valid_plan(durations)
    report = validate_audio_plan(
        plan, target_duration_s=sum(durations), scene_durations=durations,
    )
    assert report.ok is True
    assert report.errors == []


def test_narration_outside_word_budget_errors():
    durations = [5.0, 5.0]
    target = sum(durations)
    # Target ~20 words at 2 wps; emit 50 words → 150% deviation.
    plan = _valid_plan(durations, narration_text=" ".join(["w"] * 50))
    report = validate_audio_plan(
        plan, target_duration_s=target, scene_durations=durations,
    )
    assert report.ok is False
    assert any("deviation" in e and "exceeds" in e for e in report.errors)


def test_transition_note_demanding_logo_errors_when_no_on_screen_text():
    durations = [4.0]
    plan = _valid_plan(durations)
    plan["timing_map"][0]["transition_note"] = "Save Soil logo appears at the end"
    report = validate_audio_plan(
        plan, target_duration_s=4.0, scene_durations=durations,
        no_on_screen_text=True,
    )
    assert report.ok is False
    assert any(
        "transition_note" in e and "on-screen text/logo" in e
        for e in report.errors
    )


def test_timing_map_missing_scene_index_errors():
    # 2 scenes declared but timing_map only covers scene 0.
    durations = [3.0, 3.0]
    plan = _valid_plan([3.0])  # builds timing_map for index 0 only
    # Match narration to combined target so word-budget gate passes.
    plan["full_story_narration_text"] = _narration_for(sum(durations))
    report = validate_audio_plan(
        plan, target_duration_s=sum(durations), scene_durations=durations,
    )
    assert report.ok is False
    assert any(
        "missing scene_index entries" in e and "1" in e for e in report.errors
    )


def test_timing_map_total_mismatch_errors():
    # Scene 0 should cover 5s but timing_map only spans 2s.
    durations = [5.0]
    plan = _valid_plan(durations)
    plan["timing_map"] = [{
        "scene_index": 0,
        "audio_segment_start": 0.0,
        "audio_segment_end": 2.0,
        "transition_note": "",
    }]
    report = validate_audio_plan(
        plan, target_duration_s=sum(durations), scene_durations=durations,
    )
    assert report.ok is False
    assert any(
        "scene 0" in e and "covered" in e and "scene duration" in e
        for e in report.errors
    )
