"""Standalone queue scanner daemon.

Runs `scan_and_dispatch()` every SCAN_INTERVAL_S seconds:
  - if no project is active, dispatch the oldest `draft` project that has story text
  - if any active project hasn't updated_at-moved for STUCK_THRESHOLD_S, force-fail it

This decouples scanning from the GPU-bound celery worker so the scan
keeps firing even while a 40-min Phantom-Wan scene is running.

Run via scripts/start_all.sh; logs to /tmp/queue_scanner.log.
"""
from __future__ import annotations

import asyncio
import logging
import sys
import time
from pathlib import Path

# Ensure backend/ is importable when run from repo root.
ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.orchestration.tasks.queue_scanner import scan_and_dispatch  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("queue_scanner")

SCAN_INTERVAL_S = 30


async def _run() -> None:
    log.info("queue_scanner: started, interval=%ds", SCAN_INTERVAL_S)
    last = ""
    while True:
        try:
            status = await scan_and_dispatch()
            if status != last:
                log.info("scan: %s", status)
                last = status
        except Exception:
            log.exception("scan failed")
        await asyncio.sleep(SCAN_INTERVAL_S)


if __name__ == "__main__":
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        pass
