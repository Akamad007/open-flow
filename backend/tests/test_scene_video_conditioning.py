"""Pure logic tests for `_select_conditioning` — the scene 0 vs scene 1+ rules."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.orchestration.stages import scene_video


def _scene(scene_ref_path: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(scene_ref_image_path=scene_ref_path, order_index=1)


def test_last_frame_does_not_override_action_stills():
    """When the scene has its own action stills, KEEP them — don't let the
    previous scene's last_frame silently dominate. last_frame still flows
    through as `condition` for cross-scene continuity, but character +
    background + action stills are preserved as well.

    This was the root cause of the Save Soil "scenes 2-4 all look the same"
    bug: last_frame was returning early and suppressing every other input.
    """
    cond, char, bg, action = scene_video._select_conditioning(
        last_frame="/tmp/last.png",
        background="/tmp/bg.png",
        action_images=["/tmp/a.png", "/tmp/b.png"],
        character="/tmp/char.png",
        scene=_scene(),
    )
    assert cond == "/tmp/last.png"
    assert char == "/tmp/char.png"
    assert bg == "/tmp/bg.png"
    assert action == ["/tmp/a.png", "/tmp/b.png"]


def test_last_frame_used_alone_when_nothing_else_available():
    """If no character / no action stills / no background, last_frame is the
    sole conditioning input — that's the original cross-scene continuity path."""
    cond, char, bg, action = scene_video._select_conditioning(
        last_frame="/tmp/last.png",
        background=None,
        action_images=[],
        character=None,
        scene=_scene(),
    )
    assert cond == "/tmp/last.png"
    assert char is None
    assert bg is None
    assert action == []


def test_scene_zero_keeps_all_inputs_when_action_stills_present():
    """When the scene has action stills + character, those drive conditioning;
    bg is passed through separately to LTX, condition stays None (no last_frame)."""
    cond, char, bg, action = scene_video._select_conditioning(
        last_frame=None,
        background="/tmp/bg.png",
        action_images=["/tmp/a1.png"],
        character="/tmp/char.png",
        scene=_scene(),
    )
    assert cond is None
    assert char == "/tmp/char.png"
    assert bg == "/tmp/bg.png"
    assert action == ["/tmp/a1.png"]


def test_scene_zero_uses_bg_as_condition_when_no_char_no_actions():
    """If there's a bg but no character + no action stills, bg becomes the
    condition image (so LTX has SOMETHING to anchor on)."""
    cond, char, bg, action = scene_video._select_conditioning(
        last_frame=None,
        background="/tmp/bg.png",
        action_images=[],
        character=None,
        scene=_scene(),
    )
    assert cond == "/tmp/bg.png"
    assert char is None
    assert bg == "/tmp/bg.png"
    assert action == []


def test_falls_back_to_scene_ref_when_no_other_images(tmp_path):
    """No last frame, no bg, no character, no action → use scene_ref if it exists."""
    ref = tmp_path / "ref.png"
    ref.write_bytes(b"fake")

    cond, char, bg, action = scene_video._select_conditioning(
        last_frame=None,
        background=None,
        action_images=[],
        character=None,
        scene=_scene(scene_ref_path=str(ref)),
    )
    assert cond == str(ref)
    assert char is None
    assert bg is None
    assert action == []


def test_scene_ref_ignored_if_missing_on_disk():
    cond, _, _, _ = scene_video._select_conditioning(
        last_frame=None, background=None, action_images=[], character=None,
        scene=_scene(scene_ref_path="/nonexistent/ref.png"),
    )
    assert cond is None


def test_keeps_char_and_action_when_no_bg_and_no_last_frame():
    """Edge case: only character/action images present (no bg, no last frame).
    Returns condition=None but keeps the rest so generate_scene_video can use them."""
    cond, char, bg, action = scene_video._select_conditioning(
        last_frame=None,
        background=None,
        action_images=["/tmp/a.png"],
        character="/tmp/c.png",
        scene=_scene(),
    )
    assert cond is None
    assert char == "/tmp/c.png"
    assert bg is None
    assert action == ["/tmp/a.png"]
