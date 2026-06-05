#!/usr/bin/env bash
# Watchdog: every 10s, emit a single status line.
#  - Restarts celery if it died.
#  - Detects stuck active projects (no log progress in last 5 min).
#  - Surfaces any new error line from celery.log.
#
# Designed to be run under Claude's Monitor tool — each stdout line becomes
# a notification, so the LLM sees state changes in near-real-time.
set -u
REPO=/home/akash/PycharmProjects/video-app
LOG=$REPO/backend/celery.log
PY=/home/akash/.pyenv/versions/video-app/bin/python
BACKEND=http://localhost:8002

prev_status=""
prev_log_pos=$(wc -c < "$LOG" 2>/dev/null || echo 0)
tick=0

start_celery() {
    cd "$REPO/backend"
    setsid nohup env PYTHONPATH=. \
        PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True \
        CUDA_DEVICE_ORDER=PCI_BUS_ID \
        "$PY" -m celery -A celery_worker worker --loglevel=info --concurrency=1 \
        >> "$LOG" 2>&1 < /dev/null & disown
    local t=0
    until tail -100 "$LOG" 2>/dev/null | grep -q "celery@.*ready"; do
        sleep 1; t=$((t+1)); [ $t -gt 30 ] && break
    done
}

while true; do
    tick=$((tick + 1))
    ts=$(date +%H:%M:%S)

    # 1. Celery alive?
    if ! pgrep -f "celery -A celery_worker" > /dev/null 2>&1; then
        echo "[$ts] ⚠ celery DEAD — restarting"
        start_celery
        echo "[$ts] ✓ celery restarted"
        prev_log_pos=$(wc -c < "$LOG" 2>/dev/null || echo 0)
    fi

    # 2. Current active wan22 project
    summary=$(curl -s "$BACKEND/api/projects" 2>/dev/null | \
        $PY -c "
import json, sys
try:
    ps = json.loads(sys.stdin.read())
except Exception as e:
    print(f'api_error:{e}'); sys.exit(0)
ours = [p for p in ps if p.get('pipeline_profile') == 'wan22_text_only']
active = [p for p in ours if p.get('status') not in ('draft','complete','failed')]
done = sum(1 for p in ours if p['status'] == 'complete')
failed = sum(1 for p in ours if p['status'] == 'failed')
drafts = sum(1 for p in ours if p['status'] == 'draft')
if active:
    a = active[0]
    print(f\"active={a['title']}|{a['status']} done={done}/{len(ours)} failed={failed} drafts={drafts}\")
else:
    print(f\"idle done={done}/{len(ours)} failed={failed} drafts={drafts}\")
")

    # 3. New errors in log since last tick?
    cur_pos=$(wc -c < "$LOG" 2>/dev/null || echo 0)
    if [ "$cur_pos" -gt "$prev_log_pos" ]; then
        new=$(tail -c +$((prev_log_pos+1)) "$LOG" 2>/dev/null | \
            grep -E "Wan22 failed|Traceback|RuntimeError|CUSOLVER|CUDA out|Adapter name|Scene [a-f0-9-]+ generated: (ok|failed)" | head -5)
        if [ -n "$new" ]; then
            while IFS= read -r line; do
                echo "[$ts] $line"
            done <<< "$new"
        fi
        prev_log_pos=$cur_pos
    fi

    # 4. Heartbeat — print status if changed, or every 6 ticks (≈ 1 min)
    if [ "$summary" != "$prev_status" ] || [ $((tick % 6)) -eq 0 ]; then
        echo "[$ts] $summary"
        prev_status="$summary"
    fi

    sleep 10
done
