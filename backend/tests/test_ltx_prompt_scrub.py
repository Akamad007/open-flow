"""Pure tests for ltx_provider's framing scrub + far-camera prefix.

The LLM occasionally emits per-second beats that say "close-up" or
"medium shot" — when 6 such beats appear in one prompt, LTX follows
them and ignores the prefix. The scrub rewrites those terms to wide
language so every beat reads as wide.
"""

from __future__ import annotations

from app.providers.video import ltx_provider as lp


def test_scrub_replaces_close_up_variants():
    out = lp._scrub_tight_framing("locked-off low angle close-up")
    assert "close-up" not in out.lower()
    assert "wide shot full body" in out


def test_scrub_replaces_medium_close_up_and_medium_shot():
    assert "close-up" not in lp._scrub_tight_framing(
        "slow dolly-in to medium close-up"
    ).lower()
    assert "medium shot" not in lp._scrub_tight_framing(
        "static medium shot, tripod stable"
    ).lower()


def test_scrub_replaces_partial_body_crops():
    for src in ("head-to-knees visible", "head-to-waist", "waist-up", "chest-up"):
        out = lp._scrub_tight_framing(src)
        assert "wide shot full body" in out, src


def test_scrub_preserves_allowed_wide_language():
    """medium-wide / wide shot / full-body must NOT be rewritten."""
    for src in (
        "medium-wide static shot, tripod stable",
        "wide shot, full-body, both feet visible",
        "static wide shot, character centered head-to-toe",
    ):
        assert lp._scrub_tight_framing(src) == src, src


def test_scrub_handles_full_assembled_prompt():
    prompt = (
        "0–1s: She runs + locked-off low angle close-up. "
        "1–2s: She accelerates + medium close-up static hold. "
        "2–3s: She drives faster + medium-wide static shot."
    )
    out = lp._scrub_tight_framing(prompt)
    assert "close-up" not in out.lower()
    assert "medium close-up" not in out.lower()
    assert "medium-wide static shot" in out  # unchanged


def test_far_camera_prefix_has_explicit_lens_and_distance():
    p = lp._FAR_CAMERA_PREFIX.lower()
    assert "wide-angle" in p
    assert "feet" in p  # any ft-distance callout
    assert "lower-third" in p or "lower third" in p
    assert "long shot" in p or "establishing" in p


def test_scrub_replaces_camera_aware_verbs():
    for src in ("Looks up at camera", "looks towards the camera",
                "Holds gaze", "stares into the camera"):
        out = lp._scrub_tight_framing(src)
        assert "camera" not in out.lower() or "12 feet" in out, src
        assert "looks ahead" in out, src


def test_scrub_replaces_intimate_mood():
    assert "wide shot full body" in lp._scrub_tight_framing("Intimate confident mood")
    assert "intimate" not in lp._scrub_tight_framing("intimate framing").lower()


def test_negative_includes_close_up_penalties():
    n = lp._TEXT_ARTIFACT_NEGATIVE
    for term in ("close-up", "headshot", "bust shot", "medium close-up", "waist-up"):
        assert term in n, term
