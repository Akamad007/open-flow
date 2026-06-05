"""Tests for motion-aware step / CFG / negative-prompt tuning in Wan22VideoProvider.

Background: empirical analysis (docs/runs/wan22-eval/MOTION_FACE_PRESERVATION_OPTIONS.md)
found that running-character scenes drift in identity within a single 5s clip.
The provider now bumps inference steps + CFG and injects face-distortion
negative-prompt guardrails for motion-heavy scene types only.

These are pure-function tests on `_tune_for_motion` + `_is_motion_scene`. They
don't invoke the subprocess.
"""

from __future__ import annotations

import pytest

from app.providers.video import wan22_provider as p


# ──────────────── _is_motion_scene ────────────────

@pytest.mark.parametrize("scene_type", [
    "action_running",
    "walking_locomotion",
    "dancing_high_motion",
    "dramatic_cinematic_war",
])
def test_motion_scenes_are_flagged(scene_type):
    assert p._is_motion_scene(scene_type) is True


@pytest.mark.parametrize("scene_type", [
    "closeup_portrait",
    "closeup_with_fx",
    "editorial_fashion",
    "historical_period",
    "water_splash_fx",
    "crowd_mass_scene",
])
def test_static_scenes_are_not_flagged(scene_type):
    assert p._is_motion_scene(scene_type) is False


def test_unknown_scene_type_is_not_flagged():
    """Defensive default: an unrecognised scene_type does NOT get the motion
    bump (would waste 37% inference time on the wrong shots)."""
    assert p._is_motion_scene("totally_made_up") is False


# ──────────────── _tune_for_motion: motion path ────────────────

def test_motion_scene_bumps_steps_by_configured_delta():
    """Motion scenes add `_MOTION_STEP_BUMP` steps on top of the caller value.
    The bump was +40 historically; it is currently 0 (base is 140 directly, per
    the 2026-05-27 decision), so the test tracks the constant, not a literal."""
    steps, cfg, neg = p._tune_for_motion("action_running", 60, 5.0, "")
    assert steps == 60 + p._MOTION_STEP_BUMP


def test_motion_scene_bumps_cfg_by_one():
    steps, cfg, neg = p._tune_for_motion("walking_locomotion", 60, 5.0, "")
    assert cfg == pytest.approx(6.0), "motion scenes should bump CFG 5.0 -> 6.0"


def test_motion_bumps_apply_on_top_of_caller_values():
    """The deltas are additive on top of caller values:
    steps += _MOTION_STEP_BUMP, cfg += _MOTION_CFG_DELTA."""
    steps, cfg, _ = p._tune_for_motion("dancing_high_motion", 70, 5.5, "")
    assert steps == 70 + p._MOTION_STEP_BUMP
    assert cfg == pytest.approx(5.5 + p._MOTION_CFG_DELTA)


# ──────────────── _tune_for_motion: static path ────────────────

def test_static_scene_keeps_steps_unchanged():
    steps, cfg, _ = p._tune_for_motion("closeup_portrait", 40, 5.0, "")
    assert steps == 40
    assert cfg == pytest.approx(5.0)


def test_static_scene_keeps_cfg_unchanged():
    steps, cfg, _ = p._tune_for_motion("water_splash_fx", 40, 5.0, "")
    assert cfg == pytest.approx(5.0)


# ──────────────── negative-prompt baseline ────────────────

def test_face_negative_baseline_always_appended_when_caller_empty():
    _, _, neg = p._tune_for_motion("closeup_portrait", 40, 5.0, "")
    assert "warped face" in neg
    assert "fused fingers" in neg
    assert "drifting identity" in neg


def test_face_negative_baseline_appended_to_caller_negatives():
    """Caller-supplied negatives must be PRESERVED — guardrails layer on top."""
    _, _, neg = p._tune_for_motion(
        "action_running", 40, 5.0, "low quality, bad anatomy",
    )
    assert "low quality, bad anatomy" in neg
    assert "warped face" in neg
    # caller's content comes first so it doesn't get squeezed out by truncation
    assert neg.index("low quality") < neg.index("warped face")


def test_face_negative_baseline_present_for_motion_and_static_alike():
    """The negative guardrails are always-on regardless of motion flag — they
    cost nothing and help both motion and static face shots."""
    _, _, motion_neg = p._tune_for_motion("action_running", 40, 5.0, "")
    _, _, static_neg = p._tune_for_motion("closeup_portrait", 40, 5.0, "")
    assert "warped face" in motion_neg
    assert "warped face" in static_neg


def test_whitespace_only_caller_negative_treated_as_empty():
    _, _, neg = p._tune_for_motion("action_running", 40, 5.0, "   ")
    # Should not start with ", " (leading comma from concat with stripped empty)
    assert not neg.startswith(",")
    assert "warped face" in neg


# ──────────────── stability / invariants ────────────────

def test_function_is_pure_no_global_mutation():
    """Calling repeatedly must not change the constants — this guards against
    accidental in-place mutation of MOTION_SCENE_TYPES or the negative baseline."""
    before = (set(p.MOTION_SCENE_TYPES), p._FACE_NEGATIVE_BASELINE)
    for _ in range(5):
        p._tune_for_motion("action_running", 40, 5.0, "x")
        p._tune_for_motion("closeup_portrait", 40, 5.0, "y")
    after = (set(p.MOTION_SCENE_TYPES), p._FACE_NEGATIVE_BASELINE)
    assert before == after


def test_motion_scene_types_are_all_in_catalog():
    """Every MOTION_SCENE_TYPE entry must also be a real scene_type in the
    catalog yaml — guards against typos that would silently never fire."""
    from app.providers.video.wan22_provider import _load_catalog
    catalog_scene_types = set(_load_catalog()["scene_map"].keys())
    for st in p.MOTION_SCENE_TYPES:
        assert st in catalog_scene_types, (
            f"{st!r} is in MOTION_SCENE_TYPES but missing from catalog scene_map"
        )
