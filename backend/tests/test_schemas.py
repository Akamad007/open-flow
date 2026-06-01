"""Pydantic schema sanity checks."""

from __future__ import annotations

import uuid


class TestSchemas:
    def test_project_create(self):
        from app.schemas.project import ProjectCreate
        p = ProjectCreate(title="Test", original_story_text="A story...")
        assert p.title == "Test"
        assert p.original_story_text == "A story..."

    def test_project_create_defaults(self):
        from app.schemas.project import ProjectCreate
        p = ProjectCreate()
        assert p.title == "Untitled Project"
        assert p.original_story_text == ""

    def test_project_update_partial(self):
        from app.schemas.project import ProjectUpdate
        p = ProjectUpdate(title="New Title")
        dumped = p.model_dump(exclude_unset=True)
        assert dumped == {"title": "New Title"}
        assert "status" not in dumped

    def test_scene_create(self):
        from app.schemas.scene import SceneCreate
        s = SceneCreate(order_index=0, duration_seconds=4.0)
        assert s.duration_seconds == 4.0

    def test_scene_reorder(self):
        from app.schemas.scene import SceneReorder
        ids = [uuid.uuid4(), uuid.uuid4()]
        r = SceneReorder(scene_ids=ids)
        assert len(r.scene_ids) == 2
