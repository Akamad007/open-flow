#!/usr/bin/env python3
"""Celery worker entry point."""

from app.orchestration.tasks import celery_app

if __name__ == "__main__":
    celery_app.worker_main(["worker", "--loglevel=info", "--concurrency=2"])
