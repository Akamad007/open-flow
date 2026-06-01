"""`scene_video.finalize_videos` — chord callback that sets project status / raises on total failure."""

from __future__ import annotations

import pytest

from app.models.project import Project, ProjectStatus
from app.orchestration.stages import scene_video


pytestmark = pytest.mark.slow


async def _make_project(db_session, status=ProjectStatus.generating) -> Project:
    project = Project(
        title="t", original_story_text="s",
        status=status, total_target_duration_seconds=10.0,
    )
    db_session.add(project)
    await db_session.commit()
    return project


async def test_finalize_marks_project_generating_on_success(db_session):
    project = await _make_project(db_session, status=ProjectStatus.image_pregen)

    await scene_video.finalize_videos(str(project.id), [
        {"scene_id": "a", "status": "complete", "file": "/x.mp4"},
        {"scene_id": "b", "status": "skipped", "file": "/y.mp4"},
    ])

    await db_session.refresh(project)
    assert project.status == ProjectStatus.generating


async def test_finalize_raises_when_all_scenes_failed(db_session):
    project = await _make_project(db_session)

    with pytest.raises(RuntimeError, match="All 2 scene video generation tasks failed"):
        await scene_video.finalize_videos(str(project.id), [
            {"scene_id": "a", "status": "failed", "error": "boom"},
            {"scene_id": "b", "status": "failed", "error": "boom"},
        ])


async def test_finalize_continues_with_partial_success(db_session, caplog):
    project = await _make_project(db_session, status=ProjectStatus.image_pregen)

    with caplog.at_level("WARNING"):
        await scene_video.finalize_videos(str(project.id), [
            {"scene_id": "a", "status": "complete", "file": "/x.mp4"},
            {"scene_id": "b", "status": "failed", "error": "boom"},
        ])

    await db_session.refresh(project)
    assert project.status == ProjectStatus.generating
    assert any("1 scene(s) failed" in r.message for r in caplog.records)


async def test_finalize_handles_empty_results():
    """No completed scenes → raise (used to be a silent pass-through)."""
    with pytest.raises(RuntimeError):
        await scene_video.finalize_videos("any-id", [])
