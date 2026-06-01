"""Sanity checks: testcontainers Postgres is up, schema is created, models persist."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models.project import Project, ProjectStatus


pytestmark = pytest.mark.slow


async def test_postgres_container_running(db_engine):
    async with db_engine.connect() as conn:
        result = await conn.exec_driver_sql("SELECT 1")
        assert result.scalar() == 1


async def test_can_persist_project(db_session):
    project = Project(
        title="t",
        original_story_text="story",
        status=ProjectStatus.draft,
        total_target_duration_seconds=30.0,
    )
    db_session.add(project)
    await db_session.commit()

    found = (await db_session.execute(select(Project).where(Project.title == "t"))).scalar_one()
    assert found.title == "t"
    assert found.status == ProjectStatus.draft


async def test_truncate_between_tests(db_session):
    """If the previous test created a project, this test should see zero rows."""
    rows = (await db_session.execute(select(Project))).scalars().all()
    assert rows == []
