"""Tests for character-aware I2V seed selection in scene_video.

Background: Wan22 I2V chains by seeding scene N with scene N-1's last frame.
Naively this fails when scene N-1 was an environmental shot (no character) or
featured a *different* character — the seed face pollutes scene N's identity.

`_pick_seed_scene_index` walks the prior scenes and picks the most recent one
that shares at least one character. These are pure-function tests; no DB.
"""

from __future__ import annotations

import pytest

from app.orchestration.stages.scene_video import _pick_seed_scene_index


# Sentinel character IDs (real ones are UUIDs; ints are fine for set ops)
SHIVAJI, AURANGZEB, SAMBHAJI, BIRBAL = 1, 2, 3, 4


# ──────────────── no-prior cases ────────────────

def test_no_prior_scenes_returns_none():
    assert _pick_seed_scene_index({SHIVAJI}, []) is None


def test_no_prior_scenes_with_empty_current_chars_also_none():
    assert _pick_seed_scene_index(set(), []) is None


# ──────────────── environmental current scene ────────────────

def test_environmental_current_falls_back_to_most_recent_prior():
    """If the current scene has no characters, there's no face to protect —
    use the immediately-prior scene for environmental continuity."""
    priors = [(3, {SHIVAJI}), (2, set()), (1, {AURANGZEB}), (0, {AURANGZEB})]
    assert _pick_seed_scene_index(set(), priors) == 3


# ──────────────── character match in immediate prior (common case) ────────────────

def test_returns_immediate_prior_when_it_shares_character():
    priors = [(2, {SHIVAJI}), (1, {SHIVAJI, AURANGZEB}), (0, {AURANGZEB})]
    assert _pick_seed_scene_index({SHIVAJI}, priors) == 2


# ──────────────── walk-back when intermediate scenes don't share ────────────────

def test_skips_environmental_intermediate_scene():
    """The bug this fixes: scene N is Shivaji, scene N-1 is an env basket
    shot (no characters). We must skip back to scene N-2 (Shivaji)."""
    priors = [
        (3, set()),            # environmental, no chars
        (2, {SHIVAJI}),        # Shivaji — the correct seed
        (1, {SAMBHAJI}),
        (0, {AURANGZEB}),
    ]
    assert _pick_seed_scene_index({SHIVAJI}, priors) == 2


def test_skips_different_character_intermediate_scene():
    """Scene N is Shivaji. Scene N-1 was Sambhaji (different character).
    We must skip back to find Shivaji rather than seed with Sambhaji's face."""
    priors = [
        (3, {SAMBHAJI}),
        (2, {AURANGZEB}),
        (1, {SHIVAJI}),       # the correct seed
        (0, {AURANGZEB}),
    ]
    assert _pick_seed_scene_index({SHIVAJI}, priors) == 1


def test_walks_back_multiple_steps():
    priors = [(4, set()), (3, {AURANGZEB}), (2, set()), (1, {SHIVAJI}), (0, set())]
    assert _pick_seed_scene_index({SHIVAJI}, priors) == 1


# ──────────────── multi-character scenes ────────────────

def test_picks_when_any_character_overlaps():
    """If the current scene has Shivaji + Sambhaji, and the prior had just
    Sambhaji, that's still a match — Sambhaji's identity is anchored."""
    priors = [(2, {AURANGZEB}), (1, {SAMBHAJI}), (0, {SHIVAJI})]
    assert _pick_seed_scene_index({SHIVAJI, SAMBHAJI}, priors) == 1


def test_prefers_most_recent_match_over_older_match():
    """If multiple priors share characters, take the most recent one
    (closest in time = least cumulative drift to bridge)."""
    priors = [
        (4, {SHIVAJI}),     # most recent Shivaji — should win
        (3, {AURANGZEB}),
        (2, {SHIVAJI}),     # older Shivaji — should NOT win
        (1, set()),
        (0, {SHIVAJI}),
    ]
    assert _pick_seed_scene_index({SHIVAJI}, priors) == 4


# ──────────────── no-match → cold T2V ────────────────

def test_returns_none_when_no_prior_shares_character():
    """Brand-new character with no anchor: better to render cold T2V than to
    seed with a wrong face."""
    priors = [(2, {AURANGZEB}), (1, {SAMBHAJI}), (0, {AURANGZEB})]
    assert _pick_seed_scene_index({BIRBAL}, priors) is None


def test_returns_none_when_all_priors_are_environmental_and_current_has_char():
    priors = [(2, set()), (1, set()), (0, set())]
    assert _pick_seed_scene_index({SHIVAJI}, priors) is None


# ──────────────── narrative shape sanity ────────────────

def test_typical_two_character_dialogue_shape():
    """Two-character alternating closeups (hero vs rival):
      0: rival closeup
      1: hero closeup
      2: rival closeup
      3: hero closeup
    Scene 3 (hero) should seed from scene 1 (last hero), not scene 2
    (rival) — this keeps each character's identity stable across alternation.
    """
    RIVAL, HERO = 10, 11
    priors_for_scene_3 = [(2, {RIVAL}), (1, {HERO}), (0, {RIVAL})]
    assert _pick_seed_scene_index({HERO}, priors_for_scene_3) == 1


def test_typical_escape_narrative_shape():
    """hist_04 Shivaji-Aurangzeb escape:
      0: Aurangzeb on throne (Aurangzeb)
      1: Shivaji kneeling (Shivaji, Aurangzeb)
      2: Sambhaji watching (Sambhaji)
      3: Baskets being filled (no character)
      4: Shivaji curled in basket (Shivaji)
    Scene 4 should seed from scene 1 (last Shivaji), skipping 2 (Sambhaji)
    and 3 (environmental)."""
    priors_for_scene_4 = [
        (3, set()),
        (2, {SAMBHAJI}),
        (1, {SHIVAJI, AURANGZEB}),
        (0, {AURANGZEB}),
    ]
    assert _pick_seed_scene_index({SHIVAJI}, priors_for_scene_4) == 1
