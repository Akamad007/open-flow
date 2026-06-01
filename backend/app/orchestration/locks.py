"""
Pipeline distributed locks using Redis.

Provides two lock types:
  - stage_lock(project_id, stage)  — ensures one Celery task per project+stage at a time
  - pipeline_lock(project_id)      — ensures only one full-pipeline run per project

Both use Redis SET NX with TTL so locks auto-expire on crash/timeout.
On duplicate detection, raises celery.exceptions.Ignore so Celery
silently drops the duplicate without marking it as failed.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Generator

import redis as redis_lib
from celery.exceptions import Ignore

from app.config import settings

logger = logging.getLogger(__name__)

# One shared Redis client (thread-safe, connection-pooled)
_redis: redis_lib.Redis | None = None


def _get_redis() -> redis_lib.Redis:
    global _redis
    if _redis is None:
        _redis = redis_lib.from_url(
            settings.celery_broker_url,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
    return _redis


# ── Stage-level lock ─────────────────────────────────────────────────────────

def _stage_key(project_id: str, stage: str) -> str:
    return f"pipeline:stage:{project_id}:{stage}"


def acquire_stage_lock(project_id: str, stage: str, task_id: str, ttl: int = 600) -> bool:
    """
    Try to acquire a per-stage lock.
    Returns True if acquired, False if already held by another task.
    TTL defaults to 10 min — long enough for any single stage.
    """
    try:
        key = _stage_key(project_id, stage)
        acquired = _get_redis().set(key, task_id, nx=True, ex=ttl)
        if not acquired:
            existing = _get_redis().get(key)
            logger.warning(
                "Stage lock '%s' for project %s already held by task %s — dropping duplicate",
                stage, project_id, existing,
            )
        return bool(acquired)
    except redis_lib.RedisError as e:
        # Redis unavailable — fail open (let the task run, better than blocking)
        logger.error("Redis lock error (fail-open) for %s/%s: %s", project_id, stage, e)
        return True


def release_stage_lock(project_id: str, stage: str, task_id: str) -> None:
    """Release the lock only if we still own it (prevents releasing another task's lock)."""
    try:
        key = _stage_key(project_id, stage)
        current = _get_redis().get(key)
        if current == task_id:
            _get_redis().delete(key)
    except redis_lib.RedisError as e:
        logger.error("Redis release error for %s/%s: %s", project_id, stage, e)


@contextmanager
def stage_lock(
    project_id: str,
    stage: str,
    task_id: str,
    ttl: int = 600,
) -> Generator[None, None, None]:
    """
    Context manager that acquires a stage lock before the task body runs.
    Raises celery.exceptions.Ignore if a duplicate is detected — Celery
    will silently acknowledge and discard the task.

    Usage::

        @celery_app.task(bind=True)
        def task_analyze_story(self, project_id):
            with stage_lock(project_id, "analyze_story", self.request.id):
                ...
    """
    acquired = acquire_stage_lock(project_id, stage, task_id, ttl)
    if not acquired:
        raise Ignore()  # Celery silently drops this duplicate
    try:
        yield
    finally:
        release_stage_lock(project_id, stage, task_id)


# ── Pipeline-level lock (project scope) ──────────────────────────────────────

def _pipeline_key(project_id: str) -> str:
    return f"pipeline:project:{project_id}"


def acquire_pipeline_lock(project_id: str, task_id: str, ttl: int = 10800) -> bool:
    """
    Acquire a project-level pipeline lock.
    TTL defaults to 3 hours — maximum expected pipeline runtime.
    """
    try:
        key = _pipeline_key(project_id)
        acquired = _get_redis().set(key, task_id, nx=True, ex=ttl)
        if not acquired:
            existing = _get_redis().get(key)
            logger.warning(
                "Pipeline lock for project %s already held by task %s — dropping duplicate",
                project_id, existing,
            )
        return bool(acquired)
    except redis_lib.RedisError as e:
        logger.error("Redis pipeline lock error (fail-open) for %s: %s", project_id, e)
        return True


def release_pipeline_lock(project_id: str, task_id: str) -> None:
    try:
        key = _pipeline_key(project_id)
        current = _get_redis().get(key)
        if current == task_id:
            _get_redis().delete(key)
    except redis_lib.RedisError as e:
        logger.error("Redis pipeline release error for %s: %s", project_id, e)



# ── Utility: force-clear a lock (for manual recovery / admin) ────────────────

def clear_all_locks_for_project(project_id: str) -> None:
    """Admin utility: clear all stage + pipeline locks for a project."""
    try:
        r = _get_redis()
        pattern = f"pipeline:*:{project_id}*"
        keys = list(r.scan_iter(pattern))
        if keys:
            r.delete(*keys)
            logger.info("Cleared %d locks for project %s: %s", len(keys), project_id, keys)
        else:
            logger.info("No locks found for project %s", project_id)
    except redis_lib.RedisError as e:
        logger.error("Error clearing locks for project %s: %s", project_id, e)

