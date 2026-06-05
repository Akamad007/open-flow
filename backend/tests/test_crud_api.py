"""CRUD endpoint tests for characters / locations / products / scenes —
the create + delete endpoints that make the app fully API-driven."""

from __future__ import annotations

import uuid

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport

from app.models.episode import Episode
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


async def _project_with_episode(db_session) -> Project:
    p = await _project(db_session)
    db_session.add(Episode(project_id=p.id, order_index=0))
    await db_session.commit()
    return p


@pytest.mark.parametrize("resource,payload,name_field", [
    ("characters", {"canonical_name": "Alice"}, "canonical_name"),
    ("locations", {"name": "Forest"}, "name"),
    ("products", {"canonical_name": "Widget"}, "canonical_name"),
])
async def test_create_list_get_delete(client, db_session, resource, payload, name_field):
    p = await _project(db_session)

    r = await client.post(f"/api/projects/{p.id}/{resource}", json=payload)
    assert r.status_code == 201, r.text
    obj = r.json()
    assert obj[name_field] == payload[name_field]
    assert obj["project_id"] == str(p.id)
    oid = obj["id"]

    r = await client.get(f"/api/projects/{p.id}/{resource}")
    assert r.status_code == 200
    assert any(o["id"] == oid for o in r.json())

    r = await client.get(f"/api/{resource}/{oid}")
    assert r.status_code == 200

    r = await client.delete(f"/api/{resource}/{oid}")
    assert r.status_code == 204

    r = await client.get(f"/api/{resource}/{oid}")
    assert r.status_code == 404


@pytest.mark.parametrize("resource,payload", [
    ("characters", {"canonical_name": "X"}),
    ("locations", {"name": "X"}),
    ("products", {"canonical_name": "X"}),
    ("scenes", {}),
])
async def test_create_on_missing_project_returns_404(client, resource, payload):
    r = await client.post(f"/api/projects/{uuid.uuid4()}/{resource}", json=payload)
    assert r.status_code == 404, r.text


async def test_scene_create_requires_active_episode(client, db_session):
    p = await _project(db_session)  # project with no episode
    r = await client.post(f"/api/projects/{p.id}/scenes", json={})
    assert r.status_code == 400, r.text


async def test_scene_create_list_delete(client, db_session):
    p = await _project_with_episode(db_session)

    r = await client.post(f"/api/projects/{p.id}/scenes", json={"order_index": 0, "duration_seconds": 5.0})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["duration_seconds"] == 5.0
    sid = body["id"]

    r = await client.get(f"/api/projects/{p.id}/scenes")
    assert any(s["id"] == sid for s in r.json())

    r = await client.delete(f"/api/scenes/{sid}")
    assert r.status_code == 204

    r = await client.get(f"/api/scenes/{sid}")
    assert r.status_code == 404


async def test_scene_create_appends_order_index(client, db_session):
    """Repeated adds append to the end of the episode instead of colliding on 0."""
    p = await _project_with_episode(db_session)
    idxs = []
    for _ in range(3):
        r = await client.post(f"/api/projects/{p.id}/scenes", json={"order_index": 0})
        assert r.status_code == 201, r.text
        idxs.append(r.json()["order_index"])
    assert idxs == sorted(idxs) and len(set(idxs)) == 3, idxs


async def test_scene_create_explicit_episode(client, db_session):
    p = await _project_with_episode(db_session)
    ep_id = (await client.get(f"/api/projects/{p.id}/episodes")).json()[0]["id"]
    r = await client.post(f"/api/projects/{p.id}/scenes", json={"episode_id": ep_id})
    assert r.status_code == 201, r.text
    assert r.json()["episode_id"] == ep_id


async def test_scene_create_foreign_episode_rejected(client, db_session):
    p = await _project_with_episode(db_session)
    r = await client.post(f"/api/projects/{p.id}/scenes", json={"episode_id": str(uuid.uuid4())})
    assert r.status_code == 400, r.text


async def test_scene_update_sets_continuity_predecessor(client, db_session):
    p = await _project_with_episode(db_session)
    a = (await client.post(f"/api/projects/{p.id}/scenes", json={})).json()
    b = (await client.post(f"/api/projects/{p.id}/scenes", json={})).json()

    r = await client.put(f"/api/scenes/{b['id']}", json={"continuity_prev_scene_id": a["id"]})
    assert r.status_code == 200, r.text
    assert r.json()["continuity_prev_scene_id"] == a["id"]

    r = await client.put(f"/api/scenes/{b['id']}", json={"continuity_prev_scene_id": None})
    assert r.status_code == 200
    assert r.json()["continuity_prev_scene_id"] is None


async def test_scene_cannot_be_its_own_predecessor(client, db_session):
    p = await _project_with_episode(db_session)
    a = (await client.post(f"/api/projects/{p.id}/scenes", json={})).json()
    r = await client.put(f"/api/scenes/{a['id']}", json={"continuity_prev_scene_id": a["id"]})
    assert r.status_code == 400, r.text


@pytest.mark.parametrize("resource", ["characters", "locations", "products", "scenes"])
async def test_delete_missing_returns_404(client, resource):
    r = await client.delete(f"/api/{resource}/{uuid.uuid4()}")
    assert r.status_code == 404


async def test_project_read_populates_counts(client, db_session):
    """GET /projects/{id} reports real character/location counts (regression: were always 0)."""
    p = await _project(db_session)
    await client.post(f"/api/projects/{p.id}/characters", json={"canonical_name": "A"})
    await client.post(f"/api/projects/{p.id}/locations", json={"name": "L"})

    r = await client.get(f"/api/projects/{p.id}")
    assert r.status_code == 200
    body = r.json()
    assert body["character_count"] == 1
    assert body["location_count"] == 1
