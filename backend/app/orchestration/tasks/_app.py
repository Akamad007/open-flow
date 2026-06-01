"""Celery app instance + GPU-environment defaults."""

from __future__ import annotations

import os

from celery import Celery

from app.config import settings


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
    task_default_queue="gpu",           # safety fallback for any unrouted task
    # Two-queue split: LLM/prompt-side stages run on the `cpu` worker in
    # parallel with the GPU worker. Cross-project speedup — while project A
    # is doing video gen on the gpu worker, project B's prompt-side stages
    # can run on the cpu worker.
    task_routes={
        "storyvideo.full_pipeline":        {"queue": "cpu"},
        "storyvideo.analyze_story":        {"queue": "cpu"},
        "storyvideo.plan_scenes":          {"queue": "cpu"},
        "storyvideo.generate_prompts":     {"queue": "cpu"},
        "storyvideo.plan_audio":           {"queue": "cpu"},
        "storyvideo.review_consistency":   {"queue": "cpu"},
        "storyvideo.evaluate_project":     {"queue": "cpu"},
        "storyvideo.pipeline_cleanup":     {"queue": "cpu"},
        "storyvideo.pregen_images":        {"queue": "gpu"},
        "storyvideo.dispatch_video_chord": {"queue": "gpu"},
        "storyvideo.generate_scene_video": {"queue": "gpu"},
        "storyvideo.finalize_and_continue": {"queue": "cpu"},
        "storyvideo.generate_audio":       {"queue": "gpu"},
        "storyvideo.stitch":               {"queue": "cpu"},
        # YouTube upload is pure I/O — run on the cpu worker alongside LLM tasks.
        "storyvideo.upload_to_youtube":    {"queue": "cpu"},
    },
)
