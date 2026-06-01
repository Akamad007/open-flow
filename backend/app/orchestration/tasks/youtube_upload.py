"""Celery task: upload a finished episode's final_render to YouTube."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from googleapiclient.errors import HttpError
from sqlalchemy import select

from app.database import async_session_factory
from app.models.youtube_upload import YouTubeUpload, YouTubeUploadStatus
from app.orchestration.tasks._app import celery_app
from app.orchestration.tasks._runtime import run_async, to_uuid
from app.utils.youtube_uploader import (
    YouTubeAuthError,
    YouTubeUploadError,
    upload_video,
)

logger = logging.getLogger(__name__)


async def _load_upload(upload_id: str) -> YouTubeUpload | None:
    async with async_session_factory() as db:
        return await db.get(YouTubeUpload, to_uuid(upload_id))


async def _set_status(
    upload_id: str,
    *,
    status: YouTubeUploadStatus | None = None,
    progress: float | None = None,
    youtube_id: str | None = None,
    error: str | None = None,
    completed: bool = False,
) -> None:
    async with async_session_factory() as db:
        row = await db.get(YouTubeUpload, to_uuid(upload_id))
        if not row:
            return
        if status is not None:
            row.status = status
        if progress is not None:
            row.progress = progress
        if youtube_id is not None:
            row.youtube_id = youtube_id
        if error is not None:
            row.error = error
        if completed:
            row.completed_at = datetime.now(timezone.utc)
        await db.commit()


@celery_app.task(
    name="storyvideo.upload_to_youtube",
    bind=True,
    autoretry_for=(HttpError,),
    retry_backoff=True,
    retry_backoff_max=300,
    max_retries=5,
)
def task_upload_to_youtube(self, upload_id: str, video_path: str) -> dict:
    """Run a YouTube upload. Updates the YouTubeUpload row with progress/result."""
    path = Path(video_path)
    if not path.exists():
        run_async(_set_status(
            upload_id, status=YouTubeUploadStatus.failed,
            error=f"Video file missing on disk: {video_path}", completed=True,
        ))
        return {"upload_id": upload_id, "status": "failed", "error": "file missing"}

    upload = run_async(_load_upload(upload_id))
    if not upload:
        return {"upload_id": upload_id, "status": "failed", "error": "row missing"}

    run_async(_set_status(upload_id, status=YouTubeUploadStatus.uploading, progress=0.0))

    last_logged = [0.0]

    def _on_progress(p: float) -> None:
        # Throttle DB writes to every ~5%.
        if p - last_logged[0] >= 0.05 or p >= 1.0:
            last_logged[0] = p
            try:
                run_async(_set_status(upload_id, progress=p))
            except Exception:
                logger.exception("Failed to update progress row %s", upload_id)

    try:
        video_id = upload_video(
            video_path=path,
            title=upload.title,
            description=upload.description,
            privacy=upload.privacy.value,
            progress_cb=_on_progress,
            upload_thumbnail=True,
        )
    except YouTubeAuthError as e:
        run_async(_set_status(
            upload_id, status=YouTubeUploadStatus.failed, error=str(e), completed=True,
        ))
        # Do NOT retry on auth errors — operator must re-authorize.
        return {"upload_id": upload_id, "status": "failed", "error": "auth"}
    except YouTubeUploadError as e:
        run_async(_set_status(
            upload_id, status=YouTubeUploadStatus.failed, error=str(e), completed=True,
        ))
        return {"upload_id": upload_id, "status": "failed", "error": str(e)[:200]}

    run_async(_set_status(
        upload_id, status=YouTubeUploadStatus.complete, progress=1.0,
        youtube_id=video_id, completed=True,
    ))
    logger.info("YouTube upload %s complete → https://youtu.be/%s", upload_id, video_id)
    return {"upload_id": upload_id, "status": "complete", "youtube_id": video_id}
