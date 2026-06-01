"""tasks package: public exports, Celery registration, runtime helpers."""

from __future__ import annotations

import pytest

from app.orchestration import tasks
from app.orchestration.tasks._runtime import is_cancelled, to_uuid


def test_celery_app_main_name():
    assert tasks.celery_app.main == "storyvideo"


@pytest.mark.parametrize("task_name", [
    "storyvideo.analyze_story",
    "storyvideo.plan_scenes",
    "storyvideo.generate_prompts",
    "storyvideo.plan_audio",
    "storyvideo.review_consistency",
    "storyvideo.pregen_images",
    "storyvideo.generate_audio",
    "storyvideo.stitch",
    "storyvideo.generate_scene_video",
    "storyvideo.dispatch_video_chord",
    "storyvideo.finalize_and_continue",
    "storyvideo.pipeline_cleanup",
    "storyvideo.full_pipeline",
])
def test_task_registered(task_name):
    assert task_name in tasks.celery_app.tasks


def test_public_exports_present():
    expected = {
        "celery_app", "build_pipeline_workflow", "is_cancelled", "run_async",
        "task_analyze_story", "task_plan_scenes", "task_generate_prompts",
        "task_plan_audio", "task_review_consistency", "task_pregen_images",
        "task_generate_audio", "task_stitch", "task_generate_scene_video",
        "task_dispatch_video_chord", "task_finalize_and_continue",
        "task_pipeline_cleanup", "task_run_full_pipeline",
        "release_pipeline_lock_for_project",
    }
    assert expected.issubset(set(dir(tasks)))


def test_is_cancelled_recognizes_project_cancelled_error():
    from app.orchestration.pipeline import ProjectCancelledError
    assert is_cancelled(ProjectCancelledError("gone")) is True
    assert is_cancelled(RuntimeError("other")) is False
    assert is_cancelled(ValueError("nope")) is False


def test_to_uuid_parses_string():
    import uuid
    u = uuid.uuid4()
    assert to_uuid(str(u)) == u


def test_build_pipeline_workflow_has_six_stages():
    """analyze → plan → prompts → review → pregen → dispatch_chord.

    Audio planning + generation deliberately runs AFTER the video chord
    (sizes narration to actual rendered duration), so it's not part of
    this pre-video chain.
    """
    chain = tasks.build_pipeline_workflow("project-123")
    assert len(chain.tasks) == 6
    expected_names = [
        "storyvideo.analyze_story",
        "storyvideo.plan_scenes",
        "storyvideo.generate_prompts",
        "storyvideo.review_consistency",
        "storyvideo.pregen_images",
        "storyvideo.dispatch_video_chord",
    ]
    actual = [sig.task for sig in chain.tasks]
    assert actual == expected_names


def test_legacy_alias_for_release_helper_exists():
    """Some old code imported `_release_pipeline_lock_for_project` — keep the alias."""
    assert hasattr(tasks, "_release_pipeline_lock_for_project")
    assert tasks._release_pipeline_lock_for_project is tasks.release_pipeline_lock_for_project
