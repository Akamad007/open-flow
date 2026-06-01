# YouTube Upload Feature — Design

Upload a finished episode's `final_render` MP4 to YouTube from the episode card,
with a user-supplied title + description (optional thumbnail + privacy).

## Non-goals

- Multi-channel / per-user OAuth. Single channel, owned by the operator.
- Scheduling / "publish at" — only `private` / `unlisted` / `public` at upload time.
- Live streaming. Captions. Auto-translation. Comments management.
- Re-uploading. If you want to replace the video, delete on YouTube + re-upload.

## Architecture (v1)

```
 [EpisodesPanel.tsx] ──click──▶ UploadModal (title, desc, privacy)
                              │
                              ▼
   POST /api/episodes/{id}/upload-youtube  { title, description, privacy }
                              │
                              ▼
   FastAPI route validates episode has final_render
                              │
                              ▼
   Enqueue celery task on `cpu` queue (NOT gpu — pure IO)
   storyvideo.upload_to_youtube(asset_id, title, desc, privacy)
                              │
                              ▼
   Worker:
     1. Read OAuth refresh_token from secrets-manager (key: YOUTUBE_OAUTH_JSON)
     2. Exchange for access_token
     3. google-api-python-client resumable upload (chunked, retryable)
     4. Patch new Upload row in DB with progress / video_id / state
                              │
                              ▼
   FE polls GET /api/episodes/{id}/uploads — shows badge:
     queued → uploading (X%) → complete (youtube_url) | failed (error)
```

### One-time OAuth bootstrap

`scripts/youtube_authorize.py` — InstalledAppFlow (loopback redirect), runs
once on the operator's laptop, prints the refresh-token JSON, operator
pastes into secrets-manager as `YOUTUBE_OAUTH_JSON`. No browser involvement
at runtime. Client-id + client-secret also live in secrets-manager
(`YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`).

### New ORM: `YouTubeUpload`

```
id           uuid pk
episode_id   uuid fk → episodes (NOT NULL, indexed)
asset_id     uuid fk → assets (the final_render at upload time)
title        text
description  text
privacy      enum(private|unlisted|public)
status       enum(queued|uploading|complete|failed)
youtube_id   text NULL                  -- YT video id once available
youtube_url  text NULL                  -- shortcut https://youtu.be/<id>
progress     float NULL                 -- 0.0–1.0
error        text NULL
created_at   timestamptz default now()
completed_at timestamptz NULL
```

One episode → many uploads (history). Latest row = current state.

### Why NOT reuse `Asset`

Asset is a *file on disk*. A YouTube upload is a *publish event* with its own
lifecycle (queued → uploading → complete) and external identity (video_id).
Conflating them muddies queries ("show me uploads in last 24h" vs "show me
final renders").

### Frontend

- New `<YouTubeUploadButton episode={ep} />` shown only when
  `ep.final_video_path` exists.
- Click → modal: title (default = project title + " — " + episode title),
  description (default = first 200 chars of `original_story_text`),
  privacy radio (default `unlisted`).
- After submit, modal closes, button → "Uploading…" with % from poll.
- On complete → button becomes `▶ View on YouTube` link.

### Backend route

`POST /api/episodes/{episode_id}/upload-youtube`
- 404 if episode missing
- 409 if no `final_render` asset for episode
- 409 if an `uploading|queued` upload already exists for episode
- 202 + upload_id on success

`GET /api/episodes/{episode_id}/uploads` — list, newest first.

### Resumable upload params

- chunksize: 8 MB
- retry on 5xx + 429 with exponential backoff (max 5)
- progress callback writes `progress` field every ~5%

### Quota

YouTube Data API default = 10,000 units/day. A single video insert = 1,600
units. So ~6 uploads/day before hitting the cap. Document this. If we hit
it, BE returns 429 with friendly message. No need for queue throttling
at v1.

---

## Critique — what's wrong with the above

### 🔴 Critical

1. **Resumable upload chunk progress on celery + Postgres is wrong shape.**
   Updating `progress` every 5% means ~20 row-writes per upload across two
   celery serialisations. The celery worker holds the upload session
   in-process; if the worker dies, the upload restarts from zero. For a
   240 MB file that's ~30s wasted but not catastrophic. **Decision:** keep
   it simple, accept restart-from-zero. Don't try to checkpoint the
   resumable session id.

2. **OAuth refresh token in secrets-manager is fine, but token rotation
   isn't designed.** Google refresh tokens *can* be revoked or expire if
   unused for 6 months. v1 has no "refresh failed → notify operator"
   path. **Fix:** on `RefreshError`, mark upload `failed` with a clear
   message ("YouTube auth expired — run scripts/youtube_authorize.py
   again"). Don't try to auto-recover.

3. **Frontend polling is wasteful.** A 240 MB upload at typical home
   bandwidth (10 MB/s up) is 24s. Polling every 2s is fine. But if a
   user navigates away and comes back, we need durable state — which
   the DB gives us. ✅ Already handled by the schema. Keep polling.

4. **"409 if upload already exists" is too strict.** User retries after
   a failed upload should be allowed. **Fix:** only block when there's
   an *active* upload (`status in (queued, uploading)`). Failed uploads
   don't block retries.

### 🟡 Moderate

5. **Where does the operator get YouTube API credentials?** v1 doc
   doesn't say. Need a 5-line README: GCP Console → Enable YouTube Data
   API v3 → OAuth consent screen (Testing mode is enough for single
   user) → Create Desktop client → download JSON → put client id/secret
   in secrets-manager. Add this to the runbook section.

6. **Title/description size limits not validated.** YT caps title at
   100 chars, description at 5000. **Fix:** Pydantic validators on the
   request body. Trim or reject.

7. **No tags / category.** YT defaults are fine for unlisted, but if a
   user uploads `public` and forgets, the video gets no discoverability.
   **Decision:** add an optional `tags: list[str]` and default
   `categoryId = "22"` (People & Blogs). Don't expose category in v1
   UI — just hard-code 22.

8. **Thumbnail upload skipped in v1.** That's OK, but YouTube auto-thumbs
   from a Wan2.2 clip will be ugly. **Defer to v2:** auto-extract a
   middle-of-video frame with ffmpeg + `thumbnails.set` API call. One
   line of work, but not required for the button to ship.

### 🟢 Minor

9. **The celery task name `storyvideo.upload_to_youtube` is on the
   `cpu` queue but is pure I/O — neither cpu nor gpu fits.** Adding a
   third queue for this is over-engineering. Reuse `cpu` (concurrency=2);
   uploads block on network, not CPU. The two cpu slots are plenty.

10. **`youtube_url` is derived from `youtube_id` (just prepend
    `https://youtu.be/`).** Storing both is redundant. Drop
    `youtube_url`, build on read.

11. **No retry semantics on the celery task itself.** Celery's `autoretry_for=(HttpError,)` + `retry_backoff=True` covers transient
    Google errors. Add it.

12. **`original_story_text` could be > 5000 chars.** First-200-chars
    default is fine. Document the truncation.

---

## Revised architecture (post-critique)

Same as v1 with these deltas:

- Drop `youtube_url` column. Computed property.
- 409 only on active uploads (`queued|uploading`). Failed uploads allow retry.
- Pydantic validators: title ≤100, description ≤5000, tags ≤500 chars total.
- Celery task: `@task(autoretry_for=(HttpError,), retry_backoff=True, max_retries=5)`.
- Hard-code `categoryId="22"`.
- On `google.auth.exceptions.RefreshError`: mark upload failed with
  explicit re-auth message; do NOT retry.
- Add `docs/youtube-setup.md` operator runbook (GCP, OAuth, secrets keys).
- Defer thumbnail upload to v2.

## Files to add / change

```
backend/alembic/versions/<rev>_add_youtube_uploads.py        NEW (~30 lines)
backend/app/models/youtube_upload.py                          NEW (~50)
backend/app/schemas/youtube_upload.py                         NEW (~30)
backend/app/orchestration/tasks/youtube_upload.py             NEW (~80)
backend/app/api/episodes.py                                   +60 lines (2 routes)
backend/app/utils/youtube_uploader.py                         NEW (~70)
scripts/youtube_authorize.py                                  NEW (~40)
docs/youtube-setup.md                                         NEW (~50)
frontend/src/components/YouTubeUploadButton.tsx               NEW (~100)
frontend/src/components/YouTubeUploadModal.tsx                NEW (~80)
frontend/src/api/client.ts                                    +20
frontend/src/types/index.ts                                   +15
```

Total ~625 lines. Single PR. Two days including the GCP one-time setup.

## Answers (locked in)

1. **Channel:** single-channel, operator's own YouTube channel.
2. **Default privacy:** `private` (was `unlisted` in v1 — flipped).
3. **Thumbnail:** auto-extract middle frame at upload time, post via `thumbnails.set`.
4. **History:** dedicated "Uploads" tab on the episode card listing all past uploads (status + link).

Thumbnail goes from v2 to v1 scope — +1 file (~30 LOC) for the extractor.
