"""Tests for Plan B identity-preservation wiring.

Pure unit tests — no GPU subprocess calls, no DB. We exercise the
provider abstraction, the embedding cache helper, and the routing
decision in action_stills.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from unittest.mock import patch

import pytest


# ── ImageProvider abstraction ──────────────────────────────────────────────

def test_image_provider_supports_identity_default_false():
    from app.providers.image.base import ImageProvider

    assert ImageProvider.supports_identity is False


def test_image_settings_has_identity_strength():
    from app.providers.image.base import ImageSettings

    s = ImageSettings()
    assert hasattr(s, "identity_strength")
    assert 0.0 <= s.identity_strength <= 1.0


def test_image_settings_has_pose_fields_for_dual_cn():
    from app.providers.image.base import ImageSettings

    s = ImageSettings()
    assert hasattr(s, "pose_image_path")
    assert hasattr(s, "pose_strength")
    assert s.pose_image_path is None
    assert 0.0 <= s.pose_strength <= 1.0
    s2 = ImageSettings(pose_image_path="/tmp/p.png", pose_strength=0.5)
    assert s2.pose_image_path == "/tmp/p.png"
    assert s2.pose_strength == 0.5


def test_instantid_pose_script_referenced():
    """The provider knows about both backends — face-only and dual-CN."""
    from app.providers.image.instantid_provider import (
        INSTANTID_POSE_SCRIPT, INSTANTID_SCRIPT,
    )
    assert "generate_instantid_pose.py" in str(INSTANTID_POSE_SCRIPT)
    assert "generate_instantid.py" in str(INSTANTID_SCRIPT)
    assert INSTANTID_POSE_SCRIPT != INSTANTID_SCRIPT


def test_identity_ref_dataclass():
    from app.providers.image.base import IdentityRef

    r = IdentityRef(portrait_path="/tmp/x.png", embedding_path="/tmp/x.idemb.pt")
    assert r.portrait_path == "/tmp/x.png"
    assert r.embedding_path == "/tmp/x.idemb.pt"


# ── InstantID provider class ───────────────────────────────────────────────

def test_instantid_provider_supports_identity():
    from app.providers.image.instantid_provider import InstantIDImageProvider

    assert InstantIDImageProvider.supports_identity is True


def test_instantid_falls_back_for_plain_generate():
    from app.providers.image.base import ImageProvider, ImageResult, ImageSettings
    from app.providers.image.instantid_provider import InstantIDImageProvider

    class FakeFallback(ImageProvider):
        async def generate_image(self, prompt, negative_prompt, output_path, settings=None):
            return ImageResult(success=True, file_path="/tmp/fake.png")

    p = InstantIDImageProvider(fallback=FakeFallback())
    res = asyncio.run(p.generate_image("x", "", Path("/tmp/x.png")))
    assert res.success and res.file_path == "/tmp/fake.png"


def test_instantid_no_fallback_errors_on_plain():
    from app.providers.image.instantid_provider import InstantIDImageProvider

    p = InstantIDImageProvider(fallback=None)
    res = asyncio.run(p.generate_image("x", "", Path("/tmp/x.png")))
    assert res.success is False
    assert "no fallback" in (res.error or "").lower()


# ── Embedding cache helper ─────────────────────────────────────────────────

def test_embedding_path_includes_encoder_version(tmp_path):
    from app.agents.image_pregen._identity import _embedding_path, ENCODER_VERSION

    portrait = tmp_path / "sadhguru.png"
    portrait.write_bytes(b"fake")
    p = _embedding_path(str(portrait))
    assert p.name == f"sadhguru.{ENCODER_VERSION}.idemb.pt"


def test_is_fresh_cache_miss(tmp_path):
    from app.agents.image_pregen._identity import _embedding_path, _is_fresh

    portrait = tmp_path / "x.png"
    portrait.write_bytes(b"a")
    emb = _embedding_path(str(portrait))
    assert _is_fresh(str(portrait), emb) is False


def test_is_fresh_cache_hit_after_write(tmp_path):
    from app.agents.image_pregen._identity import _embedding_path, _is_fresh

    portrait = tmp_path / "x.png"
    portrait.write_bytes(b"a")
    emb = _embedding_path(str(portrait))
    emb.write_bytes(b"emb")
    assert _is_fresh(str(portrait), emb) is True


def test_is_fresh_invalidated_when_portrait_newer(tmp_path):
    from app.agents.image_pregen._identity import _embedding_path, _is_fresh

    portrait = tmp_path / "x.png"
    portrait.write_bytes(b"a")
    emb = _embedding_path(str(portrait))
    emb.write_bytes(b"emb")
    # Portrait re-rendered AFTER the cache. mtime ordering: emb then portrait.
    time.sleep(0.01)
    portrait.write_bytes(b"b")
    assert _is_fresh(str(portrait), emb) is False


@pytest.mark.asyncio
async def test_get_or_create_identity_ref_missing_portrait_raises(tmp_path):
    from app.agents.image_pregen._identity import get_or_create_identity_ref

    with pytest.raises(FileNotFoundError):
        await get_or_create_identity_ref(str(tmp_path / "missing.png"))


@pytest.mark.asyncio
async def test_get_or_create_identity_ref_no_subprocess_returns_soft_ref(tmp_path):
    """When the GPU embedding extractor isn't installed, the helper must
    NOT raise — it returns a soft IdentityRef so the provider can
    re-extract on the GPU side."""
    from app.agents.image_pregen import _identity

    portrait = tmp_path / "x.png"
    portrait.write_bytes(b"fake")
    # Simulate the script being missing.
    with patch.object(_identity, "EMBED_SCRIPT", tmp_path / "no-such-script.py"):
        ref = await _identity.get_or_create_identity_ref(str(portrait))
    assert ref.portrait_path == str(portrait)
    assert ref.embedding_path.endswith(".idemb.pt")


# ── action_stills routing ──────────────────────────────────────────────────

def test_image_pregen_factory_falls_back_when_flag_off(monkeypatch):
    """get_identity_image_provider() must return the base SD3.5 provider
    when the feature flag is off — actions stills then fall through to
    the t2i path with no behavior change vs pre-Plan-B."""
    from app.config import settings
    from app.orchestration._common import get_identity_image_provider, get_image_provider

    monkeypatch.setattr(settings, "identity_provider_enabled", False)
    p = get_identity_image_provider()
    assert type(p).__name__ == type(get_image_provider()).__name__


def test_image_pregen_factory_falls_back_when_script_missing(monkeypatch, tmp_path):
    """Even with the flag on, a missing GPU subprocess must fall back to
    the base provider — never crash the pipeline."""
    from app.config import settings

    monkeypatch.setattr(settings, "identity_provider_enabled", True)
    # Point instantid_dir at an empty tmp dir so the scripts are "not found".
    monkeypatch.setattr(settings, "instantid_dir", str(tmp_path / "instantid"))
    from app.orchestration._common import get_identity_image_provider, get_image_provider

    p = get_identity_image_provider()
    assert type(p).__name__ == type(get_image_provider()).__name__


# ── pose-reference helper ────────────────────────────────────────────────

def test_pose_refs_prompt_wraps_action_in_full_body_template():
    """The deterministic pose-ref prompt MUST inject full-body framing
    cues so SD3.5 renders a head-to-toe pose ref the OpenPose detector
    can read."""
    from app.agents.image_pregen.pose_refs import _pose_prompt_for_scene

    class _Prompt:
        action_description = "kneeling and pressing soil with both hands"

    class _Scene:
        order_index = 0
        visual_summary = ""
        prompt = _Prompt()

    out = _pose_prompt_for_scene(_Scene())
    assert "full-body" in out.lower() or "head to toe" in out.lower()
    assert "both feet visible" in out.lower()
    assert "kneeling" in out.lower()
    assert "plain neutral" in out.lower()


def test_pose_refs_prompt_falls_back_when_no_action():
    from app.agents.image_pregen.pose_refs import _pose_prompt_for_scene

    class _Scene:
        order_index = 0
        visual_summary = None
        prompt = None

    out = _pose_prompt_for_scene(_Scene())
    assert "neutral pose" in out.lower()
    assert "head to toe" in out.lower()


# ── pose library ─────────────────────────────────────────────────────────

def test_pose_library_returns_none_when_empty(monkeypatch, tmp_path):
    from app.agents.image_pregen import pose_library
    from app.config import settings

    monkeypatch.setattr(settings, "storage_root", tmp_path)
    pose_library.reload()
    assert pose_library.match("running fast") is None


def test_pose_library_match_picks_highest_keyword_score(monkeypatch, tmp_path):
    """Manifest with 2 entries — the action text matches more keywords on
    the running entry than the standing entry, so running wins."""
    import json
    from app.agents.image_pregen import pose_library
    from app.config import settings

    monkeypatch.setattr(settings, "storage_root", tmp_path)
    lib = tmp_path / "pose_library"
    lib.mkdir()
    (lib / "running_side.png").write_bytes(b"x")
    (lib / "standing_neutral.png").write_bytes(b"x")
    (lib / "manifest.json").write_text(json.dumps([
        {"label": "standing_neutral", "photo": "standing_neutral.png",
         "keywords": ["standing", "neutral"]},
        {"label": "running_side", "photo": "running_side.png",
         "keywords": ["running", "run", "sprint", "jog"]},
    ]))
    pose_library.reload()

    hit = pose_library.match("the man is running fast at a sprint pace")
    assert hit is not None
    assert hit.label == "running_side"


def test_pose_library_skips_entries_with_missing_photo(monkeypatch, tmp_path):
    import json
    from app.agents.image_pregen import pose_library
    from app.config import settings

    monkeypatch.setattr(settings, "storage_root", tmp_path)
    lib = tmp_path / "pose_library"
    lib.mkdir()
    # Manifest references a photo that doesn't exist on disk.
    (lib / "manifest.json").write_text(json.dumps([
        {"label": "ghost", "photo": "ghost.png", "keywords": ["running"]},
    ]))
    pose_library.reload()

    assert pose_library.match("running") is None


def test_pose_library_stem_match_handles_verb_forms(monkeypatch, tmp_path):
    """'jumps' / 'jumping' / 'jumped' all stem to 'jump' and match a
    keyword 'jumping'. Bidirectional so 'meditate' matches 'meditating'."""
    import json
    from app.agents.image_pregen import pose_library
    from app.config import settings

    monkeypatch.setattr(settings, "storage_root", tmp_path)
    lib = tmp_path / "pose_library"
    lib.mkdir()
    for n in ("jump.png", "meditate.png"):
        (lib / n).write_bytes(b"x")
    (lib / "manifest.json").write_text(json.dumps([
        {"label": "jump", "photo": "jump.png", "keywords": ["jumping"]},
        {"label": "meditate", "photo": "meditate.png", "keywords": ["meditate"]},
    ]))
    pose_library.reload()

    assert pose_library.match("the man jumps high").label == "jump"
    assert pose_library.match("she jumped the fence").label == "jump"
    assert pose_library.match("kids meditating quietly").label == "meditate"


def test_pose_library_demographic_filter_routes_to_woman_kid_pools(monkeypatch, tmp_path):
    """When the action text says 'she' or 'kid', the lookup is restricted
    to entries whose label has the corresponding demographic prefix."""
    import json
    from app.agents.image_pregen import pose_library
    from app.config import settings

    monkeypatch.setattr(settings, "storage_root", tmp_path)
    lib = tmp_path / "pose_library"
    lib.mkdir()
    for n in ("running_side.png", "woman_running.png", "kid_running.png"):
        (lib / n).write_bytes(b"x")
    (lib / "manifest.json").write_text(json.dumps([
        {"label": "running_side", "photo": "running_side.png", "keywords": ["running"]},
        {"label": "woman_running", "photo": "woman_running.png", "keywords": ["running"]},
        {"label": "kid_running", "photo": "kid_running.png", "keywords": ["running"]},
    ]))
    pose_library.reload()

    assert pose_library.match("the man runs fast").label == "running_side"
    assert pose_library.match("she runs fast").label == "woman_running"
    assert pose_library.match("the kid runs fast").label == "kid_running"


def test_pose_library_stop_words_dont_falsely_match(monkeypatch, tmp_path):
    """Short stop words like 'to' must not bidi-prefix-match keyword
    tokens like 'toe' / 'touch' / 'top'."""
    import json
    from app.agents.image_pregen import pose_library
    from app.config import settings

    monkeypatch.setattr(settings, "storage_root", tmp_path)
    lib = tmp_path / "pose_library"
    lib.mkdir()
    for n in ("toe_touch.png", "speak.png"):
        (lib / n).write_bytes(b"x")
    (lib / "manifest.json").write_text(json.dumps([
        {"label": "toe_touch", "photo": "toe_touch.png", "keywords": ["toe touch"]},
        {"label": "speak", "photo": "speak.png", "keywords": ["speak"]},
    ]))
    pose_library.reload()

    # "speaks to the camera" should hit speak, NOT toe_touch (where the
    # 'to' in the text would bidi-prefix-match 'toe' and 'touch' if we
    # didn't filter stop words).
    assert pose_library.match("speaks to the camera").label == "speak"


def test_pose_library_short_kw_does_not_prefix_match_unrelated_text(monkeypatch, tmp_path):
    """Two-letter or three-letter keywords like 'hi' must not bidi-prefix-
    match common words like 'his fingers' / 'history'. Surfaced when a
    long descriptive action_description containing 'his fingers' was
    routed to waving_hello (kw 'hi') instead of kneeling_one_knee.

    Policy: prefix match requires both stems ≥4 chars; shorter keywords
    must match the text token exactly."""
    import json
    from app.agents.image_pregen import pose_library
    from app.config import settings

    monkeypatch.setattr(settings, "storage_root", tmp_path)
    lib = tmp_path / "pose_library"
    lib.mkdir()
    for n in ("waving.png", "kneeling.png"):
        (lib / n).write_bytes(b"x")
    (lib / "manifest.json").write_text(json.dumps([
        # Short kws that previously over-matched: 'hi' → 'his',
        # 'hello' → 'He', 'wave' → 'wears'.
        {"label": "waving", "photo": "waving.png",
         "keywords": ["wave", "waving", "hi", "hello", "greet"]},
        {"label": "kneeling", "photo": "kneeling.png",
         "keywords": ["kneel", "kneeling"]},
    ]))
    pose_library.reload()

    action = (
        "Sadhguru kneels on parched cracked earth. He lets dry soil "
        "sift through his fingers, addressing the camera urgently."
    )
    hit = pose_library.match(action)
    assert hit is not None
    assert hit.label == "kneeling", (
        f"Action contains 'kneels' but matched {hit.label!r}. "
        "'hi' must not prefix-match 'his', 'hello' must not prefix-match 'he'."
    )


def test_pose_library_stem_equivalent_keywords_score_once(monkeypatch, tmp_path):
    """Keywords that stem to the same signature ('stretches', 'stretching',
    'stretched') must score once per entry — otherwise an entry that lists
    redundant verb conjugations unfairly outranks an entry with a single
    canonical form, biasing the matcher toward whichever pool happened to
    be more verbose. Surfaced when 'stretching overhead' incorrectly
    routed to a women-pool entry over the neutral men-pool entry."""
    import json
    from app.agents.image_pregen import pose_library
    from app.config import settings

    monkeypatch.setattr(settings, "storage_root", tmp_path)
    lib = tmp_path / "pose_library"
    lib.mkdir()
    for n in ("canonical.png", "verbose.png"):
        (lib / n).write_bytes(b"x")
    (lib / "manifest.json").write_text(json.dumps([
        # Canonical: one stem ('stretch'), one specific kw ('overhead').
        {"label": "canonical", "photo": "canonical.png",
         "keywords": ["stretch", "overhead"]},
        # Verbose: three stem-equivalent variants of 'stretch'.
        {"label": "verbose", "photo": "verbose.png",
         "keywords": ["stretches", "stretching", "stretched"]},
    ]))
    pose_library.reload()

    # 'stretching overhead' matches both stems on canonical (score 2) and
    # only the stretch-stem on verbose (score 1 after dedupe, would be 3
    # without it). Canonical must win.
    assert pose_library.match("stretching overhead").label == "canonical"


# ── Character portrait full-body enforcement ────────────────────────────

def test_force_full_body_strips_cropping_terms_and_prefixes_framing():
    """The LLM that builds the SD3.5 portrait prompt sometimes emits
    'bust shot' / 'head and shoulders' / 'close-up' even when the
    template forbids them. _force_full_body must strip those terms and
    prepend the canonical full-body framing phrase deterministically."""
    from app.agents.image_pregen.prompts import _force_full_body

    out = _force_full_body(
        "a bust shot of a man with a beard, head-and-shoulders, close-up, "
        "wearing a white robe"
    )
    assert out.startswith("full-body portrait head to toe in frame")
    assert "bust" not in out.lower()
    assert "head-and-shoulders" not in out.lower()
    assert "close-up" not in out.lower()
    # The non-cropping content survives.
    assert "white robe" in out
    assert "beard" in out


def test_force_full_body_idempotent_on_already_full_body_prompt():
    from app.agents.image_pregen.prompts import _force_full_body

    src = "a man in a white robe and turban standing, neutral pose"
    out = _force_full_body(src)
    # Source text preserved.
    assert "white robe" in out
    assert "turban" in out
    # Prefix added exactly once.
    assert out.count("full-body portrait head to toe in frame") == 1


def test_is_full_body_portrait_rejects_torso_aspect_bbox(tmp_path):
    """A portrait whose foreground bbox is roughly square (head + shoulders
    + chest) must be rejected. A tall narrow bbox (full standing person)
    must be accepted."""
    from PIL import Image
    from app.agents.image_pregen.character_portraits import _is_full_body_portrait

    # Torso shot: bbox 600x600 in a 768x1280 canvas (aspect 1.0 — fail).
    torso = tmp_path / "torso.png"
    im = Image.new("RGBA", (768, 1280), (0, 0, 0, 0))
    for x in range(80, 680):
        for y in range(80, 680):
            im.putpixel((x, y), (200, 100, 50, 255))
    im.save(torso)
    ok, aspect = _is_full_body_portrait(str(torso))
    assert ok is False
    assert aspect < 2.0

    # Full body: bbox 240x1100 in a 768x1280 canvas (aspect ~4.6 — pass).
    full = tmp_path / "full.png"
    im2 = Image.new("RGBA", (768, 1280), (0, 0, 0, 0))
    for x in range(260, 500):
        for y in range(60, 1160):
            im2.putpixel((x, y), (200, 100, 50, 255))
    im2.save(full)
    ok2, aspect2 = _is_full_body_portrait(str(full))
    assert ok2 is True
    assert aspect2 > 3.0


def test_product_compositor_pastes_product_visible_in_character_frame(tmp_path):
    """The compositor takes a bg-removed character render + a bg-removed
    product hero and produces an RGBA PNG with both subjects visible.
    Without it, an "ohwx man holding cola" prompt rendered through
    InstantID dual-CN reliably lost the bottle entirely (no product
    conditioning signal). Verify role-based scaling and that the product
    actually lands inside the canvas."""
    from PIL import Image
    from app.utils.product_compositor import composite_product

    char_p = tmp_path / "char.png"
    prod_p = tmp_path / "prod.png"

    # Character: 768x1280 canvas, opaque green rectangle filling middle —
    # simulates a bg-removed standing person.
    char = Image.new("RGBA", (768, 1280), (0, 0, 0, 0))
    for x in range(260, 500):
        for y in range(60, 1160):
            char.putpixel((x, y), (50, 200, 50, 255))
    char.save(char_p)

    # Product: 256x512 canvas, opaque red rectangle filling middle —
    # simulates a bg-removed bottle.
    prod = Image.new("RGBA", (256, 512), (0, 0, 0, 0))
    for x in range(60, 200):
        for y in range(40, 472):
            prod.putpixel((x, y), (220, 30, 30, 255))
    prod.save(prod_p)

    # Hero role: product scale 0.55 → ~704px tall on a 1280 canvas.
    composite_product(char_p, prod_p, "hero")
    out_hero = Image.open(char_p).convert("RGBA")
    # Red pixels appear somewhere — product was pasted.
    px_hero = out_hero.load()
    found_red = any(
        px_hero[x, y][0] > 180 and px_hero[x, y][1] < 80 and px_hero[x, y][2] < 80
        for x in range(0, 768, 32) for y in range(0, 1280, 32)
    )
    assert found_red, "hero: red product pixels missing — composite failed"

    # Holding role: product scale 0.28 → product is smaller than hero.
    Image.new("RGBA", (768, 1280), (0, 0, 0, 0)).save(char_p)
    for x in range(260, 500):
        for y in range(60, 1160):
            char.putpixel((x, y), (50, 200, 50, 255))
    char.save(char_p)
    composite_product(char_p, prod_p, "holding")
    out_hold = Image.open(char_p).convert("RGBA")
    # Count red pixels — should be smaller area than hero.
    red_hold = sum(
        1 for x in range(0, 768, 8) for y in range(0, 1280, 8)
        if out_hold.getpixel((x, y))[0] > 180
        and out_hold.getpixel((x, y))[1] < 80
    )
    red_hero = sum(
        1 for x in range(0, 768, 8) for y in range(0, 1280, 8)
        if out_hero.getpixel((x, y))[0] > 180
        and out_hero.getpixel((x, y))[1] < 80
    )
    assert red_hold > 0, "holding: product missing"
    assert red_hold < red_hero, (
        f"holding scale must be smaller than hero "
        f"(got holding={red_hold} hero={red_hero})"
    )


def test_product_compositor_unknown_role_falls_back_to_holding(tmp_path):
    """A bogus role string must not blow up — falls back to 'holding'
    layout so the pipeline keeps producing output."""
    from PIL import Image
    from app.utils.product_compositor import composite_product, _ROLE_LAYOUT

    char_p = tmp_path / "c.png"
    prod_p = tmp_path / "p.png"
    Image.new("RGBA", (400, 600), (0, 200, 0, 255)).save(char_p)
    Image.new("RGBA", (200, 400), (200, 0, 0, 255)).save(prod_p)
    composite_product(char_p, prod_p, "garbage_role")
    # Output exists and is the canvas size (compositor doesn't crash).
    assert Image.open(char_p).size == (400, 600)
    assert "holding" in _ROLE_LAYOUT


def test_is_full_body_portrait_handles_non_rgba_gracefully(tmp_path):
    """If the image isn't RGBA (no alpha to judge), the critic must
    abstain (return ok=True) rather than reject everything."""
    from PIL import Image
    from app.agents.image_pregen.character_portraits import _is_full_body_portrait

    p = tmp_path / "plain.png"
    Image.new("RGB", (512, 512), (128, 128, 128)).save(p)
    ok, _ = _is_full_body_portrait(str(p))
    assert ok is True
