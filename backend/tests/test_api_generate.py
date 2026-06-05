"""Integration tests for /api/generate endpoints — uses the real FastAPI app + Postgres.

Celery is patched to never actually dispatch — `.delay()` returns a fake AsyncResult.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport

from app.models.project import Project, ProjectStatus
from app.models.render_job import JobStatus, JobType, RenderJob


pytestmark = pytest.mark.slow


@pytest.fixture
def fake_celery_id():
    return "fake-celery-task-" + uuid.uuid4().hex[:8]


@pytest.fixture(autouse=True)
def _stub_celery_delay(fake_celery_id):
    """Make every `.delay(...)` return a deterministic fake AsyncResult."""
    fake_result = SimpleNamespace(id=fake_celery_id, state="PENDING")
    patches = []
    from app.orchestration import tasks
    for name in [
        "task_analyze_story", "task_plan_scenes", "task_generate_prompts",
        "task_plan_audio", "task_review_consistency", "task_generate_audio",
        "task_stitch", "task_dispatch_video_chord", "task_generate_scene_video",
        "task_run_full_pipeline",
    ]:
        task = getattr(tasks, name)
        p = patch.object(task, "delay", return_value=fake_result)
        p.start()
        patches.append(p)
    yield
    for p in patches:
        p.stop()


@pytest_asyncio.fixture
async def client(db_engine):
    """Use the real FastAPI app — its `get_db` dependency uses the patched session factory."""
    from httpx._transports.asgi import ASGITransport as _AT  # noqa: F401
    # We HAVE to import main lazily, after conftest already patched session factories.
    from app.main import app
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _make_project(db_session) -> Project:
    project = Project(
        title="t", original_story_text="s",
        status=ProjectStatus.draft,
        total_target_duration_seconds=10.0,
    )
    db_session.add(project)
    await db_session.commit()
    return project


# ── 404 path ──────────────────────────────────────────────────────────────────

async def test_analyze_returns_404_for_missing_project(client):
    fake = uuid.uuid4()
    resp = await client.post(f"/api/projects/{fake}/analyze")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Project not found"


# ── happy path: stage-trigger creates a job + returns the celery id ──────────

async def test_analyze_creates_running_job(client, db_session, fake_celery_id):
    project = await _make_project(db_session)

    resp = await client.post(f"/api/projects/{project.id}/analyze")
    assert resp.status_code == 202  # async dispatch -> 202 Accepted
    body = resp.json()
    assert body["celery_task_id"] == fake_celery_id

    from sqlalchemy import select
    job = (await db_session.execute(
        select(RenderJob).where(RenderJob.project_id == project.id)
    )).scalar_one()
    assert job.job_type == JobType.story_analysis
    assert job.status == JobStatus.running
    assert job.celery_task_id == fake_celery_id


# ── 409 path: duplicate dispatch is blocked ──────────────────────────────────

async def test_analyze_returns_409_when_job_already_queued(client, db_session):
    project = await _make_project(db_session)

    resp1 = await client.post(f"/api/projects/{project.id}/analyze")
    assert resp1.status_code == 202

    resp2 = await client.post(f"/api/projects/{project.id}/analyze")
    assert resp2.status_code == 409
    assert "already queued or running" in resp2.json()["detail"]["message"]


# ── generate-all: blocks if another project is active ────────────────────────

async def test_generate_all_blocks_when_another_project_running(client, db_session):
    busy = Project(
        title="busy", original_story_text="s",
        status=ProjectStatus.generating,
        total_target_duration_seconds=10.0,
    )
    db_session.add(busy)
    await db_session.commit()

    target = await _make_project(db_session)
    resp = await client.post(f"/api/projects/{target.id}/generate-all")
    assert resp.status_code == 409
    assert "Another project is currently running" in resp.json()["detail"]


async def test_generate_all_succeeds_when_no_other_project_active(client, db_session):
    project = await _make_project(db_session)
    resp = await client.post(f"/api/projects/{project.id}/generate-all")
    assert resp.status_code == 202  # async dispatch -> 202 Accepted
    assert resp.json()["message"] == "Full pipeline workflow dispatched"

    from sqlalchemy import select
    job = (await db_session.execute(
        select(RenderJob)
        .where(RenderJob.project_id == project.id)
        .where(RenderJob.job_type == JobType.full_pipeline)
    )).scalar_one()
    assert job.status == JobStatus.running


async def test_health_endpoint(client):
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "version": "0.1.0"}


# ── regenerate-scene: 404 path ──────────────────────────────────────────────

async def test_regenerate_scene_404_for_missing_scene(client):
    fake = uuid.uuid4()
    resp = await client.post(f"/api/scenes/{fake}/regenerate")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Scene not found"
