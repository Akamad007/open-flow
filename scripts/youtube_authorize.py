"""One-time YouTube OAuth bootstrap.

Reads `YOUTUBE_CLIENT_ID` + `YOUTUBE_CLIENT_SECRET` from the secrets-manager
vault, runs Google's OAuth consent flow (loopback redirect), and writes the
resulting refresh-token JSON to a local file (default:
`~/.video-app/youtube_oauth.json`, configurable via the `YOUTUBE_OAUTH_PATH`
env var).

Re-run this any time auth gets revoked (Google revokes refresh tokens that
are unused for 6 months, or when channel permissions change).

Run on the same machine the backend will upload from (the OAuth file is
local). Requires a browser available on the machine.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Make `app.*` imports work when run from anywhere in the repo.
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))

from google_auth_oauthlib.flow import InstalledAppFlow  # noqa: E402

from app.config import settings  # noqa: E402
from app.utils.secrets_client import get_secret_sync  # noqa: E402

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def _client_config_from_vault() -> dict:
    client_id = get_secret_sync("YOUTUBE_CLIENT_ID")
    client_secret = get_secret_sync("YOUTUBE_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise SystemExit(
            "YOUTUBE_CLIENT_ID and/or YOUTUBE_CLIENT_SECRET missing from "
            "secrets-manager. Add them in the vault first (see "
            "docs/youtube-setup.md)."
        )
    return {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--client-secrets", default=None,
        help="Optional path to a downloaded client_secrets.json. If omitted, "
             "client creds are pulled from the secrets-manager vault.",
    )
    ap.add_argument(
        "--out", default=str(settings.youtube_oauth_path),
        help=f"Where to write the OAuth JSON (default: {settings.youtube_oauth_path})",
    )
    ap.add_argument(
        "--email", default=None,
        help="Pre-fill / hint a Google account on the consent screen (login_hint).",
    )
    args = ap.parse_args()

    if args.client_secrets:
        flow = InstalledAppFlow.from_client_secrets_file(args.client_secrets, SCOPES)
    else:
        flow = InstalledAppFlow.from_client_config(_client_config_from_vault(), SCOPES)

    server_kwargs = {"port": 0, "prompt": "consent", "access_type": "offline"}
    if args.email:
        server_kwargs["login_hint"] = args.email
    creds = flow.run_local_server(**server_kwargs)

    if not creds.refresh_token:
        print(
            "ERROR: no refresh_token was issued. Verify the OAuth consent screen "
            "and the desktop client are configured correctly, then re-run.",
            file=sys.stderr,
        )
        return 1

    blob = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes or SCOPES),
    }
    out = Path(args.out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(blob, indent=2))
    out.chmod(0o600)
    print(f"\n✓ Wrote OAuth JSON to {out} (mode 0600).")
    print("Backend will pick this up automatically on the next upload.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
