"""Tests for `_adjust_last_frame` — the last-frame chain drop/keep decision.

Covers the bug where wan22_text_only's last-frame chain was being silently
nulled on every scene because the "environmental scene" branch fired any
time char/stills were missing — but for text-only profiles they're missing
*by design*, not by accident.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.orchestration.profiles import get_profile
from app.orchestration.stages import scene_video


def _profile(**overrides):
    base = dict(
        canonical_portrait_enabled=False,
        image_pregen_enabled=False,
        drop_last_frame_on_tail=False,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


# ---------------- no last_frame at all ----------------

def test_returns_none_when_no_last_frame():
    p = _profile()
    assert scene_video._adjust_last_frame(p, 1, None, None, []) is None


# ---------------- tail drop ----------------

def test_tail_drop_kicks_in_at_scene_3_when_enabled():
    p = _profile(drop_last_frame_on_tail=True)
    assert scene_video._adjust_last_frame(p, 3, "/tmp/last.png", None, []) is None
    assert scene_video._adjust_last_frame(p, 4, "/tmp/last.png", None, []) is None


def test_tail_drop_does_not_kick_in_before_scene_3():
    p = _profile(drop_last_frame_on_tail=True)
    assert scene_video._adjust_last_frame(p, 1, "/tmp/last.png", None, []) == "/tmp/last.png"
    assert scene_video._adjust_last_frame(p, 2, "/tmp/last.png", None, []) == "/tmp/last.png"


def test_tail_drop_disabled_keeps_chain_through_late_scenes():
    """With tail-drop disabled the chain is kept for every scene — including
    deep into the episode. LoRA picks + per-scene prompts handle drift."""
    p = _profile(drop_last_frame_on_tail=False)
    assert scene_video._adjust_last_frame(p, 4, "/tmp/last.png", None, []) == "/tmp/last.png"
    assert scene_video._adjust_last_frame(p, 9, "/tmp/last.png", None, []) == "/tmp/last.png"
    assert scene_video._adjust_last_frame(p, 20, "/tmp/last.png", None, []) == "/tmp/last.png"


# ---------------- environmental drop ----------------

def test_text_only_profile_does_not_drop_when_char_and_stills_absent():
    """The core bug fix: wan22_text_only disables char + stills by design.
    Absence is not a 'environmental' signal — keep the chain."""
    p = _profile(canonical_portrait_enabled=False, image_pregen_enabled=False)
    assert scene_video._adjust_last_frame(p, 1, "/tmp/last.png", None, []) == "/tmp/last.png"


def test_profile_expecting_char_drops_when_char_missing():
    p = _profile(canonical_portrait_enabled=True)
    assert scene_video._adjust_last_frame(p, 1, "/tmp/last.png", None, []) is None


def test_profile_expecting_stills_drops_when_stills_missing():
    p = _profile(image_pregen_enabled=True)
    assert scene_video._adjust_last_frame(p, 1, "/tmp/last.png", None, []) is None


def test_profile_expecting_char_keeps_chain_when_char_present():
    p = _profile(canonical_portrait_enabled=True)
    got = scene_video._adjust_last_frame(p, 1, "/tmp/last.png", "/tmp/c.png", [])
    assert got == "/tmp/last.png"


def test_profile_expecting_stills_keeps_chain_when_stills_present():
    p = _profile(image_pregen_enabled=True)
    got = scene_video._adjust_last_frame(p, 1, "/tmp/last.png", None, ["/tmp/a.png"])
    assert got == "/tmp/last.png"


# ---------------- combined ----------------

def test_tail_drop_takes_precedence_over_keep_signal():
    p = _profile(drop_last_frame_on_tail=True, canonical_portrait_enabled=True)
    got = scene_video._adjust_last_frame(p, 3, "/tmp/last.png", "/tmp/c.png", [])
    assert got is None


# ---------------- profile-level wiring ----------------

def test_wan22_text_only_profile_keeps_chain_for_all_5_scenes():
    """End-to-end profile wiring check: a 5-scene wan22_text_only ad should
    pass last_frame through on every scene index 1..4 (scene 0 has no prev)."""
    p = get_profile("wan22_text_only")
    for i in range(1, 5):
        got = scene_video._adjust_last_frame(p, i, "/tmp/last.png", None, [])
        assert got == "/tmp/last.png", f"scene {i} unexpectedly dropped"


def test_ltx_profile_still_drops_tail_and_environmental():
    """Regression guard: ltx_text_only must still drop the chain at tail."""
    p = get_profile("ltx_text_only")
    assert p.drop_last_frame_on_tail is True
    assert scene_video._adjust_last_frame(p, 3, "/tmp/last.png", None, []) is None


def test_wan22_text_only_profile_flags():
    """Profile-level invariants the chain-keep behavior depends on."""
    p = get_profile("wan22_text_only")
    assert p.pin_last_frame_chain is True
    assert p.drop_last_frame_on_tail is False
    assert p.canonical_portrait_enabled is False
    assert p.image_pregen_enabled is False
