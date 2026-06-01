"""YouTube uploader — resumable upload + auto-thumbnail.

Auth split:
- `YOUTUBE_CLIENT_ID` + `YOUTUBE_CLIENT_SECRET` live in the secrets-manager vault
  (static, set once from the GCP Desktop OAuth client).
- The per-channel OAuth refresh-token JSON is written to a local file
  (default `~/.video-app/youtube_oauth.json`, overridable via
  `settings.youtube_oauth_path`) by `scripts/youtube_authorize.py`. The
  local file is per-machine and must not be checked in.

On RefreshError we surface a clear "re-run the authorize script" message
— never auto-retry on auth failures.
"""

from __future__ import annotations

import json
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Callable, Optional

from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from app.config import settings
from app.utils.secrets_client import get_secret_sync

logger = logging.getLogger(__name__)

CLIENT_ID_KEY = "YOUTUBE_CLIENT_ID"
CLIENT_SECRET_KEY = "YOUTUBE_CLIENT_SECRET"
DEFAULT_TOKEN_URI = "https://oauth2.googleapis.com/token"
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
CATEGORY_ID = "22"  # People & Blogs


class YouTubeUploadError(RuntimeError):
    pass


class YouTubeAuthError(YouTubeUploadError):
    """Auth missing/expired/revoked — operator must re-run scripts/youtube_authorize.py."""


def _load_credentials() -> Credentials:
    path = Path(settings.youtube_oauth_path)
    if not path.exists():
        raise YouTubeAuthError(
            f"OAuth file missing at {path}. "
            "Run `python scripts/youtube_authorize.py` to create it."
        )
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        raise YouTubeAuthError(f"{path} is not valid JSON: {e}")
    refresh_token = data.get("refresh_token")
    if not refresh_token:
        raise YouTubeAuthError(f"{path} has no refresh_token — re-run the authorize script.")

    # Client creds: vault first, then fall back to whatever was saved in the file.
    client_id = get_secret_sync(CLIENT_ID_KEY) or data.get("client_id")
    client_secret = get_secret_sync(CLIENT_SECRET_KEY) or data.get("client_secret")
    if not client_id or not client_secret:
        raise YouTubeAuthError(
            f"{CLIENT_ID_KEY}/{CLIENT_SECRET_KEY} missing from secrets-manager and from {path}."
        )
    return Credentials(
        token=data.get("token"),
        refresh_token=refresh_token,
        token_uri=data.get("token_uri", DEFAULT_TOKEN_URI),
        client_id=client_id,
        client_secret=client_secret,
        scopes=SCOPES,
    )


def extract_middle_frame(video_path: Path, out_path: Path) -> Path:
    """Extract a single jpeg at the video's midpoint. Returns out_path on success."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Probe duration
    probe = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(video_path)],
        capture_output=True, text=True, check=False,
    )
    try:
        dur = float(probe.stdout.strip())
    except (ValueError, AttributeError):
        dur = 0.0
    midpoint = max(dur / 2.0, 0.5)
    subprocess.run(
        [settings.ffmpeg_path, "-y", "-ss", f"{midpoint:.2f}", "-i", str(video_path),
         "-frames:v", "1", "-q:v", "2", str(out_path)],
        capture_output=True, check=True,
    )
    return out_path


def upload_video(
    video_path: Path,
    title: str,
    description: str,
    privacy: str,
    progress_cb: Optional[Callable[[float], None]] = None,
    upload_thumbnail: bool = True,
) -> str:
    """Upload `video_path` to YouTube. Returns the video_id.

    progress_cb receives a 0.0–1.0 float each chunk. Raises YouTubeAuthError on
    refresh failure (do NOT retry) and YouTubeUploadError on other errors.
    """
    if not video_path.exists():
        raise YouTubeUploadError(f"Video file does not exist: {video_path}")
    try:
        creds = _load_credentials()
    except YouTubeAuthError:
        raise
    youtube = build("youtube", "v3", credentials=creds, cache_discovery=False)

    body = {
        "snippet": {"title": title[:100], "description": description[:5000], "categoryId": CATEGORY_ID},
        "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False},
    }
    media = MediaFileUpload(str(video_path), mimetype="video/*", chunksize=8 * 1024 * 1024, resumable=True)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    try:
        while response is None:
            status, response = request.next_chunk()
            if status and progress_cb:
                try:
                    progress_cb(float(status.progress()))
                except Exception:
                    pass
    except RefreshError as e:
        raise YouTubeAuthError(
            f"YouTube auth expired/revoked: {e}. Re-run scripts/youtube_authorize.py."
        ) from e
    except HttpError as e:
        raise YouTubeUploadError(f"YouTube API error: {e}") from e

    video_id = response.get("id")
    if not video_id:
        raise YouTubeUploadError(f"Upload finished but no video id in response: {response}")
    if progress_cb:
        try:
            progress_cb(1.0)
        except Exception:
            pass

    if upload_thumbnail:
        try:
            with tempfile.TemporaryDirectory() as td:
                thumb = extract_middle_frame(video_path, Path(td) / "thumb.jpg")
                youtube.thumbnails().set(
                    videoId=video_id,
                    media_body=MediaFileUpload(str(thumb), mimetype="image/jpeg"),
                ).execute()
        except Exception as e:
            # Non-fatal: keep the upload, log the thumbnail failure.
            logger.warning("Thumbnail upload failed for %s: %s", video_id, e)

    return video_id
