"""The UI-pinned continuity predecessor (continuity_prev_scene_id) overrides the
character-overlap I2V seed picker — scene N chains off the pinned scene's last
frame regardless of order_index adjacency."""

from __future__ import annotations

from app.config import settings
from app.models.episode import Episode
from app.models.project import Project, ProjectStatus
from app.models.scene import Scene
from app.orchestration.stages.scene_video import _resolve_last_frame


async def _project_episode(db_session):
    p = Project(title="t", original_story_text="x",
                status=ProjectStatus.draft, total_target_duration_seconds=10.0)
    db_session.add(p)
    await db_session.flush()
    ep = Episode(project_id=p.id, order_index=0)
    db_session.add(ep)
    await db_session.flush()
    return p, ep


async def test_explicit_predecessor_overrides_smart_seed(db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    p, ep = await _project_episode(db_session)
    a = Scene(project_id=p.id, episode_id=ep.id, order_index=0)
    mid = Scene(project_id=p.id, episode_id=ep.id, order_index=1)
    db_session.add_all([a, mid])
    await db_session.flush()
    b = Scene(project_id=p.id, episode_id=ep.id, order_index=2, continuity_prev_scene_id=a.id)
    db_session.add(b)
    await db_session.flush()

    frame_dir = tmp_path / "temp" / str(p.id) / "episodes" / str(ep.id)
    frame_dir.mkdir(parents=True)
    frame = frame_dir / "scene_000_last_frame.png"   # scene A (order 0), NOT the adjacent scene 1
    frame.write_bytes(b"x")

    chosen = await _resolve_last_frame(db_session, str(p.id), b, ep)
    assert chosen == str(frame)


async def test_explicit_predecessor_not_rendered_yet_returns_none(db_session, tmp_path, monkeypatch):
    """Pinned predecessor with no last_frame on disk → None (caller cold-starts / requeues),
    not a silent fallback to the heuristic."""
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    p, ep = await _project_episode(db_session)
    a = Scene(project_id=p.id, episode_id=ep.id, order_index=0)
    db_session.add(a)
    await db_session.flush()
    b = Scene(project_id=p.id, episode_id=ep.id, order_index=1, continuity_prev_scene_id=a.id)
    db_session.add(b)
    await db_session.flush()

    assert await _resolve_last_frame(db_session, str(p.id), b, ep) is None
