#!/usr/bin/env python
"""
Closed-loop pipeline-quality improver for the Save Soil ad.

Each iteration:
    1. Run the full e2e via test_save_soil_e2e.py
    2. Score the resulting project with measure_project.py
    3. If verdict is GREAT — stop.
    4. Otherwise pick the highest-priority flag we know how to fix and apply
       a remediation from the FIX_REGISTRY.
    5. Restart celery so the worker picks up code changes.
    6. Loop.

Stops when:
    - verdict reaches GREAT
    - same flag fires N times in a row (we don't have a fix that helps)
    - max_iterations reached

Each cycle is ~30-45 minutes of GPU + LLM time, so leave it running.

Usage:
    python scripts/iterate_pipeline.py --max-iter 5
    python scripts/iterate_pipeline.py --target-score 85 --max-iter 10
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
PYTHON = "/home/akash/.pyenv/versions/video-app/bin/python"
LOG_DIR = ROOT / "logs" / "iterate"
LOG_DIR.mkdir(parents=True, exist_ok=True)


def log(msg: str) -> None:
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    (LOG_DIR / "iterate.log").open("a").write(line + "\n")


def restart_celery() -> bool:
    log("Restarting celery worker…")
    r = subprocess.run(["bash", str(ROOT / "dev.sh"), "start"],
                       capture_output=True, cwd=ROOT)
    return r.returncode == 0


def run_e2e() -> str | None:
    """Returns the project_id of the completed run, or None on failure."""
    log("Running e2e (this takes ~30-45 min)…")
    out_path = ROOT / "test_save_soil_e2e.out"
    proc = subprocess.run(
        [PYTHON, str(ROOT / "test_save_soil_e2e.py"),
         "--api", "http://localhost:8002"],
        capture_output=True, text=True, timeout=7200,
    )
    output = proc.stdout + proc.stderr
    out_path.write_text(output)
    m = re.search(r"Created project ([0-9a-f-]{36})", output)
    if not m:
        log("FAILED: could not extract project_id from e2e output")
        return None
    pid = m.group(1)
    log(f"e2e completed → project {pid} (exit {proc.returncode})")
    return pid


def measure(project_id: str) -> dict:
    log(f"Measuring project {project_id}…")
    r = subprocess.run(
        [PYTHON, str(ROOT / "scripts" / "measure_project.py"), project_id,
         "--api", "http://localhost:8002"],
        capture_output=True, text=True,
    )
    try:
        report = json.loads(r.stdout)
    except json.JSONDecodeError:
        log(f"measure failed: {r.stdout[:500]} / {r.stderr[:500]}")
        return {"score": 0, "verdict": "BROKEN", "flags": ["MEASURE_FAILED"]}
    log(f"  score={report['score']} verdict={report['verdict']} flags={report['flags']}")
    return report


# ── FIX REGISTRY ────────────────────────────────────────────────────────
# Each fix: a function that takes the report and applies a code change.
# Returns a short label (the fix description) or None if it can't help.

def fix_high_unlinked_char_rate(report: dict) -> str | None:
    """Tighten the scene_planner instruction to use exact canonical names."""
    f = ROOT / "backend" / "app" / "agents" / "scene_planner.py"
    text = f.read_text()
    marker = "# AUTO_ITER_FIX: char-name-strict-canonical"
    if marker in text:
        return None  # already applied
    addition = f"""
- CHARACTER NAMES: when filling `character_names`, use the EXACT canonical name as listed in KNOWN CHARACTERS above (including any parenthetical qualifiers like "(unseen, hands only)"). Do NOT shorten, paraphrase, or invent new names. {marker}"""
    if "RULES:" not in text:
        return None
    new = text.replace(
        "- CRITICAL: Focus heavily on the person",
        f"{addition}\n- CRITICAL: Focus heavily on the person",
        1,
    )
    if new == text:
        return None
    f.write_text(new)
    return "scene_planner: enforce exact canonical char names"


def fix_many_scenes_without_stills(report: dict) -> str | None:
    """Composite location plate as anchor for scenes lacking action stills.

    Already partially handled (we skip stills for unlinked scenes), so the
    real remediation here is to make sure those scenes still get a non-trivial
    conditioning input. This is enforced at scene_video.py — verify our
    earlier _select_conditioning fix is in.
    """
    f = ROOT / "backend" / "app" / "orchestration" / "stages" / "scene_video.py"
    text = f.read_text()
    if "if action_images or character:" not in text:
        return None  # earlier fix not present — bail to avoid rewriting
    return None  # nothing further automated; rely on char fuzzy + visual_director scope


def fix_character_hallucination(report: dict) -> str | None:
    """Already applied via visual_director scope-rule edit. If flag persists,
    bump the LLM temperature down to reduce drift."""
    f = ROOT / "backend" / "app" / "agents" / "visual_director.py"
    text = f.read_text()
    marker = "# AUTO_ITER_FIX: lower-temperature-for-scope"
    if marker in text:
        return None
    new = re.sub(
        r"temperature=0\.7,",
        f"temperature=0.4,  {marker}",
        text, count=1,
    )
    if new == text:
        return None
    f.write_text(new)
    return "visual_director: temperature 0.7 → 0.4 to reduce char-hallucination"


def fix_too_many_locations(report: dict) -> str | None:
    """Tighten the analyst's location budget further."""
    f = ROOT / "backend" / "app" / "agents" / "story_analyst.py"
    text = f.read_text()
    marker = "# AUTO_ITER_FIX: location-budget-tighter"
    if marker in text:
        return None
    new = text.replace(
        "target 1-3 locations TOTAL",
        f"target EXACTLY 1 location for ads under 30s, max 2 for ads under 60s {marker}",
        1,
    )
    if new == text:
        return None
    f.write_text(new)
    return "story_analyst: tighter location budget (1 for <30s ads)"


def fix_high_scene_similarity(report: dict) -> str | None:
    """Add explicit per-scene visual-distinctiveness instruction."""
    f = ROOT / "backend" / "app" / "agents" / "scene_planner.py"
    text = f.read_text()
    marker = "# AUTO_ITER_FIX: scene-visual-distinctiveness"
    if marker in text:
        return None
    addition = f"""
- VISUAL DISTINCTIVENESS: Each scene's visual_summary MUST be unmistakably different from the previous scene. If two consecutive scenes describe similar action (e.g. both show the protagonist walking), CHANGE the camera angle, time-of-day, or focal subject so they read as distinct shots, not continuous footage. {marker}"""
    new = text.replace(
        "- LOCATION REUSE — STRICT:",
        f"{addition}\n- LOCATION REUSE — STRICT:",
        1,
    )
    if new == text:
        return None
    f.write_text(new)
    return "scene_planner: enforce visual distinctiveness between consecutive scenes"


# Priority order — apply highest-priority unfixed flag first
FIX_PRIORITY = [
    ("CHARACTER_HALLUCINATION_IN_PROMPTS", fix_character_hallucination),
    ("HIGH_UNLINKED_CHAR_RATE",           fix_high_unlinked_char_rate),
    ("DUPLICATE_LOOKING_SCENES",          fix_high_scene_similarity),
    ("HIGH_SCENE_SIMILARITY",             fix_high_scene_similarity),
    ("TOO_MANY_LOCATIONS",                fix_too_many_locations),
    ("MANY_SCENES_WITHOUT_STILLS",        fix_many_scenes_without_stills),
]


def apply_fix(report: dict) -> str | None:
    for flag, fix_fn in FIX_PRIORITY:
        if flag in report["flags"]:
            applied = fix_fn(report)
            if applied:
                log(f"  → applied fix for {flag}: {applied}")
                return applied
            else:
                log(f"  → fix for {flag} not applicable / already applied")
    return None


def iterate(target_score: int, max_iter: int) -> int:
    history: list[dict] = []
    for i in range(1, max_iter + 1):
        log(f"━━━ Iteration {i}/{max_iter} ━━━")

        if not restart_celery():
            log("Celery restart failed; aborting.")
            return 2
        time.sleep(8)

        pid = run_e2e()
        if not pid:
            log("e2e failed; aborting iteration loop.")
            return 3

        report = measure(pid)
        history.append({"iter": i, "project_id": pid, **report})
        (LOG_DIR / "history.json").write_text(json.dumps(history, indent=2))

        if report["score"] >= target_score and report["verdict"] == "GREAT":
            log(f"✅ Target reached (score={report['score']}). Stopping.")
            return 0

        # Pick a fix
        fix_label = apply_fix(report)
        if not fix_label:
            log(f"❌ No automated fix available for flags {report['flags']} — manual intervention needed.")
            return 1

        # Bail if we keep applying the same kind of fix in a row (no progress)
        recent_fixes = [h.get("applied_fix") for h in history[-3:] if h.get("applied_fix")]
        history[-1]["applied_fix"] = fix_label
        if recent_fixes.count(fix_label) >= 2:
            log(f"⚠️  Same fix applied 3 times without effect. Bailing.")
            return 4

    log(f"⏱  Reached max_iter={max_iter} without hitting target. Last score: {history[-1]['score']}")
    return 5


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--target-score", type=int, default=85)
    p.add_argument("--max-iter", type=int, default=5)
    args = p.parse_args()
    return iterate(args.target_score, args.max_iter)


if __name__ == "__main__":
    sys.exit(main())
