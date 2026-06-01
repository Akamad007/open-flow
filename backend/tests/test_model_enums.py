"""ORM enum sanity — values are stable and the full lifecycle is wired up."""

from __future__ import annotations


class TestModelEnums:
    def test_project_status_values(self):
        from app.models.project import ProjectStatus
        assert ProjectStatus.draft.value == "draft"
        assert ProjectStatus.complete.value == "complete"
        assert ProjectStatus.failed.value == "failed"
        statuses = [s.value for s in ProjectStatus]
        assert "analyzing" in statuses
        assert "generating" in statuses
        assert "stitching" in statuses

    def test_scene_status_values(self):
        from app.models.scene import SceneStatus
        assert SceneStatus.planned.value == "planned"
        assert SceneStatus.generated.value == "generated"

    def test_asset_type_values(self):
        from app.models.asset import AssetType
        assert AssetType.scene_video.value == "scene_video"
        assert AssetType.full_story_audio.value == "full_story_audio"
        assert AssetType.final_render.value == "final_render"

    def test_job_type_values(self):
        from app.models.render_job import JobType
        values = {j.value for j in JobType}
        for expected in (
            "story_analysis", "scene_planning", "prompt_generation",
            "audio_planning", "consistency_review", "image_pregen",
            "video_generation", "audio_generation", "stitching", "full_pipeline",
        ):
            assert expected in values, f"Missing JobType: {expected}"
