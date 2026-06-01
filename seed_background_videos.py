#!/usr/bin/env python
"""Seed silent-background music-video projects.

Creates a project per long-form video, then PATCHes its auto-created
Episode 0 to skip_audio=true so the final render is video-only — the
user overlays their own narration/song externally.

Current seeds:
- ganesha_bal_kailash : 291s (4:51) cartoon background for a bhajan track
- vivekananda_life    : 304s (5:04) biographical narrative background

Usage:
    python seed_background_videos.py
    python seed_background_videos.py --api http://localhost:8002
"""

from __future__ import annotations

import argparse
import sys
import time

import requests


CARTOON_STYLE = (
    "2D animated cartoon style, vibrant flat colors, bold black outlines, "
    "cel-shaded, expressive lotus eyes, soft Indian devotional-poster look "
    "blended with modern cartoon-network energy, warm sunlit palette, "
    "no live action, no photorealism, no mirrors, no glass reflections"
)


BAL_GANESHA = (
    "Bal Ganesha is a chubby toddler with bright golden-saffron skin, a "
    "small elephant head with rosy round cheeks, big curling ears like soft "
    "leaves, a short trunk curved cheerfully to one side, two tiny ivory "
    "tusks, kind half-moon eyes, and four soft little arms — two folded in "
    "his lap, one holding a tiny ladoo, one holding a small bamboo flute "
    "near his lips. He wears a bright-red silk dhoti with gold embroidery "
    "around the hem, layered pearl and gold necklaces, gold armbands, "
    "anklets with bells, and a small gold crown topped with a single white "
    "lotus bud. A friendly smile, eyes that twinkle when he sings."
)

GANESHA_STORY = (
    f"{CARTOON_STYLE}.\n\n"
    f"Character: {BAL_GANESHA}\n\n"
    "Setting: a serene cartoon Mount Kailash at golden dawn — soft snowy "
    "peaks behind, glowing pink-orange sky, a wide flat moss-covered rock "
    "as Ganesha's seat, fluffy clouds drifting below, a small mountain "
    "stream curling around the rock, white lotus flowers and small wild "
    "blossoms scattered around. No other deities in frame, no buildings, "
    "no glass, no mirrors, no reflections.\n\n"
    "Story: Bal Ganesha sits cross-legged on the moss-covered rock in the "
    "middle of Kailash. He raises his small bamboo flute to his trunk and "
    "begins to sing softly to himself, eyes half-closed in joy. The "
    "sunlight grows; a gentle breeze ruffles his red dhoti. A pair of "
    "white doves flutters past him and circles overhead. A small spotted "
    "mouse — his vahana Mushak — peeks out from behind the rock, twitching "
    "its whiskers in time with the song. A garland of white lotuses "
    "blooms one petal at a time on the stream beside him. Bal Ganesha "
    "sways gently as he sings, lifts the ladoo with one of his lower "
    "hands and offers it skyward, then closes his eyes in bliss. Slow "
    "drifting clouds and soft falling petals throughout. The camera "
    "slowly orbits and pulls back to reveal the full vast snowy Kailash "
    "stage, then settles on Bal Ganesha glowing at the centre of frame "
    "as the dawn fully arrives. A peaceful, devotional, slow-paced "
    "music-video background — let every beat be unhurried and lyrical."
)


VIVEKANANDA_DESC = (
    "Swami Vivekananda is a tall composed monk in his late twenties with "
    "warm wheat-brown skin, sharp focused dark eyes, a strong jaw, a "
    "trimmed dark moustache, and short jet-black hair. He wears flowing "
    "saffron monastic robes — long kurta and dhoti — with a saffron "
    "turban wrapped around his head. He carries a wooden danda walking "
    "staff and wears simple rudraksh-bead malas around his neck. His "
    "expression is calm, his posture upright, his gaze steady. Drawn in "
    "the same 2D cartoon style across every scene — soft expressive "
    "features, no photorealism."
)

VIVEKANANDA_STORY = (
    f"{CARTOON_STYLE}.\n\n"
    f"Character: {VIVEKANANDA_DESC}\n\n"
    "Setting: a sweeping cartoon journey across India and the West — "
    "Bengal riverbanks, dusty colonial-era Calcutta streets, a small "
    "monastic ashram with palm trees, the iconic Chicago Parliament hall "
    "with grand pillars and a velvet-draped lectern, foggy London "
    "rooftops, a quiet Himalayan trail. No other named historical "
    "figures in frame, no real photographs, no rendered text or "
    "newspaper headlines.\n\n"
    "Story (animated biographical montage): Young Narendra reads a "
    "Sanskrit book by lamplight in a Calcutta home. He walks alone "
    "through the streets at dawn searching, deep in thought. He sits "
    "across from a glowing kind elder mystic on a riverbank — his guru "
    "Ramakrishna's silhouette suggested with a soft halo, never a "
    "literal portrait. After receiving a quiet blessing, Narendranath "
    "takes monastic vows: he changes into saffron robes by a small fire, "
    "picks up a wooden staff, and begins to walk across the Indian "
    "countryside. He climbs into the Himalayas, meditates beside a "
    "snowy stream, then descends and boards a great steamer ship. He "
    "stands at the prow of the ship watching the ocean. He arrives at "
    "the grand Chicago Parliament hall, steps to the lectern, lifts his "
    "arms wide, and the hall erupts into silent applause around him "
    "(no on-screen text, just the visual gesture of a standing "
    "ovation). He travels through misty Western cities, lectures to "
    "rapt small gatherings, walks through London fog, returns by ship. "
    "Back in India, he climbs a stone temple staircase, walks through "
    "a busy bazaar lifting his hand in blessing, and founds an ashram "
    "where children gather around him. The final beat: Vivekananda "
    "stands alone on a Himalayan ridge at sunset, staff in hand, "
    "looking outward at the horizon — calm, complete. Slow, dignified, "
    "documentary-paced cartoon. Soft sweeping camera moves; no quick "
    "cuts. Let the silence carry it — this is a background for an "
    "external narration."
)


PROJECTS: list[dict] = [
    {
        "slug": "ganesha_bal_kailash",
        "title": "Bal Ganesha singing on Kailash — bhajan background",
        "story": GANESHA_STORY,
        "duration_seconds": 291.0,  # 4:51
    },
    {
        "slug": "vivekananda_life",
        "title": "Swami Vivekananda — animated biographical background",
        "story": VIVEKANANDA_STORY,
        "duration_seconds": 304.0,  # 5:04
    },
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://localhost:8002")
    args = parser.parse_args()

    created = 0
    for proj in PROJECTS:
        try:
            # Create project (auto-creates Episode 0 with audio enabled).
            r = requests.post(
                f"{args.api}/api/projects",
                json={
                    "title": proj["title"],
                    "original_story_text": proj["story"],
                    "total_target_duration_seconds": proj["duration_seconds"],
                    "pipeline_profile": "wan22_text_only",
                },
                timeout=30,
            )
            r.raise_for_status()
            pdata = r.json()
            pid = pdata["id"]

            # Brief wait for the API's flush to land, then flip Episode 0's
            # skip_audio flag. The episode is still in 'draft' or 'analyzing'
            # at this point so PATCH is allowed.
            time.sleep(0.5)
            eps = requests.get(f"{args.api}/api/projects/{pid}/episodes", timeout=15)
            eps.raise_for_status()
            ep0 = eps.json()[0]
            patch = requests.patch(
                f"{args.api}/api/episodes/{ep0['id']}",
                json={"skip_audio": True},
                timeout=15,
            )
            patch.raise_for_status()

            print(
                f"✓ {proj['slug']:24s} project={pid} episode={ep0['id']} "
                f"duration={proj['duration_seconds']:.0f}s skip_audio=true "
                f"status={pdata.get('status')}"
            )
            created += 1
        except requests.RequestException as e:
            print(f"✗ {proj['slug']:24s} failed: {e}", file=sys.stderr)

    print(f"\nCreated {created}/{len(PROJECTS)} silent-background projects.")
    print("Queue scanner will drain drafts FIFO once the current project finishes.")
    print("Final renders will be SILENT MP4s — overlay your own audio externally.")
    return 0 if created == len(PROJECTS) else 1


if __name__ == "__main__":
    sys.exit(main())
