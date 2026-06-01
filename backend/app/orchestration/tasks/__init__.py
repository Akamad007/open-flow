"""Tasks package — re-exports the public API previously at `tasks.py`."""

from app.orchestration.tasks._app import celery_app
from app.orchestration.tasks._runtime import is_cancelled, run_async
from app.orchestration.tasks.cleanup import (
    release_pipeline_lock_for_project,
    task_pipeline_cleanup,
)
from app.orchestration.tasks.eval_task import task_evaluate_project
from app.orchestration.tasks.full_pipeline import (
    build_pipeline_workflow,
    task_run_full_pipeline,
)
from app.orchestration.tasks.queue_scanner import scan_and_dispatch
from app.orchestration.tasks.scene_tasks import (
    task_dispatch_video_chord,
    task_finalize_and_continue,
    task_generate_scene_video,
)
from app.orchestration.tasks.stage_tasks import (
    task_analyze_story,
    task_generate_audio,
    task_generate_prompts,
    task_plan_audio,
    task_plan_scenes,
    task_pregen_images,
    task_review_consistency,
    task_stitch,
)
from app.orchestration.tasks.youtube_upload import task_upload_to_youtube

# Internal compatibility shim for code that imported `_release_pipeline_lock_for_project`.
_release_pipeline_lock_for_project = release_pipeline_lock_for_project

__all__ = [
    "celery_app",
    "build_pipeline_workflow",
    "is_cancelled",
    "run_async",
    "release_pipeline_lock_for_project",
    "task_analyze_story",
    "task_dispatch_video_chord",
    "task_evaluate_project",
    "task_finalize_and_continue",
    "task_generate_audio",
    "task_generate_prompts",
    "task_generate_scene_video",
    "task_pipeline_cleanup",
    "task_plan_audio",
    "task_plan_scenes",
    "task_pregen_images",
    "task_review_consistency",
    "task_run_full_pipeline",
    "task_stitch",
    "task_upload_to_youtube",
    "scan_and_dispatch",
]
