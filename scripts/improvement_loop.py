"""Autonomous improvement loop. Each cycle:
  1. Create 2 ads (rotating prompt list).
  2. Wait for both pipelines to finish.
  3. Score each via eval_run.py — read the JSON written to docs/runs/.
  4. Identify the WEAKEST non-saturated metric across the pair.
  5. Apply a corresponding fix from FIX_REGISTRY (one fix per cycle).
  6. Restart celery to load the change.
  7. Repeat.

Logs everything to docs/runs/LOOP.md so you can see iter-over-iter
progress without watching the worker output.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / "docs" / "runs"
LOOP_LOG = RUNS / "LOOP.md"
PYTHON = "/home/akash/.pyenv/versions/video-app/bin/python"
API = "http://localhost:8002"

# Two-ad rotation. Mix sub-styles to surface different failure modes.
ADS = [
    ("krishna_butter",
     "A 12-second whimsical cinematic ad — if Krishna walked into this "
     "life today, how would he eat butter? A young man in his late 20s, "
     "with a soft blue undertone to his skin, dark curly hair pinned with "
     "a single peacock feather, wearing a saffron-yellow modern hoodie, "
     "stands in a sunlit minimalist kitchen and opens a stainless-steel "
     "fridge to reveal a single glass jar of golden butter glowing on the "
     "middle shelf. He lifts the jar out, dips two fingers into the "
     "butter, brings them to his lips with a slow mischievous grin, "
     "looks straight at the camera and says, 'Some habits travel through "
     "ages.' Warm window light, saffron-and-blue palette, intimate "
     "medium close-up, 35mm grain, playful timeless mood."),
    ("running_shoes",
     "A 12-second cinematic ad for performance running shoes. A man in "
     "his early 30s in a charcoal performance tee laces a bright orange "
     "running shoe on a stone city stoop at dawn. He stands, pushes off "
     "the curb, and breaks into a steady stride down a quiet street. "
     "He glances at camera and says, 'No excuses today.' Cool dawn blue "
     "fading to amber sunrise, low handheld camera, 35mm grain, kinetic."),
    ("coffee_morning",
     "A 12-second cinematic ad for an artisan coffee brand. A man in his "
     "early 30s in a charcoal sweater stands at a sunlit kitchen counter "
     "and pours a thin steady stream of dark coffee from a pour-over kettle "
     "into a white ceramic mug. He lifts the mug, inhales the steam, takes "
     "a slow sip, and says, 'Mornings made right.' Warm window light, "
     "cream-and-espresso palette, 35mm grain, intimate quiet."),
    ("denim_jacket",
     "A 12-second cinematic ad for a heritage denim jacket. A man in his "
     "late 20s with stubble and a dark grey scarf shrugs on a rich indigo "
     "denim jacket on a cobblestone street at golden hour. He buttons the "
     "front, runs both hands down the lapels, and looks up at the camera. "
     "He says, 'It only gets better.' Warm late-day side light, indigo "
     "and amber palette, 35mm grain, fashion editorial."),
]


def _post_project(title: str, prompt: str, profile: str | None = None) -> str | None:
    payload = {
        "title": f"LOOP — {title}",
        "original_story_text": prompt,
        "total_target_duration_seconds": 12.0,
    }
    if profile:
        payload["pipeline_profile"] = profile
    r = requests.post(f"{API}/api/projects", json=payload, timeout=30)
    if r.status_code != 201:
        _log(f"  POST {title} failed: HTTP {r.status_code} {r.text[:200]}")
        return None
    return r.json()["id"]


def _project_status(pid: str) -> str:
    r = requests.get(f"{API}/api/projects/{pid}", timeout=15)
    if r.status_code != 200:
        return "unknown"
    return r.json().get("status", "unknown")


def _wait_complete(pid: str, timeout_s: int = 7200) -> str:
    start = time.time()
    last = ""
    while time.time() - start < timeout_s:
        s = _project_status(pid)
        if s != last:
            _log(f"  [{int(time.time()-start)}s] {pid[:8]} → {s}")
            last = s
        if s in ("complete", "failed"):
            return s
        time.sleep(20)
    return "timeout"


def _grade(pid: str) -> dict | None:
    """Run eval_run.py; read the JSON it writes to docs/runs/."""
    short = pid[:8]
    before = {p.name for p in RUNS.glob(f"*__{short}.json")}
    r = subprocess.run([PYTHON, str(ROOT / "eval_run.py"), pid],
                       capture_output=True, text=True, timeout=900)
    if r.returncode != 0:
        _log(f"  eval failed for {short}: {r.stderr[-300:]}")
        return None
    after = sorted(p for p in RUNS.glob(f"*__{short}.json") if p.name not in before)
    if not after:
        return None
    return json.loads(after[-1].read_text())


def _restart_celery() -> None:
    _log("  restarting celery to load fix...")
    subprocess.run(["pkill", "-KILL", "-f", "celery -A celery_worker"], check=False)
    time.sleep(3)
    backend = ROOT / "backend"
    subprocess.Popen(
        [PYTHON, "-m", "celery", "-A", "celery_worker", "worker",
         "--loglevel=info", "--concurrency=1"],
        cwd=str(backend),
        stdout=open("/tmp/celery_worker.log", "ab"),
        stderr=subprocess.STDOUT,
        env=os.environ,
    )
    # wait for ready
    log = Path("/tmp/celery_worker.log")
    deadline = time.time() + 90
    start_size = log.stat().st_size if log.exists() else 0
    while time.time() < deadline:
        if log.exists() and log.stat().st_size > start_size:
            try:
                tail = log.read_bytes()[-4000:].decode(errors="ignore")
                if "celery@" in tail and "ready" in tail:
                    _log("  celery ready")
                    return
            except OSError:
                pass
        time.sleep(2)
    _log("  WARNING: celery readiness check timed out")


# ── Fix registry ────────────────────────────────────────────────────────────
# Each entry: (metric_id, threshold, name, fn). fn(grade_a, grade_b) applies
# a single edit and returns a description of what changed. fn returns None
# if the fix is not applicable (so we move on to the next candidate).

CONFIG_PY = ROOT / "backend" / "app" / "config.py"
LTX_GENERATE = ROOT / "ltx_generate.py"
VISUAL_DIRECTOR = ROOT / "backend" / "app" / "prompts" / "visual_director.txt"
LTX_PROVIDER = ROOT / "backend" / "app" / "providers" / "video" / "ltx_provider.py"


def fix_m11_face_consistency(a, b) -> str | None:
    """M11 face consistency: tighten the visual_director's character
    description rule so the per-second beats name the SAME identifying
    physical features each beat (face, hair, build) — gives LTX a
    stronger text-side identity anchor without touching image_pregen
    (user explicitly disabled it). One-shot: only fires once."""
    txt = VISUAL_DIRECTOR.read_text()
    marker = "IDENTITY ECHO (HARD)"
    if marker in txt:
        return None
    new = txt.replace(
        "DIMENSION 4 — CAMERA",
        "  " + marker + ": every per-second beat must include the "
        "character's face/hair anchor (e.g. 'the woman with chestnut "
        "ponytail and warm tan skin' or whatever the source story "
        "specifies). Even when the action is hands-only or torso-only, "
        "name the identity-bearing features so LTX has a text-anchor "
        "for face geometry across all 6s. Never let the character "
        "become 'she' or 'the figure' mid-scene.\n\nDIMENSION 4 — CAMERA",
    )
    if new == txt:
        return None
    VISUAL_DIRECTOR.write_text(new)
    return "added IDENTITY ECHO rule to visual_director (target M11 text-anchor)"


def fix_m6_multi_person(a, b) -> str | None:
    """If M6 < 0.95, expand the single-subject negative prompt."""
    txt = LTX_PROVIDER.read_text()
    addon = "lone subject only, no extras, "
    needle = '"two people, multiple people, second person, extra person, crowd, "'
    if addon in txt or needle not in txt:
        return None
    LTX_PROVIDER.write_text(
        txt.replace(needle, '"' + addon + 'two people, multiple people, second person, extra person, crowd, "')
    )
    return "expanded single-subject negative prompt (target M6)"


def fix_m9_verb_distinctness(a, b) -> str | None:
    """If M9 < 0.8, strengthen verb-diversity rule in visual_director."""
    txt = VISUAL_DIRECTOR.read_text()
    marker = "VERB DIVERSITY (HARD)"
    if marker in txt:
        return None
    insertion = (
        "\n  " + marker + ": every per-second beat must lead with a "
        "DIFFERENT action verb than the previous beat. "
        "If you wrote 'kneels' at 1-2s, do NOT write 'continues to kneel' "
        "at 2-3s — write 'leans', 'reaches', 'plants hand', etc. "
        "Verb root may not repeat across consecutive beats.\n"
    )
    new = txt.replace(
        "  EVERY scene must have a mini-arc",
        insertion + "  EVERY scene must have a mini-arc",
    )
    if new == txt:
        return None
    VISUAL_DIRECTOR.write_text(new)
    return "added VERB DIVERSITY rule to visual_director (target M9)"


def fix_m7_motion(a, b) -> str | None:
    """If M7 < 0.6, demand camera move per beat in visual_director."""
    txt = VISUAL_DIRECTOR.read_text()
    marker = "CAMERA MOVE PER BEAT (HARD)"
    if marker in txt:
        return None
    new = txt.replace(
        "STRONG BIAS: prefer **wide",
        marker + ": every per-second beat must specify a camera move "
        "(slow dolly-in / pan-left / parallax handheld / orbit / push-out). "
        "Static medium close-ups for back-to-back beats are forbidden.\n\n"
        "  STRONG BIAS: prefer **wide",
    )
    if new == txt:
        return None
    VISUAL_DIRECTOR.write_text(new)
    return "added CAMERA MOVE PER BEAT rule (target M7)"


def fix_m12_full_body(a, b) -> str | None:
    """If M12 < 0.6, add 'cropped body' entries to LTX negative prompt
    so the model is penalised for waist-up / bust-shot framings on
    motion beats. One-shot: marker guards re-fire."""
    txt = LTX_PROVIDER.read_text()
    marker = "cropped figure, cut-off feet, partial body, waist-up, "
    if marker in txt:
        return None
    needle = "background figure, bystander, duplicate character, twin"
    if needle not in txt:
        return None
    LTX_PROVIDER.write_text(
        txt.replace(needle, needle + ", " + marker.rstrip(", "))
    )
    return "added cropped-body negative tokens to LTX prompt (target M12)"


FIX_REGISTRY = [
    ("M6",  0.95, fix_m6_multi_person),
    ("M11", 0.85, fix_m11_face_consistency),
    ("M12", 0.65, fix_m12_full_body),
    ("M9",  0.80, fix_m9_verb_distinctness),
    ("M7",  0.60, fix_m7_motion),
]


def _pick_fix(grade_a: dict, grade_b: dict) -> tuple[str, str] | None:
    """Pick the highest-priority fix whose mean(metric) across the two
    ads is below threshold. Single-ad outliers still pull the average."""
    ma, mb = grade_a["metrics"], grade_b["metrics"]
    for metric, threshold, fn in FIX_REGISTRY:
        key = next((k for k in ma if k.startswith(metric + "_")), None)
        if not key:
            continue
        va, vb = ma.get(key), mb.get(key)
        if va is None or vb is None:
            continue
        avg = (va + vb) / 2
        if avg < threshold:
            desc = fn(grade_a, grade_b)
            if desc:
                return (metric, desc)
    return None


def _log(msg: str) -> None:
    line = f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    LOOP_LOG.parent.mkdir(parents=True, exist_ok=True)
    if not LOOP_LOG.exists():
        LOOP_LOG.write_text("# Improvement loop log\n\n")
    with LOOP_LOG.open("a") as fh:
        fh.write(line + "\n")


MAX_CYCLES = 10


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default=None,
                    help="pipeline_profile to test (default: server-side default)")
    ap.add_argument("--cycles", type=int, default=MAX_CYCLES)
    ap.add_argument("--per-project-timeout-s", type=int, default=7200)
    args = ap.parse_args()

    if args.profile:
        _log(f"### LOOP profile={args.profile}")

    cycle = 0
    ad_idx = 0
    while cycle < args.cycles:
        cycle += 1
        _log(f"### Cycle {cycle}/{args.cycles}")
        # Pick 2 ads
        a_slug, a_prompt = ADS[ad_idx % len(ADS)]
        b_slug, b_prompt = ADS[(ad_idx + 1) % len(ADS)]
        ad_idx += 2

        _log(f"  POST {a_slug}")
        a_pid = _post_project(a_slug, a_prompt, profile=args.profile)
        if not a_pid:
            time.sleep(60)
            continue

        # Wait for a to finish before posting b (one-active gate)
        _wait_complete(a_pid, timeout_s=args.per_project_timeout_s)

        _log(f"  POST {b_slug}")
        b_pid = _post_project(b_slug, b_prompt, profile=args.profile)
        if not b_pid:
            time.sleep(60)
            continue
        _wait_complete(b_pid, timeout_s=args.per_project_timeout_s)

        # Grade both
        grade_a = _grade(a_pid)
        grade_b = _grade(b_pid)
        if grade_a is None or grade_b is None:
            _log("  grading failed for one of them, skipping fix this cycle")
            continue

        _log(f"  {a_slug} auto={grade_a['auto_total']:.3f}")
        _log(f"  {b_slug} auto={grade_b['auto_total']:.3f}")
        for k in sorted(grade_a["metrics"]):
            va, vb = grade_a["metrics"][k], grade_b["metrics"][k]
            if va is None or vb is None:
                continue
            _log(f"    {k}: a={va:.2f} b={vb:.2f}")

        # Apply fix
        picked = _pick_fix(grade_a, grade_b)
        if picked is None:
            _log("  no fix applies (all metrics above thresholds, or fixes exhausted)")
        else:
            metric, desc = picked
            _log(f"  FIX (target {metric}): {desc}")
            _restart_celery()


if __name__ == "__main__":
    main()
