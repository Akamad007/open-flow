"""Watch the projects table for newly-complete projects and auto-grade
them with eval_run.py. Appends a one-line summary to docs/runs/AUTO.md
so we don't have to manually score each batch ad.

Polls every 60s; only grades projects updated in the last 12h whose
auto-grade JSON doesn't already exist.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / "docs" / "runs"
AUTO_LOG = RUNS / "AUTO.md"
PYTHON = "/home/akash/.pyenv/versions/video-app/bin/python"


def _completed_projects() -> list[tuple[str, str, datetime]]:
    sql = (
        "SELECT id::text, COALESCE(title,''), updated_at FROM projects "
        "WHERE status='complete' AND updated_at > NOW() - INTERVAL '12 hours' "
        "ORDER BY updated_at DESC;"
    )
    out = subprocess.check_output(
        ["psql", "-h", "localhost", "-U", "storyvideouser", "-d", "storyvideo",
         "-tAF", "|", "-c", sql],
        env={**os.environ, "PGPASSWORD": "storyvideopass"},
        timeout=15,
    ).decode()
    rows: list[tuple[str, str, datetime]] = []
    for line in out.strip().splitlines():
        parts = line.split("|", 2)
        if len(parts) != 3:
            continue
        rows.append((parts[0], parts[1], datetime.fromisoformat(parts[2])))
    return rows


def _already_graded(pid: str) -> bool:
    short = pid[:8]
    return any(RUNS.glob(f"*__{short}.json"))


def _grade(pid: str, title: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] grading {title} ({pid[:8]})...", flush=True)
    before = {p.name for p in RUNS.glob(f"*__{pid[:8]}.json")}
    res = subprocess.run(
        [PYTHON, str(ROOT / "eval_run.py"), pid],
        capture_output=True, text=True, timeout=600,
    )
    if res.returncode != 0:
        print(f"  ERROR: {res.stderr[-300:]}", flush=True)
        return
    after = sorted(p for p in RUNS.glob(f"*__{pid[:8]}.json") if p.name not in before)
    if not after:
        print("  (no new JSON written, skipping)", flush=True)
        return
    data = json.loads(after[-1].read_text())
    metrics = data["metrics"]
    auto = data["auto_total"]
    line = (
        f"- `{pid[:8]}` **{title}** auto={auto:.3f} "
        f"M5={metrics['M5_pose_variance']:.2f} "
        f"M11={metrics['M11_video_face_consistency']:.2f} "
        f"M7={metrics['M7_motion_magnitude']:.2f} "
        f"({datetime.now(timezone.utc).strftime('%H:%M')})\n"
    )
    AUTO_LOG.parent.mkdir(parents=True, exist_ok=True)
    if not AUTO_LOG.exists():
        AUTO_LOG.write_text("# Auto-grade log (F-NO-STILL-PINS batch)\n\n")
    with AUTO_LOG.open("a") as fh:
        fh.write(line)
    print(f"  graded → {line.strip()}", flush=True)


def main() -> None:
    seen: set[str] = set()
    while True:
        try:
            for pid, title, _ in _completed_projects():
                if pid in seen or _already_graded(pid):
                    seen.add(pid)
                    continue
                _grade(pid, title)
                seen.add(pid)
        except Exception as exc:  # noqa: BLE001 — long-running loop
            print(f"  loop error: {exc}", flush=True)
        time.sleep(60)


if __name__ == "__main__":
    main()
