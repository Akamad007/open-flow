"""Tests for the product entity pipeline (Plan A).

Covers the pure-Python pieces that don't need the DB or LLM: validators,
prompt blocks, name-strip, and the model imports/relationships. DB-bound
behavior is exercised by the post-migration smoke run, not unit tests.
"""

from __future__ import annotations

import pytest


# ── Story analyst validation ────────────────────────────────────────────────

def test_validate_products_empty_returns_no_errors():
    from app.agents.story_analyst import _validate_products

    assert _validate_products([]) == []
    assert _validate_products(None) == []


def test_validate_products_cap_violated():
    from app.agents.story_analyst import _validate_products

    errs = _validate_products([
        {"canonical_name": "A", "physical_description": "x"},
        {"canonical_name": "B", "physical_description": "y"},
    ])
    assert errs and "cap is 1" in errs[0]


def test_validate_products_required_fields():
    from app.agents.story_analyst import _validate_products

    errs = _validate_products([{}])
    assert any("canonical_name is empty" in e for e in errs)
    assert any("physical_description is empty" in e for e in errs)


def test_validate_products_happy_path():
    from app.agents.story_analyst import _validate_products

    assert _validate_products([
        {"canonical_name": "RedFizz Cola", "physical_description": "frosted bottle"}
    ]) == []


# ── Visual director product block ──────────────────────────────────────────

def test_format_product_block_none():
    from app.agents.visual_director import _format_product_block

    out = _format_product_block(None, None)
    assert "no product" in out.lower()


def test_format_product_block_hero_role_phrasing():
    from app.agents.visual_director import _format_product_block

    out = _format_product_block(
        {
            "canonical_name": "RedFizz Cola Bottle",
            "physical_description": "frosted clear-glass bottle",
            "brand_marks": "red wraparound label band",
            "color_palette": "deep red, amber, silver",
        },
        "hero",
    )
    assert "RedFizz" in out
    assert "extreme close-up" in out
    assert "Role  : hero" in out


def test_format_product_block_holding_default():
    from app.agents.visual_director import _format_product_block

    out = _format_product_block({"canonical_name": "Phone"}, None)
    # Falls back to 'holding' role phrasing
    assert "grip" in out.lower() or "hold" in out.lower()


# ── SD3.5 action-prompt product block ──────────────────────────────────────

def test_action_product_block_empty_when_no_product():
    from app.agents.image_pregen.prompts import _product_block

    assert _product_block(None, None) == ""


def test_action_product_block_includes_brand_rule():
    from app.agents.image_pregen.prompts import _product_block

    class P:
        physical_description = "frosted glass bottle"
        brand_marks = "red label band"
        color_palette = "deep red"

    block = _product_block(P(), "hero")
    assert "PRODUCT IN FRAME" in block
    # The brand-name ban must be inline so the LLM can't miss it.
    assert "NEVER write the brand name" in block
    assert "rendered text" in block


# ── Model wiring ────────────────────────────────────────────────────────────

def test_product_model_exports():
    from app.models import Product, scene_products

    assert Product.__tablename__ == "products"
    cols = [c.name for c in scene_products.c]
    assert cols == ["scene_id", "product_id", "product_role", "shows_product"]


def test_scene_has_products_relationship():
    from app.models import Scene

    assert hasattr(Scene, "products")


def test_project_has_products_relationship():
    from app.models import Project

    assert hasattr(Project, "products")


def test_assettype_has_product_ref():
    from app.models.asset import AssetType

    assert AssetType.product_ref.value == "product_ref"


# ── Config field for img2img bake strength ─────────────────────────────────

def test_product_img2img_strength_in_safe_range():
    from app.config import settings

    # 0.55-0.7 is the calibration window from the plan.
    assert 0.5 <= settings.product_img2img_strength <= 0.8


# ── action_stills accepts the new product kwargs ──────────────────────────

@pytest.mark.asyncio
async def test_scene_action_user_message_with_product():
    from app.agents.image_pregen.prompts import _scene_action_user_message

    class _P:
        scene_breakdown = "0–1s: Maya kneels, hand sifting soil"

    class _Char:
        id = 1
        canonical_name = "Maya"
        physical_description = "South Indian male"
        clothing_description = "white robe and turban"

    class _Prod:
        physical_description = "frosted clear-glass bottle"
        brand_marks = "red wraparound label band"
        color_palette = "red, amber, silver"

    class _Scene:
        order_index = 0
        prompt = _P()
        characters = [_Char()]
        visual_summary = ""
        location = None

    msg = _scene_action_user_message(
        _Scene(), _Char(), "story summary", second_idx=0, n_stills=6,
        product=_Prod(), product_role="hero",
    )
    assert "PRODUCT IN FRAME" in msg
    assert "frosted clear-glass bottle" in msg
    assert "extreme close-up" in msg
