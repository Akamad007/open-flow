#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────
# dev.sh — Manage the video-app Celery worker
#
# Guarantees: EXACTLY 1 worker, concurrency=1, GPU-safe
#
# Usage:
#   ./dev.sh            — kill existing, start fresh worker
#   ./dev.sh stop       — kill all workers
#   ./dev.sh status     — show worker processes
# ─────────────────────────────────────────────────────────────────

set -euo pipefail

BACKEND_DIR="$(cd "$(dirname "$0")/backend" && pwd)"

# Resolve interpreter portably: $PYTHON_BIN > repo venv > PATH.
PYTHON="${PYTHON_BIN:-$BACKEND_DIR/.venv/bin/python}"
[ -x "$PYTHON" ] || PYTHON="$(command -v python3)"
CELERY="${CELERY_BIN:-$(dirname "$PYTHON")/celery}"
[ -x "$CELERY" ] || CELERY="$(command -v celery)"

flush_redis() {
    echo "🔴 Flushing Redis (clearing queue, locks, results)..."
    "$PYTHON" -c "
import redis, sys
try:
    r = redis.from_url('redis://localhost:6379/0')
    r.flushdb()
    print('   ✅ Redis flushed —', r.dbsize(), 'keys remaining')
except Exception as e:
    print('   ⚠️  Redis flush failed (non-fatal):', e, file=sys.stderr)
" 2>&1 || true
}

kill_all() {
    flush_redis
    echo "⏹  Killing all Celery processes..."
    pkill -9 -f "celery_worker" 2>/dev/null || true
    pkill -9 -f "celery worker"  2>/dev/null || true
    pkill -9 -f "watchmedo"      2>/dev/null || true
    pkill -9 -f "ForkPoolWorker" 2>/dev/null || true
    sleep 1
    COUNT=$(pgrep -f "celery|ForkPool" | wc -l || echo 0)
    [ "$COUNT" -eq 0 ] && echo "✅ All clear." || echo "⚠️  $COUNT process(es) may still be running"
}

case "${1:-start}" in
    stop)
        kill_all
        ;;
    status)
        echo "=== Worker processes ==="
        ps aux | grep -E "celery|ForkPool" | grep -v grep || echo "(none running)"
        ;;
    start|*)
        kill_all
        echo ""
        echo "🚀 Starting Celery worker..."
        echo "   concurrency : 1  (GPU-safe — one task at a time)"
        echo "   CUDA alloc  : expandable_segments=True"
        echo "   GPU order   : PCI_BUS_ID (5070 Ti = cuda:0)"
        echo "   logs        : $BACKEND_DIR/celery.log"
        echo ""

        cd "$BACKEND_DIR"
        PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True \
        CUDA_DEVICE_ORDER=PCI_BUS_ID \
        "$CELERY" -A celery_worker worker \
            --loglevel=info \
            --concurrency=1 \
            >> celery.log 2>&1 &

        WPID=$!
        sleep 4

        if kill -0 "$WPID" 2>/dev/null; then
            WORKER_COUNT=$(pgrep -f "celery worker" | wc -l || echo 0)
            echo "✅ Worker running  (PID=$WPID, processes=$WORKER_COUNT)"
            echo ""
            echo "   To stop:   ./dev.sh stop"
            echo "   To reload: ./dev.sh  (kills old, starts fresh)"
            echo "   Tail logs: tail -f $BACKEND_DIR/celery.log"
        else
            echo "❌ Worker failed to start — check celery.log"
            tail -20 "$BACKEND_DIR/celery.log"
            exit 1
        fi
        ;;
esac
