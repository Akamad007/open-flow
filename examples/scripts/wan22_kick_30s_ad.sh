#!/usr/bin/env bash
# One-shot launcher: kick a 30s ad through the real backend pipeline using Wan22.
#
# What it does:
#  1. Verifies backend + celery are running (does NOT restart them).
#  2. POSTs a new project with pipeline_profile=wan22_text_only.
#  3. Returns the project_id + tail-friendly log paths so you can watch progress.
#
# This script is safe to re-run — it just creates a new project each time.
# It does NOT modify .env or restart services. If celery isn't running with
# `video_provider=wan22` *or* the wan22 profile picks the provider via factory
# (which it does — `_common.get_video_provider(profile_name)` reads the profile's
# video_provider field), this still works because the profile overrides the
# global setting.
#
# Usage: ./wan22_kick_30s_ad.sh [title] [story_text_file]

set -euo pipefail

BACKEND_URL="${BACKEND_URL:-http://localhost:8002}"
TITLE="${1:-Wan22 30s demo $(date +%H%M%S)}"
STORY_FILE="${2:-}"

# Default 30s ad brief — 5 scenes of 6s each, mixing scene types so the
# Wan22 classifier picks different LoRAs (proves the smart selection works).
DEFAULT_STORY="A 30-second product ad in 5 vignettes (~6s each):
1. A chef in a black apron tosses vegetables into a wok over leaping flames.
2. A man in athletic gear runs through a tree-lined park at golden hour.
3. A fashion model walks down a runway carrying a brown leather handbag.
4. A samurai in heavy armor charges across a misty battlefield, swords drawn.
5. A massive crowd raises fists at an evening rally, banners overhead."

if [ -n "$STORY_FILE" ] && [ -f "$STORY_FILE" ]; then
    STORY=$(cat "$STORY_FILE")
else
    STORY="$DEFAULT_STORY"
fi

echo "=== Pre-flight checks ==="
curl -sf "$BACKEND_URL/api/pipelines" >/dev/null || {
    echo "ERROR: backend not reachable at $BACKEND_URL. Run ./scripts/start_all.sh first."
    exit 2
}
pgrep -f "celery -A celery_worker" >/dev/null || {
    echo "ERROR: celery worker not running. Run ./scripts/start_all.sh first."
    exit 2
}
echo "  ✓ backend reachable at $BACKEND_URL"
echo "  ✓ celery worker running"

echo
echo "=== Creating project ==="
RESPONSE=$(curl -sf -X POST "$BACKEND_URL/api/projects" \
    -H "Content-Type: application/json" \
    -d "$(python3 -c "import json,sys; print(json.dumps({
        'title': '$TITLE',
        'original_story_text': sys.stdin.read(),
        'total_target_duration_seconds': 30,
        'pipeline_profile': 'wan22_text_only',
    }))" <<< "$STORY")")

PROJECT_ID=$(python3 -c "import json,sys; d=json.loads(sys.stdin.read()); print(d['id'])" <<< "$RESPONSE")
echo "  ✓ project created: $PROJECT_ID"
echo "  ✓ profile: wan22_text_only (provider=wan22 via factory)"
echo

echo "=== Monitor ==="
echo "celery log: tail -F /home/akash/PycharmProjects/video-app/backend/celery.log"
echo "project status: curl -s $BACKEND_URL/api/projects/$PROJECT_ID | python3 -m json.tool"
echo
echo "Expected timeline (~30-40 min):"
echo "  - analyze + plan_scenes:   ~1-2 min"
echo "  - prompt generation:        ~2-3 min"
echo "  - scene rendering (5 × 5s): ~25-30 min  (Wan22 + LoRA + optional post-proc)"
echo "  - audio + stitching:        ~3-5 min"
