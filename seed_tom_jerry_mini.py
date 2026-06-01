#!/usr/bin/env python
"""Seed a Tom & Jerry cartoon mini-series — 5 super-funny 30s shorts.

Each short is a one-gag chase between Tom (cat) and Jerry (mouse), styled
like the classic Hanna-Barbera cartoon. Both characters are mascots from
the new character_kind classifier's perspective, so the portrait builder
will render them as cartoon animals, not photoreal humans.

POSTs all 5 to /api/projects. First auto-triggers the pipeline; the rest
queue as drafts and the queue_scanner drains them FIFO.

Usage:
    python seed_tom_jerry_mini.py            # default api=http://localhost:8002
    python seed_tom_jerry_mini.py --api http://localhost:8002
"""

from __future__ import annotations

import argparse
import sys

import requests

CARTOON_STYLE = (
    "Classic Hanna-Barbera Tom and Jerry 2D animation style, vibrant flat "
    "cel-shaded colors, bold black ink outlines, expressive squash-and-stretch "
    "poses, exaggerated cartoon physics, bright cheerful palette, no live "
    "action, no photorealism, no mirrors or reflective surfaces"
)

# Each story names BOTH Tom (cat) and Jerry (mouse) so they're extracted as
# two mascot characters. Stories describe one clean gag, escalating in 3
# beats so the scene planner can split it into per-character scenes.
EPISODES: list[tuple[str, str]] = [
    (
        "tomjerry_cheese_caper",
        f"{CARTOON_STYLE}. Jerry the small brown mouse with big round ears "
        "tiptoes across a sunny kitchen counter, eyes locked on an enormous "
        "wedge of yellow Swiss cheese. Jerry grabs the cheese and grins. "
        "Tom the lanky gray-and-white cat with a pink nose pops up behind a "
        "blender, eyes bugging out, and lunges at Jerry. Jerry zips off the "
        "counter; Tom skids face-first into the cheese, his head pops "
        "through a cheese hole, and he looks dazed as Jerry waves from a "
        "tiny mouse-hole holding a smaller piece of cheese. Slapstick "
        "boings, kazoos and pratfall sound cues throughout. Super funny.",
    ),
    (
        "tomjerry_vacuum_showdown",
        f"{CARTOON_STYLE}. Tom the gray-and-white cat with mischievous "
        "yellow eyes plugs in a giant red vacuum cleaner, smirking at the "
        "camera. Tom aims the hose at a mouse hole. Jerry the tiny brown "
        "mouse pokes his head out, sees the hose, and pulls a tiny pair of "
        "sunglasses down over his eyes. Jerry yanks the hose, flipping Tom "
        "upside down. The vacuum sucks Tom in headfirst; only his striped "
        "legs stick out, kicking. Jerry pops out and waves victoriously, "
        "perched on top of the bag. Cartoon suction whirrs, pratfall thuds, "
        "comedic boing on the flip. Super funny.",
    ),
    (
        "tomjerry_pie_duel",
        f"{CARTOON_STYLE}. Jerry the small brown mouse balances a giant "
        "cream pie on his tiny paws, eyes sparkling, perched on a kitchen "
        "shelf. Jerry hurls the pie. Tom the gray-and-white cat with a pink "
        "nose ducks just in time — the pie smacks a portrait on the wall. "
        "Tom grabs an even bigger pie from the counter and winds up. Jerry "
        "pulls down a tiny chef's hat and grins. Tom throws; Jerry "
        "side-steps; the pie boomerangs back, smacking Tom square in the "
        "face. Tom stands frozen, eyes blinking through cream, while Jerry "
        "tap-dances victoriously. Squishy splats, boings, victory horns. "
        "Super funny.",
    ),
    (
        "tomjerry_mousetrap_mishap",
        f"{CARTOON_STYLE}. Tom the lanky gray cat with bushy whiskers "
        "sets an oversized wooden mousetrap baited with a fat yellow "
        "cheese cube. Tom snickers and crouches behind a chair, paws "
        "rubbing together. Jerry the brown mouse with a tiny red bow tie "
        "creeps in, sniffs the cheese, then pulls out a pair of cartoon "
        "scissors and snips the trap's trigger string. The trap "
        "back-snaps onto Tom's tail; Tom rockets straight up, ears "
        "flattened, eyes saucer-wide. Jerry walks off with the cheese, "
        "humming a jaunty tune. Spring-load twangs, comedic ascending "
        "whistle, cymbal crash on the trap-snap. Super funny.",
    ),
    (
        "tomjerry_soapy_floor_chase",
        f"{CARTOON_STYLE}. Jerry the tiny brown mouse with round black "
        "eyes spills a giant bottle of dish soap across a checkerboard "
        "kitchen floor, then dives behind a chair. Tom the gray-and-white "
        "cat charges in claws-out chasing nothing, hits the soap, and "
        "skates wildly on all fours, arms windmilling. Tom slides into a "
        "pile of pots and pans, sending them flying like a brass-band "
        "explosion. Jerry calmly skates by on a tiny piece of soap, "
        "wearing tiny goggles, salutes the camera, and vanishes into a "
        "mouse hole. Squeaky skids, comedic crashes, kazoo flourishes. "
        "Super funny.",
    ),
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://localhost:8002")
    parser.add_argument("--duration", type=float, default=30.0)
    args = parser.parse_args()

    created = 0
    for slug, story in EPISODES:
        title = f"AD Tom&Jerry — {slug}"
        try:
            r = requests.post(
                f"{args.api}/api/projects",
                json={
                    "title": title,
                    "original_story_text": story,
                    "total_target_duration_seconds": args.duration,
                    "pipeline_profile": "wan22_text_only",
                },
                timeout=30,
            )
            r.raise_for_status()
            data = r.json()
            print(f"✓ {slug:32s} id={data['id']} status={data.get('status')}")
            created += 1
        except requests.RequestException as e:
            print(f"✗ {slug:32s} failed: {e}", file=sys.stderr)
    print(f"\nCreated {created}/{len(EPISODES)} Tom & Jerry mini-series projects.")
    print("Queue scanner will drain drafts FIFO once the current active project finishes.")
    return 0 if created == len(EPISODES) else 1


if __name__ == "__main__":
    sys.exit(main())
