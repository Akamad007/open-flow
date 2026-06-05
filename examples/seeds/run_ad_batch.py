#!/usr/bin/env python
"""Run a batch of PSA-style ad prompts through the full pipeline, one at a
time. For each prompt: create a project, poll until the pipeline reaches
a terminal state, record success/failure + final video path. After the
batch, print a summary table.

Usage:
    python run_ad_batch.py
    python run_ad_batch.py --duration 12 --timeout 5400
    python run_ad_batch.py --only "save_soil,plant_a_tree"

The default prompt set is 8 PSAs covering the same shape as Save Soil
(narrator + one other on-screen action per scene). Each runs end-to-end
through analyze → plan → prompts → audio_plan → review → images →
videos → audio → stitch. Failures are logged and the batch continues.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Optional

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_save_soil_e2e import get_assets, get_project, post_project  # noqa: E402

TERMINAL = {"complete", "failed"}


# Diverse ads covering PSA, beverage, food, sport, tech, beauty,
# automotive, travel, fashion, fitness. Each story is self-contained:
# ONE on-screen protagonist + ONE clear visible action per scene + a short
# hero line at the end. Stories avoid second-character interactions
# (the pipeline enforces one character per 6s scene).
#
# Values are either a plain string (uses the CLI --duration default) or a
# dict {"prompt": str, "duration": float} for per-ad duration overrides.
ADS: dict[str, str | dict] = {
    "save_soil": (
        "A cinematic public-service ad for Save Soil. Sadhguru, in his white "
        "robe and turban, kneels on parched cracked earth and lets dry soil "
        "fall through his fingers. He looks directly at the camera and says, "
        "'We have less than 50 years of farmable soil. Save Soil — it is in "
        "your hands.' Warm cinematic grade, 35mm grain, contemplative."
    ),
    "soft_drink_cola": (
        "A 12-second cinematic ad for an ice-cold cola. A young man in a "
        "white t-shirt at a sunlit kitchen counter pops the metal tab on a "
        "frosted glass bottle of cola — vapour curls off the rim. He raises "
        "the bottle and takes a long pull, his face relaxing in pure relief. "
        "He sets it down and says quietly, 'That's the moment.' Warm summer "
        "lighting, condensation droplets in macro, vibrant reds, 35mm grain."
    ),
    "instant_noodles": (
        "A 12-second cinematic ad for premium instant noodles. A woman in "
        "her late 20s in a soft beige cardigan stands in a small modern "
        "kitchen, lifts a tangle of golden noodles from a steaming bowl with "
        "chopsticks, and inhales the steam with a slow smile. She turns to "
        "the camera and says, 'Five minutes. One bowl. Home.' Warm window "
        "light, steam catching the light, intimate close-up, 35mm grain."
    ),
    "running_shoes": (
        "A 12-second cinematic ad for performance running shoes. A man in "
        "his early 30s in a charcoal performance tee laces a bright orange "
        "running shoe on a stone city stoop at dawn. He stands, pushes off "
        "the curb, and breaks into a steady stride down a quiet street. "
        "He glances at camera and says, 'No excuses today.' Cool dawn blue "
        "fading to amber sunrise, low handheld camera, 35mm grain, kinetic."
    ),
    "smartphone_camera": (
        "A 12-second cinematic ad for a smartphone camera. A woman in her "
        "20s in a denim jacket stands on a rain-slick city street at "
        "dusk, raises a sleek matte-black phone with both hands, and "
        "frames a shot of a glowing neon sign. The phone screen shows the "
        "captured image, sharper than the scene around her. She lowers it "
        "and says, 'See it the way you saw it.' Neon-lit cyan/magenta "
        "palette, shallow depth, 35mm grain, contemporary."
    ),
    "skincare_serum": (
        "A 12-second cinematic ad for a hydrating skincare serum. A woman "
        "in her 30s with bare shoulders sits at a marble bathroom counter "
        "in soft morning light. She tips a glass dropper of clear serum "
        "onto her fingertips and presses it gently across her cheek and "
        "jaw. She turns to a wall mirror, then to the camera and says, "
        "'Skin you can feel.' Soft diffused warm light, pearl-white "
        "palette, macro on the dropper, 35mm grain, premium intimate."
    ),
    "electric_car": (
        "A 12-second cinematic ad for an electric SUV. A woman in her "
        "late 30s in a tailored grey coat stands on a cliffside overlook "
        "next to a glossy black electric SUV. She runs her hand along the "
        "door, pulls the handle, and the door opens silently. She turns "
        "back to the camera and says, 'Quiet is the new powerful.' Cool "
        "overcast coastal light, slate and graphite palette, slow dolly, "
        "35mm grain, premium documentary."
    ),
    "airline_travel": (
        "A 12-second cinematic ad for a premium airline. A businesswoman "
        "in her 40s in a navy suit walks down a sun-bleached jet bridge "
        "with a leather carry-on, pauses at the cabin door, and looks "
        "back over her shoulder. She gives a small nod and says, 'Let's "
        "go somewhere new.' Crisp natural daylight, white and navy "
        "palette, shallow depth, 35mm grain, calm aspirational."
    ),
    "denim_jacket": (
        "A 12-second cinematic ad for a heritage denim jacket. A man in "
        "his late 20s with stubble and a dark grey scarf shrugs on a "
        "rich indigo denim jacket on a cobblestone street at golden "
        "hour. He buttons the front, runs both hands down the lapels, "
        "and looks up at the camera. He says, 'It only gets better.' "
        "Warm late-day side light, indigo and amber palette, 35mm grain, "
        "fashion editorial."
    ),
    "yoga_mat": (
        "A 12-second cinematic ad for a sustainable yoga mat. A woman "
        "in her 30s in a sage tank top kneels on a sun-dappled wooden "
        "studio floor and unrolls a deep-green textured yoga mat with "
        "both hands, smoothing it flat. She sits cross-legged on the "
        "mat, places her hands on her knees, and says, 'Start where you "
        "are.' Soft natural daylight, sage-and-oak palette, low-angle "
        "wide shot, 35mm grain, calm grounded mood."
    ),
    "coffee_morning": (
        "A 12-second cinematic ad for an artisan coffee brand. A man in "
        "his early 30s in a charcoal sweater stands at a sunlit kitchen "
        "counter and pours a thin steady stream of dark coffee from a "
        "pour-over kettle into a white ceramic mug. He lifts the mug, "
        "inhales the steam, takes a slow sip, and says, 'Mornings made "
        "right.' Warm window light, cream-and-espresso palette, 35mm "
        "grain, intimate quiet."
    ),
    "luxury_watch": (
        "A 12-second cinematic ad for a luxury mechanical watch. A man "
        "in his late 40s in a navy suit sits at a leather-topped desk "
        "in a wood-paneled study, fastens a polished steel watch to his "
        "wrist, and adjusts the clasp. He turns his wrist, glances down "
        "at the dial, then up at camera and says, 'Time, on your "
        "terms.' Warm tungsten side light, deep brown and steel "
        "palette, shallow depth, 35mm grain, refined gravitas."
    ),
    "clean_water_psa": (
        "A 12-second cinematic public-service ad for a clean-water "
        "charity. A woman in her 20s in a beige linen shirt crouches "
        "beside a dusty hand-pump in a sunbaked rural field, places a "
        "clay bowl under the spout, and watches a clear stream of water "
        "fill it. She lifts the bowl, looks at camera and says, 'Water "
        "is the first promise.' Warm dust-lit afternoon, ochre and "
        "white palette, 35mm grain, hopeful documentary."
    ),
    "krishna_butter": (
        "A 12-second whimsical cinematic ad — if Krishna walked into "
        "this life today, how would he eat butter? A young man in "
        "his late 20s, with a soft blue undertone to his skin, dark "
        "curly hair pinned with a single peacock feather, wearing a "
        "saffron-yellow modern hoodie, stands in a sunlit minimalist "
        "kitchen and opens a stainless-steel fridge to reveal a "
        "single glass jar of golden butter glowing on the middle "
        "shelf. He lifts the jar out, dips two fingers into the "
        "butter, brings them to his lips with a slow mischievous "
        "grin, looks straight at the camera and says, 'Some habits "
        "travel through ages.' Warm window light, saffron-and-blue "
        "palette, intimate medium close-up, 35mm grain, playful "
        "timeless mood."
    ),
    "outdoor_backpack": (
        "A 12-second cinematic ad for a mountain hiking backpack. A "
        "man in his late 30s in a forest-green technical jacket "
        "shoulders a charcoal hiking pack on a windswept alpine ridge, "
        "tightens the chest strap, and faces the open valley. He "
        "glances over his shoulder at camera and says, 'Carry less, go "
        "further.' Cool overcast mountain light, slate-and-pine "
        "palette, wide low-angle, 35mm grain, rugged adventurous."
    ),
    # 60-second hero ad — 10 scenes × 6s. Single protagonist, one
    # continuous visual style, builds across blocks, San Francisco
    # locations woven through.
    "sf_runner_woman": {
        "duration": 60.0,
        "prompt": (
            "A 60-second cinematic ad for a women's running brand. "
            "A woman in her late 20s in a cobalt-blue running tank, "
            "black technical shorts, and white running shoes runs "
            "through the streets of San Francisco from dawn to "
            "midday. She begins on the Embarcadero with the Bay "
            "Bridge behind her at first light, then climbs the steep "
            "sidewalks of Russian Hill, descends past the painted "
            "Victorians of Alamo Square (Postcard Row) with morning "
            "fog burning off, threads through the pastel facades of "
            "the Mission District, crosses a quiet Chinatown alley "
            "as shopkeepers raise their shutters, sprints across the "
            "wide pier promenade by the Ferry Building, climbs the "
            "stairs cut into Telegraph Hill toward Coit Tower, "
            "passes the wind-rippled grass at the Marina Green with "
            "the Golden Gate Bridge filling the background, and "
            "finishes on a sunlit Crissy Field path looking out to "
            "the open bay. Throughout she keeps a steady runner's "
            "stride, head up, breathing rhythmic. In the closing "
            "scene she slows, turns to camera, and says, 'The city "
            "is the run.' Warm dawn-blue fading to amber to clean "
            "midday daylight, full-body framing, photorealistic "
            "35mm film grain, kinetic but grounded."
        ),
    },
}


@dataclass
class AdResult:
    slug: str
    project_id: Optional[str] = None
    final_status: Optional[str] = None
    elapsed_s: float = 0.0
    error: Optional[str] = None
    video_path: Optional[str] = None
    asset_count: int = 0
    stage_failures: list[str] = field(default_factory=list)


def _final_video_path(api: str, project_id: str) -> Optional[str]:
    try:
        assets = get_assets(api, project_id)
    except (requests.RequestException, ValueError) as e:
        # Don't kill the batch over a stray API hiccup on the assets endpoint.
        print(f"  [assets fetch error: {e}]", file=sys.stderr)
        return None
    finals = [a for a in assets if a.get("asset_type") == "final_video"]
    if not finals:
        return None
    return finals[-1].get("file_path")


def _stage_failures(api: str, project_id: str) -> list[str]:
    try:
        jobs = requests.get(f"{api}/api/projects/{project_id}/jobs", timeout=10).json()
    except requests.RequestException:
        return []
    return [
        f"{j.get('job_type')}:{(j.get('error_text') or '').splitlines()[0][:80]}"
        for j in jobs if j.get("status") == "failed"
    ]


def _wait_terminal(api: str, project_id: str, timeout_s: int, poll_s: int) -> str:
    start = time.time()
    last = ""
    while time.time() - start < timeout_s:
        try:
            proj = get_project(api, project_id)
        except requests.RequestException as e:
            print(f"  [poll error] {e}", file=sys.stderr)
            time.sleep(poll_s)
            continue
        status = proj.get("status", "?")
        if status != last:
            elapsed = int(time.time() - start)
            print(f"  [{elapsed:>5}s] status: {last or '-'} → {status}", flush=True)
            last = status
        if status in TERMINAL:
            return status
        time.sleep(poll_s)
    return "timeout"


def _run_one(api: str, slug: str, prompt: str, duration: float,
             timeout_s: int, poll_s: int) -> AdResult:
    res = AdResult(slug=slug)
    start = time.time()
    title = f"AD batch — {slug}"
    print(f"\n=== {slug} ===")
    print(f"  duration={duration}s timeout={timeout_s}s")
    try:
        project = post_project(api, title, prompt, duration)
    except requests.RequestException as e:
        res.error = f"create failed: {e}"
        res.elapsed_s = time.time() - start
        return res
    res.project_id = project["id"]
    print(f"  project_id={res.project_id} status={project.get('status')}")

    res.final_status = _wait_terminal(api, res.project_id, timeout_s, poll_s)
    res.elapsed_s = time.time() - start
    res.video_path = _final_video_path(api, res.project_id)
    try:
        res.asset_count = len(get_assets(api, res.project_id))
    except (requests.RequestException, ValueError):
        res.asset_count = 0
    res.stage_failures = _stage_failures(api, res.project_id)
    return res


def _run_one_with_retries(
    api: str, slug: str, prompt: str, duration: float,
    timeout_s: int, poll_s: int, retries: int,
) -> AdResult:
    """Run an ad up to retries+1 times; return the first success or the last
    attempt's result. Each retry creates a fresh project (no resume) so a
    transient celery/GPU hiccup on one attempt doesn't poison the next."""
    last: Optional[AdResult] = None
    for attempt in range(retries + 1):
        if attempt > 0:
            print(f"  ↻ retry {attempt}/{retries} for {slug}")
        r = _run_one(api, slug, prompt, duration, timeout_s, poll_s)
        if r.final_status == "complete":
            return r
        last = r
        # Don't retry if the prompt itself was rejected during create
        if r.error and "create failed" in r.error:
            break
    return last  # type: ignore[return-value]


def _print_summary(results: list[AdResult]) -> None:
    print("\n" + "=" * 78)
    print("BATCH SUMMARY")
    print("=" * 78)
    width_slug = max(len(r.slug) for r in results) + 1
    for r in results:
        marker = "OK " if r.final_status == "complete" else "FAIL"
        if r.final_status == "timeout":
            marker = "TIMEOUT"
        v = (r.video_path or "(none)")
        print(f"  [{marker:>7}] {r.slug:<{width_slug}} {int(r.elapsed_s):>5}s "
              f"assets={r.asset_count:>2}  video={v}")
        if r.error:
            print(f"            error: {r.error}")
        for fail in r.stage_failures:
            print(f"            stage_fail: {fail}")
    n_ok = sum(1 for r in results if r.final_status == "complete")
    print(f"\n  {n_ok}/{len(results)} completed end-to-end")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--api", default="http://localhost:8002")
    p.add_argument("--duration", type=float, default=12.0)
    p.add_argument("--timeout", type=int, default=5400,
                   help="Per-ad timeout in seconds (default 90 min)")
    p.add_argument("--poll", type=int, default=10)
    p.add_argument("--only", default=None,
                   help="Comma-separated subset of slugs (e.g. 'save_soil,vote')")
    p.add_argument("--retries", type=int, default=2,
                   help="Number of retries per ad on failure/timeout (default 2 = 3 total attempts)")
    args = p.parse_args()

    if args.only:
        wanted = {s.strip() for s in args.only.split(",") if s.strip()}
        ads = {k: v for k, v in ADS.items() if k in wanted}
        missing = wanted - ads.keys()
        if missing:
            print(f"Unknown slugs: {sorted(missing)}", file=sys.stderr)
            return 2
    else:
        ads = ADS

    print(f"Batch: {len(ads)} ad(s) — slugs: {', '.join(ads.keys())}")
    print(f"API={args.api} duration={args.duration}s timeout={args.timeout}s/ad")

    results: list[AdResult] = []
    for slug, entry in ads.items():
        if isinstance(entry, dict):
            prompt = entry["prompt"]
            duration = float(entry.get("duration", args.duration))
        else:
            prompt = entry
            duration = args.duration
        try:
            r = _run_one_with_retries(
                args.api, slug, prompt, duration,
                args.timeout, args.poll, args.retries,
            )
        except KeyboardInterrupt:
            print("\nInterrupted; printing partial summary.")
            results.append(AdResult(slug=slug, error="interrupted"))
            break
        results.append(r)

    _print_summary(results)
    n_ok = sum(1 for r in results if r.final_status == "complete")
    return 0 if n_ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
