#!/usr/bin/env python
"""Seed two cartoon-style Krishna ad projects.

1. Baby Krishna (Bal Krishna) playing the bamboo flute in Vrindavan.
2. Adult Krishna and Arjuna having a casual conversation on the chariot.

Both use wan22_text_only profile (default). Characters are described in
full inside the story_text so the story_analyst extracts a complete
canonical_name + physical_description + clothing_description block for
each one — that's what flows into every per-scene prompt.

Usage:
    python seed_krishna_ads.py                       # default api=http://localhost:8002
    python seed_krishna_ads.py --duration 30 --api http://localhost:8002
"""

from __future__ import annotations

import argparse
import sys

import requests


CARTOON_STYLE = (
    "2D animated cartoon style, vibrant flat colors, bold black outlines, "
    "cel-shaded, expressive lotus eyes, soft Indian devotional-poster look "
    "blended with modern cartoon-network energy, warm sunlit palette, "
    "no live action, no photorealism, no mirrors, no glass reflections"
)

# Full visual descriptions — story_analyst will pull these into canonical
# Character rows so EVERY downstream prompt re-states the look the same way.
BAL_KRISHNA = (
    "Bal Krishna is a chubby toddler with bright sky-blue skin, big round "
    "lotus-shaped black eyes, a tiny mischievous smile, soft black curly "
    "hair, and a single iridescent peacock feather tucked into his "
    "topknot. He wears a small bright-yellow silk dhoti with a thin gold "
    "border, layered gold necklaces and anklets that jingle when he moves, "
    "and a tiny gold waist-belt. He carries a slim polished bamboo flute "
    "with two gold rings near the mouth-piece."
)

ADULT_KRISHNA = (
    "Adult Krishna is a tall slender young man with deep sky-blue skin, "
    "long lotus-shaped black eyes, a calm half-smile, jet-black wavy hair "
    "swept back under a tall gold crown topped with a single iridescent "
    "peacock feather. He wears a flowing bright-yellow silk dhoti, a "
    "saffron sash across his bare chest, multi-strand gold necklaces, "
    "gold armlets and earrings shaped like makara (sea-creatures), and "
    "holds a polished bamboo flute."
)

ARJUNA = (
    "Arjuna is a tall muscular warrior in his prime with warm wheat-brown "
    "skin, sharp focused dark-brown eyes, a strong jaw, and long black "
    "hair tied back in a single braided knot at the crown. He wears "
    "silver-grey chainmail armor over an ivory tunic, a deep-blue waist "
    "sash, leather wrist-guards, a quiver of arrows slung across his "
    "back, and grips his great wooden bow Gandiva. A subtle warrior's "
    "tilak mark sits on his forehead."
)

ADS: list[tuple[str, str, float]] = [
    (
        "krishna_baby_flute",
        # Baby Krishna playing the flute by the Yamuna in Vrindavan.
        # Story_analyst will read the description block as the canonical
        # Bal Krishna character.
        f"{CARTOON_STYLE}.\n\n"
        f"Character: {BAL_KRISHNA}\n\n"
        "Setting: a sunlit cartoon Vrindavan riverbank with a calm blue "
        "Yamuna river, pink lotus blooms floating on the water, soft "
        "rolling green hills behind, and a single tall kadamba tree with "
        "wide green leaves and bright yellow blossoms.\n\n"
        "Story: Bal Krishna toddles to a smooth flat stone beside the "
        "river. He sits cross-legged with his peacock feather catching "
        "the morning sun. He lifts his bamboo flute to his lips and "
        "begins to play, eyes half-closed in a peaceful smile. Two "
        "spotted calves wander over and lower their heads to listen. "
        "A pair of yellow butterflies circle his shoulders. Bal Krishna "
        "tilts his head and plays one last long sweet note, then opens "
        "his eyes and grins straight at the viewer. Gentle Indian "
        "bamboo-flute melody throughout, soft river-water ambience, "
        "occasional bird-call.",
        30.0,
    ),
    (
        "krishna_arjuna_casual_chat",
        # Adult Krishna and Arjuna on the chariot, talking casually like
        # two old friends — not the Gita's intense battlefield moment.
        # Both characters get a full description block.
        f"{CARTOON_STYLE}.\n\n"
        f"Character 1: {ADULT_KRISHNA}\n\n"
        f"Character 2: {ARJUNA}\n\n"
        "Setting: a sturdy wooden war-chariot parked at the edge of a "
        "vast golden-grass Kurukshetra field at warm sunset, with four "
        "white horses standing calmly in front, harness bells gleaming. "
        "Soft saffron and pink sky behind them. No other soldiers in "
        "frame, no banners, no weapons drawn — a quiet pause before "
        "anything begins.\n\n"
        "Story: Adult Krishna leans casually against the chariot rail "
        "on the right, twirling his bamboo flute between two fingers. "
        "Arjuna stands beside him on the left, one hand resting on the "
        "chariot wall, the other holding Gandiva loosely at his side. "
        "Krishna says something light and Arjuna laughs, shaking his "
        "head. Krishna gestures with his flute toward the horizon as he "
        "speaks; Arjuna nods, glances at him with a small fond smile, "
        "and replies. Krishna pats Arjuna on the shoulder warmly. They "
        "share a quiet moment looking out across the field together. "
        "Warm low-volume tabla and sitar bed underneath, soft wind "
        "ambience, faint horse breathing.",
        30.0,
    ),
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://localhost:8002")
    parser.add_argument(
        "--duration", type=float, default=None,
        help="Override duration for both ads (defaults to per-ad value)",
    )
    args = parser.parse_args()

    created = 0
    for slug, story, default_dur in ADS:
        title = f"AD Krishna — {slug}"
        duration = args.duration if args.duration is not None else default_dur
        try:
            r = requests.post(
                f"{args.api}/api/projects",
                json={
                    "title": title,
                    "original_story_text": story,
                    "total_target_duration_seconds": duration,
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

    print(f"\nCreated {created}/{len(ADS)} Krishna ad projects.")
    print("Queue scanner will drain drafts FIFO once the current active project finishes.")
    return 0 if created == len(ADS) else 1


if __name__ == "__main__":
    sys.exit(main())
