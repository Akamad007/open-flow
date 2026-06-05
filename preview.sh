#!/usr/bin/env bash
# preview.sh — one-shot low-resolution e2e for fast iteration.
#
# Restarts the celery worker with preview env vars (LTX 320x192, 25 frames,
# 15 steps; SD3.5 30 steps) and runs test_save_soil_preview.py. Restores
# the worker to default settings when the preview finishes.
#
# Usage:
#   ./preview.sh                  # full preview run, ~5 min
#   ./preview.sh --keep-env       # leave the worker on preview settings
#                                 # (use for iterating multiple projects)

set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
PYTHON="${PYTHON_BIN:-$ROOT/backend/.venv/bin/python}"
[ -x "$PYTHON" ] || PYTHON="$(command -v python3)"
KEEP_ENV=0
[[ "${1:-}" == "--keep-env" ]] && KEEP_ENV=1

echo "🔄 Starting celery in PREVIEW mode (low-res, fast)…"

# Preview settings — clearly degraded for speed; match comments in config.py
export LTX_HEIGHT=192
export LTX_WIDTH=320
export LTX_NUM_FRAMES=25            # 8*3+1 — LTX requires 8n+1
export LTX_INFERENCE_STEPS=15
export LTX_FPS=12
export SD35_STEPS=30
export SD35_CHAR_WIDTH=512
export SD35_CHAR_HEIGHT=512

# Restart celery so the worker process inherits these env vars
"$ROOT/dev.sh" start >/dev/null 2>&1
until tail -3 "$ROOT/backend/celery.log" 2>/dev/null | grep -q "ready"; do sleep 1; done
echo "✅ Worker ready (preview settings)"

echo ""
"$PYTHON" "$ROOT/test_save_soil_preview.py" --api http://localhost:8002 "$@"
EXIT=$?

if [[ $KEEP_ENV -eq 0 ]]; then
    echo ""
    echo "🔄 Restoring celery to DEFAULT (full-res) settings…"
    unset LTX_HEIGHT LTX_WIDTH LTX_NUM_FRAMES LTX_INFERENCE_STEPS \
          LTX_FPS SD35_STEPS SD35_CHAR_WIDTH SD35_CHAR_HEIGHT
    "$ROOT/dev.sh" start >/dev/null 2>&1
    until tail -3 "$ROOT/backend/celery.log" 2>/dev/null | grep -q "ready"; do sleep 1; done
    echo "✅ Worker restored to default settings"
fi

exit $EXIT
