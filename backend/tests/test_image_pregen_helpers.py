"""Pure-function helpers extracted during the image_pregen_agent split."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agents.image_pregen import _assets, prompts
from app.agents.image_pregen._constants import GENERIC_NEGATIVE, QUALITY_SUFFIX


# ── _assets.safe_name ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("inp,expected", [
    ("Plain", "plain"),
    ("With Space", "with_space"),
    ("Comma, Period.", "comma__period_"),
    ("UPPER-CASE_words", "upper-case_words"),
    ("a/b\\c:d?", "a_b_c_d_"),
])
def test_safe_name(inp, expected):
    assert _assets.safe_name(inp) == expected


# ── prompts._moment_label ─────────────────────────────────────────────────────

def test_moment_label_single_still():
    assert prompts._moment_label(0, 1) == "peak action moment"


def test_moment_label_first_of_many():
    assert "scene entrance" in prompts._moment_label(0, 6)


def test_moment_label_last_of_many():
    label = prompts._moment_label(5, 6)
    assert "scene exit" in label and "second 5" in label


def test_moment_label_middle():
    label = prompts._moment_label(3, 6)
    assert "mid-scene" in label and "second 3 of 5" in label


# ── prompts._beat_hint ────────────────────────────────────────────────────────

def test_beat_hint_returns_empty_for_empty_input():
    assert prompts._beat_hint("", 0) == ""
    assert prompts._beat_hint(None, 0) == ""


def test_beat_hint_returns_indexed_line():
    breakdown = "first beat\nsecond beat\nthird beat"
    assert prompts._beat_hint(breakdown, 0) == "first beat"
    assert prompts._beat_hint(breakdown, 1) == "second beat"
    assert prompts._beat_hint(breakdown, 2) == "third beat"


def test_beat_hint_clamps_to_last_line():
    breakdown = "only beat"
    assert prompts._beat_hint(breakdown, 5) == "only beat"


def test_beat_hint_strips_blank_lines():
    breakdown = "\n  \nreal beat\n   "
    assert prompts._beat_hint(breakdown, 0) == "real beat"


# ── build_character_prompt — fallback path (LLM raises) ───────────────────────

class _BoomLLM:
    async def complete_json(self, *_, **__):
        raise RuntimeError("LLM down")


class _OKLLM:
    def __init__(self, response):
        self.response = response

    async def complete_json(self, *_, **__):
        return self.response


async def test_build_character_prompt_uses_llm_when_available():
    llm = _OKLLM({"portrait_prompt": "vivid prompt", "negative_prompt": "neg"})
    char = SimpleNamespace(
        canonical_name="Lena",
        physical_description="athletic",
        clothing_description="red windbreaker",
    )
    prompt, neg = await prompts.build_character_prompt(llm, char, story_summary="run story")
    # LLM body is preserved AND prefixed with the deterministic full-body
    # framing phrase to defeat SD3.5's torso-shot collapse.
    assert "vivid prompt" in prompt
    assert prompt.startswith("full-body portrait head to toe in frame")
    # Negative is augmented with the cropping guard so SD3.5 explicitly
    # avoids bust / waist-up framings even if the LLM negative is sparse.
    assert "neg" in neg
    assert "bust shot" in neg


async def test_build_character_prompt_falls_back_when_llm_fails():
    char = SimpleNamespace(
        canonical_name="Lena",
        physical_description="athletic",
        clothing_description="red windbreaker",
    )
    prompt, neg = await prompts.build_character_prompt(_BoomLLM(), char, story_summary="run")
    assert "Lena" in prompt
    assert "athletic" in prompt
    assert "red windbreaker" in prompt
    # Fallback also gets the framing prefix and the cropping-guard negative.
    assert prompt.startswith("full-body portrait head to toe in frame")
    assert GENERIC_NEGATIVE in neg
    assert "bust shot" in neg


async def test_build_character_prompt_falls_back_when_llm_returns_empty():
    char = SimpleNamespace(canonical_name="X", physical_description=None, clothing_description=None)
    prompt, neg = await prompts.build_character_prompt(
        _OKLLM({"portrait_prompt": "", "negative_prompt": "n"}), char, story_summary="",
    )
    assert "X" in prompt
    assert prompt.startswith("full-body portrait head to toe in frame")
    assert GENERIC_NEGATIVE in neg
    assert "bust shot" in neg


# ── build_background_prompt ───────────────────────────────────────────────────

async def test_build_background_prompt_uses_llm_when_available():
    llm = _OKLLM({"background_prompt": "wide shot", "negative_prompt": "no people"})
    loc = SimpleNamespace(name="Park", description="green hills")
    prompt, neg = await prompts.build_background_prompt(llm, loc, story_summary="any")
    # Deterministic framing prefix is prepended so SD3.5 doesn't render a
    # phantom subject we'll be compositing over.
    assert "landscape 16:9 cinematic establishing shot" in prompt
    assert "no people in frame" in prompt
    assert "wide shot" in prompt
    assert "no people" in neg
    assert "person" in neg  # explicit person ban in framing-negative


async def test_build_background_prompt_fallback_excludes_people():
    loc = SimpleNamespace(name="Park", description="green hills")
    prompt, neg = await prompts.build_background_prompt(_BoomLLM(), loc)
    assert "Park" in prompt
    assert "green hills" in prompt
    assert "no characters" in prompt
    assert "people" in neg and "human" in neg


# ── outfit-string lock ────────────────────────────────────────────────────────
# Action stills must wear byte-identical clothing across every still and
# every scene. The LLM is told not to describe clothing; the system splices
# the canonical outfit clause in deterministically.

def _scene_with_action(action: str = "kneeling and pouring soil"):
    p = SimpleNamespace(
        action_description=action,
        scene_breakdown=action,
        environment_description="",
    )
    return SimpleNamespace(
        order_index=0, prompt=p, characters=[], visual_summary="", location=None,
    )


def _char(clothing="red windbreaker over black tee, dark joggers, white trainers"):
    return SimpleNamespace(
        id=1,
        canonical_name="Lena",
        physical_description="athletic woman, short dark hair",
        clothing_description=clothing,
    )


async def test_action_prompt_appends_canonical_outfit_on_llm_success():
    llm = _OKLLM({"action_prompt": "Lena kneeling, full body in frame", "negative_prompt": "blurry"})
    out = await prompts.build_scene_action_prompt(llm, _scene_with_action(), _char())
    assert out["prompt"].endswith(
        "wearing red windbreaker over black tee, dark joggers, white trainers"
    )


async def test_action_prompt_strips_llm_leaked_clothing_then_splices_canonical():
    # LLM ignored the instruction and wrote 'wearing a green hoodie'; the
    # system must strip that and use the canonical outfit only.
    llm = _OKLLM({
        "action_prompt": "Lena kneeling on the ground, wearing a green hoodie and blue jeans",
        "negative_prompt": "blurry",
    })
    out = await prompts.build_scene_action_prompt(llm, _scene_with_action(), _char())
    assert "green hoodie" not in out["prompt"]
    assert "blue jeans" not in out["prompt"]
    assert out["prompt"].endswith(
        "wearing red windbreaker over black tee, dark joggers, white trainers"
    )


async def test_action_prompt_outfit_is_byte_identical_across_stills():
    # Same character, two different stills (different beats) — outfit clause
    # must be byte-identical. Different action_prompts from the LLM are fine;
    # the clothing tail must match exactly.
    char = _char()
    llm = _OKLLM({"action_prompt": "Lena standing tall", "negative_prompt": "blurry"})
    a = await prompts.build_scene_action_prompt(llm, _scene_with_action("standing"), char, second_idx=0)
    b = await prompts.build_scene_action_prompt(llm, _scene_with_action("walking"), char, second_idx=3)
    assert a["prompt"].split(", wearing ")[-1] == b["prompt"].split(", wearing ")[-1]


async def test_action_prompt_fallback_also_splices_canonical_outfit():
    out = await prompts.build_scene_action_prompt(_BoomLLM(), _scene_with_action(), _char())
    assert "wearing red windbreaker over black tee, dark joggers, white trainers" in out["prompt"]


async def test_action_prompt_uses_placeholder_when_clothing_missing():
    # Even when clothing_description is None, the SAME placeholder must
    # appear in every still so SD3.5 sees identical clothing tokens.
    llm = _OKLLM({"action_prompt": "Lena standing", "negative_prompt": ""})
    char = _char(clothing=None)
    a = await prompts.build_scene_action_prompt(llm, _scene_with_action(), char)
    b = await prompts.build_scene_action_prompt(llm, _scene_with_action("walking"), char)
    assert a["prompt"].endswith("wearing neutral everyday clothing")
    assert b["prompt"].endswith("wearing neutral everyday clothing")
