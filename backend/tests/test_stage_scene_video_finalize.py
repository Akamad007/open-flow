"""`scene_video.finalize_videos` — chord callback that sets project status.

The current implementation ignores the per-task `results` arg (chain dispatch
doesn't aggregate them) and instead *trusts the DB*: it counts scenes in the
active episode that have a completed scene-video Asset whose file exists on disk.
- >= 1 completed video  -> project status set to `generating`.
- 0 completed videos     -> raise RuntimeError.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.models.asset import Asset, AssetStatus, AssetType
from app.models.episode import Episode
from app.models.project import Project, ProjectStatus
from app.models.scene import Scene
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


async def _make_episode(db_session, project) -> Episode:
    episode = Episode(project_id=project.id, order_index=0)
    db_session.add(episode)
    await db_session.commit()
    return episode


async def _add_scene(db_session, project, episode, order, *, complete_file: Path | None = None) -> Scene:
    """Add a scene; if `complete_file` is given, write it to disk and attach a
    completed scene-video Asset so `_existing_complete_video` counts it."""
    scene = Scene(project_id=project.id, episode_id=episode.id, order_index=order)
    db_session.add(scene)
    await db_session.commit()
    if complete_file is not None:
        complete_file.write_bytes(b"\x00")
        db_session.add(Asset(
            project_id=project.id, scene_id=scene.id,
            asset_type=AssetType.scene_video, status=AssetStatus.complete,
            file_path=str(complete_file),
        ))
        await db_session.commit()
    return scene


async def test_finalize_marks_project_generating_on_success(db_session, tmp_path):
    project = await _make_project(db_session, status=ProjectStatus.image_pregen)
    episode = await _make_episode(db_session, project)
    await _add_scene(db_session, project, episode, 0, complete_file=tmp_path / "a.mp4")

    await scene_video.finalize_videos(str(project.id), [])

    await db_session.refresh(project)
    assert project.status == ProjectStatus.generating


async def test_finalize_continues_with_partial_success(db_session, tmp_path):
    """One completed video is enough — a sibling scene with no video doesn't block."""
    project = await _make_project(db_session, status=ProjectStatus.image_pregen)
    episode = await _make_episode(db_session, project)
    await _add_scene(db_session, project, episode, 0, complete_file=tmp_path / "a.mp4")
    await _add_scene(db_session, project, episode, 1)  # no completed video

    await scene_video.finalize_videos(str(project.id), [])

    await db_session.refresh(project)
    assert project.status == ProjectStatus.generating


async def test_finalize_raises_when_no_completed_videos(db_session):
    """Scenes exist but none have a completed video on disk -> raise."""
    project = await _make_project(db_session)
    episode = await _make_episode(db_session, project)
    await _add_scene(db_session, project, episode, 0)

    with pytest.raises(RuntimeError, match="No completed scene videos"):
        await scene_video.finalize_videos(str(project.id), [])


async def test_finalize_raises_when_no_scenes(db_session):
    """No episode/scenes at all -> raise (replaces the old empty-results case)."""
    project = await _make_project(db_session)

    with pytest.raises(RuntimeError, match="No completed scene videos"):
        await scene_video.finalize_videos(str(project.id), [])
