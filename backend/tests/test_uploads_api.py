"""Tests for /api/projects/{id}/uploads/{character,product} endpoints."""
from __future__ import annotations

import io
import json
import uuid

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport
from PIL import Image
from sqlalchemy import select

from app.models.asset import Asset, AssetType
from app.models.project import Project, ProjectStatus

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def client(db_engine):
    from app.main import app
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _project(db_session) -> Project:
    p = Project(title="t", original_story_text="s",
                status=ProjectStatus.draft, total_target_duration_seconds=10.0)
    db_session.add(p)
    await db_session.commit()
    return p


def _png_bytes(size=(640, 480), color="red") -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


async def test_upload_character_creates_asset(client, db_session):
    p = await _project(db_session)
    resp = await client.post(
        f"/api/projects/{p.id}/uploads/character",
        data={"label": "Alice"},
        files={"file": ("alice.png", _png_bytes(), "image/png")},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["asset_type"] == "character_ref"
    assert body["kind"] == "character"
    assert body["label"] == "Alice"
    assert body["source"] == "user_upload"
    asset = await db_session.get(Asset, uuid.UUID(body["asset_id"]))
    assert asset is not None
    assert asset.asset_type == AssetType.character_ref
    assert asset.generation_provider == "user_upload"
    md = json.loads(asset.metadata_json)
    assert md["label"] == "Alice"


async def test_upload_product_creates_asset(client, db_session):
    p = await _project(db_session)
    resp = await client.post(
        f"/api/projects/{p.id}/uploads/product",
        data={"label": "tan Birkin handbag"},
        files={"file": ("bag.png", _png_bytes(color="brown"), "image/png")},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["asset_type"] == "product_ref"
    assert body["kind"] == "product"


async def test_upload_character_and_product_are_distinct(client, db_session):
    p = await _project(db_session)
    await client.post(
        f"/api/projects/{p.id}/uploads/character",
        data={"label": "Alice"},
        files={"file": ("a.png", _png_bytes(), "image/png")},
    )
    await client.post(
        f"/api/projects/{p.id}/uploads/product",
        data={"label": "Birkin"},
        files={"file": ("b.png", _png_bytes(), "image/png")},
    )
    rows = (await db_session.execute(
        select(Asset).where(Asset.project_id == p.id)
    )).scalars().all()
    types = {a.asset_type for a in rows}
    assert AssetType.character_ref in types
    assert AssetType.product_ref in types


async def test_upload_missing_label_rejected(client, db_session):
    p = await _project(db_session)
    resp = await client.post(
        f"/api/projects/{p.id}/uploads/character",
        data={"label": ""},
        files={"file": ("x.png", _png_bytes(), "image/png")},
    )
    assert resp.status_code in (400, 422)


async def test_upload_rejects_non_image(client, db_session):
    p = await _project(db_session)
    resp = await client.post(
        f"/api/projects/{p.id}/uploads/character",
        data={"label": "Alice"},
        files={"file": ("a.txt", b"not an image", "text/plain")},
    )
    assert resp.status_code == 400


async def test_upload_unknown_project_404(client):
    fake = uuid.uuid4()
    resp = await client.post(
        f"/api/projects/{fake}/uploads/character",
        data={"label": "Alice"},
        files={"file": ("a.png", _png_bytes(), "image/png")},
    )
    assert resp.status_code == 404


async def test_list_uploads_returns_only_user_uploads(client, db_session):
    p = await _project(db_session)
    await client.post(
        f"/api/projects/{p.id}/uploads/character",
        data={"label": "Alice"},
        files={"file": ("a.png", _png_bytes(), "image/png")},
    )
    resp = await client.get(f"/api/projects/{p.id}/uploads")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["source"] == "user_upload"


async def test_delete_upload_removes_asset(client, db_session):
    p = await _project(db_session)
    create = await client.post(
        f"/api/projects/{p.id}/uploads/character",
        data={"label": "Alice"},
        files={"file": ("a.png", _png_bytes(), "image/png")},
    )
    aid = create.json()["asset_id"]
    delete = await client.delete(f"/api/projects/{p.id}/uploads/{aid}")
    assert delete.status_code == 204
    again = await client.delete(f"/api/projects/{p.id}/uploads/{aid}")
    assert again.status_code == 404


async def test_delete_refuses_non_user_upload(client, db_session):
    """SD3.5-generated assets must not be deletable via this endpoint."""
    p = await _project(db_session)
    a = Asset(
        id=uuid.uuid4(), project_id=p.id, scene_id=None,
        asset_type=AssetType.character_ref, file_path="storage/gen.png",
        generation_provider="sd35", metadata_json=json.dumps({"label": "x"}),
    )
    db_session.add(a)
    await db_session.commit()
    resp = await client.delete(f"/api/projects/{p.id}/uploads/{a.id}")
    assert resp.status_code == 403
