"""assert_project_active raises ProjectCancelledError for missing or terminal projects."""

from __future__ import annotations

import uuid

import pytest

from app.models.project import Project, ProjectStatus
from app.orchestration._common import ProjectCancelledError, assert_project_active


pytestmark = pytest.mark.slow


async def _add_project(db_session, status: ProjectStatus) -> Project:
    project = Project(
        title="t", original_story_text="s",
        status=status, total_target_duration_seconds=10.0,
    )
    db_session.add(project)
    await db_session.commit()
    return project


async def test_active_project_returns_project(db_session):
    project = await _add_project(db_session, ProjectStatus.analyzing)
    found = await assert_project_active(db_session, str(project.id), "analysis")
    assert found.id == project.id


async def test_missing_project_raises(db_session):
    fake_id = str(uuid.uuid4())
    with pytest.raises(ProjectCancelledError, match="no longer exists"):
        await assert_project_active(db_session, fake_id, "analysis")


@pytest.mark.parametrize("status", [
    ProjectStatus.failed,
    ProjectStatus.complete,
    ProjectStatus.draft,
])
async def test_inactive_project_raises(db_session, status):
    project = await _add_project(db_session, status)
    with pytest.raises(ProjectCancelledError, match=f"status '{status.value}'"):
        await assert_project_active(db_session, str(project.id), "analysis")


@pytest.mark.parametrize("status", [
    ProjectStatus.analyzing,
    ProjectStatus.planning,
    ProjectStatus.prompting,
    ProjectStatus.audio_planning,
    ProjectStatus.reviewing,
    ProjectStatus.image_pregen,
    ProjectStatus.generating,
    ProjectStatus.stitching,
])
async def test_active_statuses_pass(db_session, status):
    project = await _add_project(db_session, status)
    result = await assert_project_active(db_session, str(project.id), "any")
    assert result.id == project.id
