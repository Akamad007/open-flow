#!/usr/bin/env python
"""Seed 10 cartoon-style ad projects (15s each, wan22_image_seeded profile).

POSTs all 10 to /api/projects. The first one auto-triggers the pipeline;
the rest get queued as drafts and the queue_scanner drains them FIFO.

Usage:
    python seed_cartoon_ads.py            # default api=http://localhost:8002
    python seed_cartoon_ads.py --api http://localhost:8002
"""

from __future__ import annotations

import argparse
import sys

import requests

# Shared cartoon style — vibrant 2D animation, bold outlines, flat colors.
# Each scene depicts ONE friendly mascot character. No mirrors.
CARTOON_STYLE = (
    "2D animated cartoon style, vibrant flat colors, bold black outlines, "
    "cel-shaded, expressive eyes, modern Cartoon Network look, no live "
    "action, no photorealism"
)

ADS: list[tuple[str, str]] = [
    (
        "cartoon_toothbrush_mascot",
        f"{CARTOON_STYLE}. A cheerful blue toothbrush mascot named Brushy "
        "with big white eyes and a friendly smile dances around a shiny "
        "white tooth, leaving sparkle trails. Brushy hops on top of the "
        "tooth, brushes vigorously side to side, then strikes a confident "
        "thumbs-up pose. Bright pastel kitchen background, no mirrors. "
        "Brushy says, 'Smile bright with Brushy!' Playful kids' jingle.",
    ),
    (
        "cartoon_cloud_weather",
        f"{CARTOON_STYLE}. A round fluffy cloud mascot named Nimbus with "
        "tiny rainboot feet skips across a bright blue sky. Nimbus winks, "
        "shoots out a tiny rainbow from his side, and balances a glowing "
        "sun on his head. Solid sky-blue background, no buildings, no "
        "reflective surfaces. Nimbus says, 'Know the sky with Nimbus!' "
        "Upbeat weather-app jingle.",
    ),
    (
        "cartoon_sneaker_kids",
        f"{CARTOON_STYLE}. A bouncy red sneaker character named Zippy "
        "with cartoon eyes on the toe-cap leaps across a green park "
        "lawn. Zippy springs high, lands with a puff of dust, then dashes "
        "forward leaving a comet trail. Sunny park background with "
        "rolling hills, no mirrors. Zippy says, 'Run free with Zippy!' "
        "Energetic kid-pop track.",
    ),
    (
        "cartoon_owl_learning",
        f"{CARTOON_STYLE}. A wise purple owl mascot named Professor Hoot "
        "wearing round spectacles perches on a giant open storybook. "
        "Hoot flips pages with a wing, a small lightbulb appears above "
        "his head, then he winks and tips his glasses. Warm library "
        "background with tall bookshelves, no mirrors. Hoot says, "
        "'Learn smart with Professor Hoot!' Gentle wise-and-warm jingle.",
    ),
    (
        "cartoon_bee_honey",
        f"{CARTOON_STYLE}. A plump yellow bee mascot named Buzzie with "
        "big sparkly eyes hovers around a bright sunflower. Buzzie dips "
        "her tiny hand into the flower's center, pulls out a glowing "
        "honey drop, and licks her lips happily. Sunny meadow "
        "background, no reflective surfaces. Buzzie says, 'Sweet pure "
        "Buzzie honey!' Cheerful folk-pop jingle.",
    ),
    (
        "cartoon_bear_mattress",
        f"{CARTOON_STYLE}. A sleepy brown bear cub mascot named Snoozy "
        "in fuzzy blue pajamas yawns and stretches on a fluffy cloud-"
        "shaped mattress. Snoozy flops onto the mattress, snuggles into "
        "a pillow, and closes his eyes with a contented smile. Pastel "
        "kids' bedroom background with stars on the wall, no mirrors. "
        "Snoozy says, 'Dream big with Snoozy!' Soothing lullaby jingle.",
    ),
    (
        "cartoon_oak_notebook",
        f"{CARTOON_STYLE}. A friendly oak tree mascot named Oaky with a "
        "smiling bark face and leafy arms holds up a green notebook. "
        "Oaky shakes the notebook proudly, sprinkles tiny acorns from "
        "his branches, then plants a sapling in the ground. Bright "
        "forest clearing background, no mirrors. Oaky says, 'Write "
        "green with Oaky!' Wholesome eco-folk jingle.",
    ),
    (
        "cartoon_sun_cereal",
        f"{CARTOON_STYLE}. A glowing yellow sun mascot named Sunny with "
        "a wide cheerful grin pours sparkling cereal from his rays into "
        "a giant bowl. Sunny tips the bowl toward the camera, the "
        "cereal pieces dance in the milk, and Sunny gives a big thumbs-"
        "up. Sunny kitchen background with a window of blue sky, no "
        "mirrors. Sunny says, 'Start bright with Sunny!' Catchy "
        "morning-cereal jingle.",
    ),
    (
        "cartoon_robot_toy",
        f"{CARTOON_STYLE}. A boxy silver robot mascot named Bolt with "
        "big round eyes and antennae rolls across a colorful kid's "
        "playroom floor. Bolt waves a metal arm, flashes lights on his "
        "chest, then spins in a happy little dance. Bright playroom "
        "background with toy shelves, no mirrors or glass. Bolt says, "
        "'Play with Bolt!' Bouncy electronic-toy jingle.",
    ),
    (
        "cartoon_wand_magic",
        f"{CARTOON_STYLE}. A sparkling purple magic wand mascot named "
        "Whizzy with a glowing star tip and tiny gloved hands hovers "
        "above a magician's table. Whizzy spins in a circle, shoots "
        "sparkles into the air, then taps the table to reveal a rabbit "
        "popping out of a hat. Velvety magic-show stage background "
        "with dark curtains, no mirrors. Whizzy says, 'Make magic with "
        "Whizzy!' Whimsical sparkle-filled jingle.",
    ),
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://localhost:8002")
    parser.add_argument("--duration", type=float, default=15.0)
    args = parser.parse_args()

    created = 0
    for slug, story in ADS:
        title = f"AD cartoon — {slug}"
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
            print(f"✓ {slug:30s} id={data['id']} status={data.get('status')}")
            created += 1
        except requests.RequestException as e:
            print(f"✗ {slug:30s} failed: {e}", file=sys.stderr)
    print(f"\nCreated {created}/{len(ADS)} cartoon ad projects.")
    print("Queue scanner will drain drafts FIFO once the current active project finishes.")
    return 0 if created == len(ADS) else 1


if __name__ == "__main__":
    sys.exit(main())
