# YouTube Upload — Operator Setup (one-time)

Auth is split:
- **Vault** (secrets-manager at `:8010`): `YOUTUBE_CLIENT_ID` + `YOUTUBE_CLIENT_SECRET` (static, set once)
- **Local file** (`~/.video-app/youtube_oauth.json`): per-channel refresh-token JSON, written by the authorize script. Per-machine. Never check in.

## 1. GCP project + API

1. Go to https://console.cloud.google.com.
2. Create / pick a project (e.g. `video-app-uploads`).
3. **APIs & Services → Library →** search "YouTube Data API v3" → **Enable**.

## 2. OAuth consent screen

1. **APIs & Services → OAuth consent screen.**
2. **User Type:** *External*. **Create.**
3. Fill the minimum: app name (anything), your email as user support + dev contact.
4. **Scopes:** add `https://www.googleapis.com/auth/youtube.upload`.
5. **Test users:** add your own Google account (the one that owns the channel).
6. **Save.** Stay in *Testing* mode — Production review isn't needed for a single user.

## 3. OAuth credentials → secrets-manager

1. **APIs & Services → Credentials → Create Credentials → OAuth client ID.**
2. **Application type:** *Desktop app*. Click Create.
3. Open the new credential and copy the **Client ID** + **Client secret**.
4. Add both to the secrets-manager at http://127.0.0.1:8010/admin/vault/secret/:
   - Key `YOUTUBE_CLIENT_ID` → value = the Client ID
   - Key `YOUTUBE_CLIENT_SECRET` → value = the Client secret

## 4. One-time authorization

On the same machine the backend runs on (a browser is required):

```bash
cd /home/akash/PycharmProjects/video-app
/home/akash/.pyenv/versions/video-app/bin/python scripts/youtube_authorize.py
```

- A browser pops, you sign into the YouTube-owning account, click *Allow*.
- The script writes `~/.video-app/youtube_oauth.json` (mode 0600).
- Override the path with `--out /some/path.json` or via `YOUTUBE_OAUTH_PATH` env var.

That's it. The backend reads the file automatically on each upload.

## Re-authorization

If you see `OAuth file missing` or `YouTube auth expired/revoked` errors, run
step 4 again. Google revokes refresh tokens if unused for ~6 months or when
you change channel permissions.

## Quota

YouTube Data API v3 default quota: **10,000 units/day**. A single video
upload costs **1,600 units**, so ~6 uploads/day. If you need more, request a
quota increase from the API console (typically takes a few days).
