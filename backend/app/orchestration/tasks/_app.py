"""Celery app instance + GPU-environment defaults."""

from __future__ import annotations

import os

from celery import Celery

from app.config import settings
from app.utils.gpu_routing import route_task


os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

celery_app = Celery(
    "storyvideo",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,                # re-queue on worker crash
    worker_prefetch_multiplier=1,
    task_default_retry_delay=30,
    task_max_retries=3,
    result_expires=86400,
    chord_propagates=True,
    # CRITICAL: with acks_late, the redis broker re-delivers any task that runs
    # longer than visibility_timeout to a SECOND worker — two copies then run
    # concurrently (caused the ix_scene_prompts_scene_id duplicate-key crash).
    # Default is 3600s; set it well above the longest possible task.
    broker_transport_options={"visibility_timeout": 43200},  # 12h
    task_reject_on_worker_lost=False,   # don't silently re-run a genuinely lost task
    task_default_queue="cpu",           # unrouted tasks land on the safe CPU worker, never a GPU card
    # Multi-GPU split. GPU-side tasks route per-project to the project's
    # assigned `gpu{i}` queue via `route_task` (one worker pinned per card),
    # so N projects render on N GPUs in parallel. CPU/LLM stages stay on the
    # shared `cpu` worker and run alongside any GPU render. `route_task`
    # returns None for non-GPU tasks, falling through to the static map below.
    task_routes=(
        route_task,
        {
            "storyvideo.full_pipeline":         {"queue": "cpu"},
            "storyvideo.analyze_story":         {"queue": "cpu"},
            "storyvideo.plan_scenes":           {"queue": "cpu"},
            "storyvideo.generate_prompts":      {"queue": "cpu"},
            "storyvideo.plan_audio":            {"queue": "cpu"},
            "storyvideo.review_consistency":    {"queue": "cpu"},
            "storyvideo.evaluate_project":      {"queue": "cpu"},
            "storyvideo.pipeline_cleanup":      {"queue": "cpu"},
            "storyvideo.episode_prompts":       {"queue": "cpu"},
            "storyvideo.finalize_and_continue": {"queue": "cpu"},
            "storyvideo.stitch":                {"queue": "cpu"},
            # YouTube upload is pure I/O — run on the cpu worker.
            "storyvideo.upload_to_youtube":     {"queue": "cpu"},
        },
    ),
)
