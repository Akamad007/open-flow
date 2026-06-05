#!/usr/bin/env bash
# start_all.sh — start every service the video-app needs:
#   1. secrets-manager  (Django, :8010)  ── LLM API keys live here
#   2. backend uvicorn  (:8002)          ── FastAPI app
#   3. celery worker                     ── pipeline workers (1 task at a time)
#   4. frontend vite    (:5173)          ── React UI
#   5. queue scanner                     ── dispatches drafts FIFO-style
#
# Each service writes to /tmp/<service>.log. Idempotent: kills the
# matching process before relaunching. Redis is assumed up on :6379.
#
# Usage:  ./scripts/start_all.sh
#         ./scripts/start_all.sh stop      (kill all four)
#         ./scripts/start_all.sh status    (one line per service)

set -u

REPO=/home/akash/PycharmProjects/video-app
SECRETS=/home/akash/PycharmProjects/secrets-manager
PY_APP=/home/akash/.pyenv/versions/video-app/bin/python
PY_SECRETS=/home/akash/PycharmProjects/secrets-manager/venv/bin/python

start_infra() {
    cd "$REPO"
    docker compose up -d db redis >/dev/null
    until "$PY_APP" -c 'import redis; redis.from_url("redis://localhost:6379/0").ping()' 2>/dev/null; do sleep 1; done
    until docker compose exec -T db pg_isready -U storyvideouser -d storyvideo >/dev/null 2>&1; do sleep 1; done
    echo "✓ infra (db + redis)"
}

start_secrets() {
    pkill -f "manage.py runserver 127.0.0.1:8010" 2>/dev/null || true
    sleep 1
    cd "$SECRETS"
    setsid nohup "$PY_SECRETS" manage.py runserver 127.0.0.1:8010 --noreload \
        > /tmp/secrets_manager.log 2>&1 < /dev/null &
    disown
    until ss -tlnp 2>/dev/null | grep -q ':8010 '; do sleep 1; done
    echo "✓ secrets-manager  :8010"
}

start_backend() {
    pkill -f "uvicorn app.main:app" 2>/dev/null || true
    sleep 1
    cd "$REPO/backend"
    setsid nohup env PYTHONPATH=. "$PY_APP" -m uvicorn app.main:app \
        --host 0.0.0.0 --port 8002 --reload \
        > /tmp/backend_uvicorn.log 2>&1 < /dev/null &
    disown
    until curl -sf http://localhost:8002/api/pipelines >/dev/null 2>&1; do sleep 1; done
    echo "✓ backend uvicorn  :8002"
}

start_celery() {
    pkill -9 -f "celery -A celery_worker" 2>/dev/null || true
    pkill -9 -f "celery_worker" 2>/dev/null || true
    sleep 2
    "$PY_APP" -c "import redis; redis.from_url('redis://localhost:6379/0').flushdb()" 2>/dev/null || true
    cd "$REPO/backend"
    # Truncate so "celery ready" checks match THIS run, not a previous one.
    : > "$REPO/backend/celery-cpu.log"

    # One GPU worker per physical card, pinned via *_GPU_INDEX env and serving
    # its own `gpu{i}` queue. Per-project routing (app.utils.gpu_routing) sends
    # each project's GPU tasks to its assigned card, so N projects render in
    # parallel. gpu0 also drains the legacy `gpu` queue. concurrency=1 keeps
    # each card strictly one task at a time.
    NGPU=$(nvidia-smi -L 2>/dev/null | grep -c '^GPU ') || NGPU=0
    [ "$NGPU" -ge 1 ] || NGPU=1
    for i in $(seq 0 $((NGPU - 1))); do
        QUEUES="gpu$i"; [ "$i" -eq 0 ] && QUEUES="gpu0,gpu"
        LOG="$REPO/backend/celery-gpu$i.log"; : > "$LOG"
        setsid nohup env PYTHONPATH=. \
            PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True \
            CUDA_DEVICE_ORDER=PCI_BUS_ID \
            WAN22_GPU_INDEX=$i IMAGE_GEN_GPU_INDEX=$i AUDIO_GPU_INDEX=$i \
            "$PY_APP" -m celery -A celery_worker worker \
                --hostname=gpu$i@%h --queues="$QUEUES" --concurrency=1 \
                --loglevel=info \
            >> "$LOG" 2>&1 < /dev/null &
        disown
        until tail -200 "$LOG" 2>/dev/null | grep -qE "gpu$i@[^ ]+ ready"; do sleep 1; done
        echo "✓ celery gpu$i worker  (card $i, queues=$QUEUES)"
    done

    # CPU worker: story analysis, scene planning, prompt gen, audio plan,
    # consistency review, eval, cleanup. Runs in parallel with the GPU worker
    # so project B's prompts can be generated while project A's video renders.
    setsid nohup env PYTHONPATH=. \
        "$PY_APP" -m celery -A celery_worker worker \
            --hostname=cpu@%h --queues=cpu --concurrency=2 \
            --loglevel=info \
        >> "$REPO/backend/celery-cpu.log" 2>&1 < /dev/null &
    disown
    until tail -200 "$REPO/backend/celery-cpu.log" 2>/dev/null | grep -qE "cpu@[^ ]+ ready"; do sleep 1; done
    echo "✓ celery cpu worker  (log: backend/celery-cpu.log)"
}

start_frontend() {
    pkill -f "vite" 2>/dev/null || true
    sleep 1
    cd "$REPO/frontend"
    setsid nohup npm run dev > /tmp/frontend_vite.log 2>&1 < /dev/null &
    disown
    until ss -tlnp 2>/dev/null | grep -qE ':5173 |:5174 '; do sleep 1; done
    PORT=$(ss -tlnp 2>/dev/null | grep -oE ':51[0-9]+ ' | head -1 | tr -d ':' | tr -d ' ')
    echo "✓ frontend vite    :$PORT"
}

start_scanner() {
    pkill -f "scripts/queue_scanner.py" 2>/dev/null || true
    sleep 1
    cd "$REPO"
    setsid nohup "$PY_APP" scripts/queue_scanner.py \
        > /tmp/queue_scanner.log 2>&1 < /dev/null &
    disown
    sleep 2
    pgrep -f "scripts/queue_scanner.py" >/dev/null && echo "✓ queue scanner" || echo "✗ queue scanner FAILED — see /tmp/queue_scanner.log"
}

stop_all() {
    pkill -f "manage.py runserver 127.0.0.1:8010" 2>/dev/null || true
    pkill -f "uvicorn app.main:app" 2>/dev/null || true
    pkill -9 -f "celery -A celery_worker" 2>/dev/null || true
    pkill -9 -f "celery_worker" 2>/dev/null || true
    pkill -f "vite" 2>/dev/null || true
    pkill -f "scripts/queue_scanner.py" 2>/dev/null || true
    echo "✓ stopped all"
}

status_all() {
    echo "secrets-manager    $(ss -tlnp 2>/dev/null | grep -q ':8010 ' && echo UP || echo DOWN)"
    echo "backend uvicorn    $(curl -sf http://localhost:8002/api/pipelines >/dev/null 2>&1 && echo UP || echo DOWN)"
    echo "celery worker      $(pgrep -f 'celery -A celery_worker' >/dev/null && echo UP || echo DOWN)"
    echo "frontend vite      $(ss -tlnp 2>/dev/null | grep -qE ':5173 |:5174 ' && echo UP || echo DOWN)"
    echo "queue scanner      $(pgrep -f 'scripts/queue_scanner.py' >/dev/null && echo UP || echo DOWN)"
    if "$PY_APP" -c 'import redis; redis.from_url("redis://localhost:6379/0").ping()' 2>/dev/null; then
        echo "redis              UP"
    else
        echo "redis              DOWN"
    fi
}

case "${1:-start}" in
    stop)   stop_all ;;
    status) status_all ;;
    start|*)
        start_infra
        start_secrets
        start_backend
        start_celery
        start_frontend
        start_scanner
        echo ""
        echo "All services up. Logs:"
        echo "  /tmp/secrets_manager.log         /tmp/backend_uvicorn.log"
        echo "  $REPO/backend/celery-gpu*.log   $REPO/backend/celery-cpu.log   /tmp/frontend_vite.log"
        echo "  /tmp/queue_scanner.log"
        ;;
esac
