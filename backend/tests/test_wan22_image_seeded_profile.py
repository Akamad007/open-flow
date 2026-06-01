"""Tests for the wan22_image_seeded profile + scene_video conditioning.

These guarantee the I2V wiring that makes user-uploaded refs flow into Wan22
output: profile flags + conditioning selector + provider plumbing.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from app.orchestration.profiles import PROFILES, get_profile
from app.orchestration.stages.scene_video import _select_conditioning


def test_wan22_image_seeded_profile_registered():
    assert "wan22_image_seeded" in PROFILES
    p = get_profile("wan22_image_seeded")
    assert p.video_provider == "wan22"
    # Profile generates char portrait + background (image_pregen_enabled=True),
    # but does NOT use per-scene action stills — scene 0 conditions Wan22 I2V
    # on the character portrait, scenes N>0 on the prior scene's last_frame.
    assert p.image_pregen_enabled is True
    assert p.pin_action_stills is False


def test_wan22_text_only_unchanged():
    """Adding the new profile must not regress the old one."""
    p = get_profile("wan22_text_only")
    assert p.video_provider == "wan22"
    assert p.image_pregen_enabled is False
    assert p.pin_action_stills is False


def _scene(order_index: int = 5):
    s = MagicMock()
    s.scene_ref_image_path = None
    s.order_index = order_index
    return s


def test_select_conditioning_scene_zero_uses_character_portrait():
    """Scene 0 of an image-seeded run conditions Wan22 I2V on the character
    portrait directly — the lever that lets uploaded refs flow into output."""
    cond, char, bg, ai = _select_conditioning(
        last_frame=None, background=None,
        action_images=[], character="/tmp/char.png",
        scene=_scene(order_index=0), use_action_still_as_condition=True,
    )
    assert cond == "/tmp/char.png"


def test_select_conditioning_legacy_path_unchanged():
    """LTX-style call (flag False) keeps last_frame as the condition image."""
    cond, _, _, _ = _select_conditioning(
        last_frame="/tmp/last.png", background=None,
        action_images=["/tmp/action.png"], character="/tmp/char.png",
        scene=_scene(), use_action_still_as_condition=False,
    )
    assert cond == "/tmp/last.png"


def test_select_conditioning_flag_set_but_no_action_still_falls_back():
    cond, _, _, _ = _select_conditioning(
        last_frame="/tmp/last.png", background=None,
        action_images=[], character=None,
        scene=_scene(), use_action_still_as_condition=True,
    )
    assert cond == "/tmp/last.png"


def test_select_conditioning_background_fallback():
    cond, _, _, _ = _select_conditioning(
        last_frame=None, background="/tmp/bg.png",
        action_images=[], character=None,
        scene=_scene(), use_action_still_as_condition=False,
    )
    assert cond == "/tmp/bg.png"
