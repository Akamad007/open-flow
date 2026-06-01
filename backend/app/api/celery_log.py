"""Tail the celery log, optionally filtered to lines mentioning a project_id."""
from __future__ import annotations

import os
import uuid
from collections import deque
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

router = APIRouter(tags=["celery_log"])

LOG_PATH = Path(os.environ.get(
    "CELERY_LOG_PATH",
    Path(__file__).resolve().parents[2] / "celery.log",
))
MAX_TAIL = 2000


def _tail_filtered(path: Path, needle: str | None, tail: int) -> list[str]:
    if not path.exists():
        return []
    keep: deque[str] = deque(maxlen=tail)
    with path.open("r", errors="replace") as fh:
        for line in fh:
            if needle is None or needle in line:
                keep.append(line.rstrip("\n"))
    return list(keep)


@router.get("/celery-log")
async def celery_log_tail(tail: int = Query(200, ge=1, le=MAX_TAIL)):
    lines = _tail_filtered(LOG_PATH, None, tail)
    return {"path": str(LOG_PATH), "lines": lines, "count": len(lines)}


@router.get("/projects/{project_id}/celery-log")
async def project_celery_log(project_id: uuid.UUID, tail: int = Query(300, ge=1, le=MAX_TAIL)):
    if not LOG_PATH.exists():
        raise HTTPException(status_code=404, detail=f"celery log not found at {LOG_PATH}")
    lines = _tail_filtered(LOG_PATH, str(project_id), tail)
    return {"project_id": str(project_id), "lines": lines, "count": len(lines)}
