"""Tests for image_pregen.uploads_link — label↔entity matcher + DB linking."""
from __future__ import annotations

import json
import uuid

import pytest

from app.agents.image_pregen.uploads_link import (
    label_matches_name, link_character_uploads, link_product_uploads,
)
from app.models.asset import Asset, AssetStatus, AssetType
from app.models.character import Character
from app.models.product import Product
from app.models.project import Project, ProjectStatus

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("label,name,expected", [
    ("Alice protagonist", "Alice", True),
    ("Alice", "Alice protagonist", True),
    ("ALICE", "alice", True),
    ("tan Birkin handbag", "Birkin Handbag", True),
    ("alice", "bob", False),
    ("", "Alice", False),
    ("Alice", "", False),
    (None, "Alice", False),
    ("A", "A", False),  # single-char tokens dropped
    ("Mr. Smith", "smith", True),  # punctuation stripped
])
async def test_label_matches_name(label, name, expected):
    assert label_matches_name(label, name) is expected


async def _new_project(db) -> Project:
    p = Project(title="t", original_story_text="s",
                status=ProjectStatus.draft, total_target_duration_seconds=10.0)
    db.add(p)
    await db.commit()
    return p


async def _new_upload_asset(db, project_id, asset_type, label) -> Asset:
    a = Asset(
        id=uuid.uuid4(), project_id=project_id, scene_id=None,
        asset_type=asset_type, file_path=f"storage/uploads/{project_id}/{label}.png",
        status=AssetStatus.complete, generation_provider="user_upload",
        metadata_json=json.dumps({"source": "user_upload", "label": label}),
    )
    db.add(a)
    await db.commit()
    return a


async def test_link_character_uploads_matches_by_label(db_session):
    p = await _new_project(db_session)
    asset = await _new_upload_asset(db_session, p.id, AssetType.character_ref, "Alice")
    char = Character(project_id=p.id, canonical_name="Alice", reference_image_path=None)
    db_session.add(char)
    await db_session.commit()

    n = await link_character_uploads(db_session, p.id, [char])

    assert n == 1
    assert char.reference_image_path == asset.file_path


async def test_link_character_uploads_skips_already_linked(db_session):
    p = await _new_project(db_session)
    await _new_upload_asset(db_session, p.id, AssetType.character_ref, "Alice")
    char = Character(project_id=p.id, canonical_name="Alice",
                     reference_image_path="storage/existing.png")
    db_session.add(char)
    await db_session.commit()

    n = await link_character_uploads(db_session, p.id, [char])

    assert n == 0
    assert char.reference_image_path == "storage/existing.png"


async def test_link_character_uploads_no_match_no_change(db_session):
    p = await _new_project(db_session)
    await _new_upload_asset(db_session, p.id, AssetType.character_ref, "Alice")
    char = Character(project_id=p.id, canonical_name="Bob", reference_image_path=None)
    db_session.add(char)
    await db_session.commit()

    n = await link_character_uploads(db_session, p.id, [char])

    assert n == 0
    assert char.reference_image_path is None


async def test_link_product_uploads_sets_user_uploaded_path(db_session):
    p = await _new_project(db_session)
    asset = await _new_upload_asset(db_session, p.id, AssetType.product_ref, "tan Birkin handbag")
    prod = Product(project_id=p.id, canonical_name="Birkin Handbag",
                   user_uploaded_path=None, reference_image_path=None)
    db_session.add(prod)
    await db_session.commit()

    n = await link_product_uploads(db_session, p.id, [prod])

    assert n == 1
    assert prod.user_uploaded_path == asset.file_path
    # reference_image_path NOT touched — the existing products.generate_all
    # path copies user_uploaded_path → reference_image_path itself.
    assert prod.reference_image_path is None


async def test_link_ignores_non_user_uploads(db_session):
    p = await _new_project(db_session)
    # Generation-provider != user_upload should be ignored.
    a = Asset(
        id=uuid.uuid4(), project_id=p.id, scene_id=None,
        asset_type=AssetType.character_ref, file_path="storage/gen.png",
        status=AssetStatus.complete, generation_provider="sd35",
        metadata_json=json.dumps({"label": "Alice"}),
    )
    db_session.add(a)
    char = Character(project_id=p.id, canonical_name="Alice", reference_image_path=None)
    db_session.add(char)
    await db_session.commit()

    n = await link_character_uploads(db_session, p.id, [char])

    assert n == 0
    assert char.reference_image_path is None
