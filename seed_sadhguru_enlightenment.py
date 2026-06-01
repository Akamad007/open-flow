#!/usr/bin/env python
"""Seed a 3-minute (~36 scene) episode on young Jaggi Vasudev's awakening
on Chamundi Hill, Mysore, on the afternoon of September 23, 1982.

One project, one Episode 0, target 180s. The planner targets ~5s/scene →
~36 scenes. The narrative is structured as 9 location-arcs of ~4 beats
each so backgrounds change roughly every 4 scenes while continuity inside
each arc reads as a single moment. STRICTLY one character throughout.

Usage:
    python seed_sadhguru_enlightenment.py
    python seed_sadhguru_enlightenment.py --api http://localhost:8002
"""

from __future__ import annotations

import argparse
import sys

import requests


STYLE = (
    "Studio Ghibli inspired semi-realistic anime, hand-painted watercolor "
    "backgrounds, lush detailed South Indian nature, soft cinematic "
    "painterly lighting, delicate line work, warm earth-toned palette of "
    "ochre, terracotta, deep green, dusty rose and twilight gold, "
    "supremely beautiful composition. Single character throughout — no "
    "other people anywhere in any scene, no crowds, no bystanders, no "
    "passersby, no family. All motion slow, deliberate, breath-paced and "
    "contemplative — no fast cuts, no jittery motion, no quick action, no "
    "live action, no photorealism, no 3D-render look, no harsh outlines, "
    "no mirrors, no glass reflections."
)

JAGGI = (
    "Jaggi is a young South Indian Tamil man, twenty-five years old, of "
    "medium height and lean athletic build with strong shoulders, "
    "warm sun-tanned brown skin slightly darker on the cheekbones and "
    "forearms. He has a full head of jet-black hair, short and softly "
    "tousled, parted naturally. A neat black mustache sits above his "
    "upper lip. His eyes are dark, deep-set, bright, sparkling with "
    "playful intelligence and unmistakable joy. A wide easy grin lives "
    "on his face — teeth showing, eyes creasing — the smile of a young "
    "man fully alive and delighted by his own life. Soft strong jaw, "
    "faint stubble shadow. His body language is vivid and athletic: "
    "shoulders loose, chest open, light on his feet, every movement "
    "showing buoyant unspent energy — but each motion itself is slow "
    "and deliberate, no fast cuts, no motion blur. He wears a plain "
    "pale cream cotton half-sleeve shirt tucked into dark olive cotton "
    "trousers and simple worn leather sandals. No jewelry, no watch, "
    "no beard, no robes. He is the only person on screen at all times."
)


STORY_BODY = """
Setting: Mysore, Karnataka, South India, in the early 1980s. Dusty
sun-bleached small-city streets lined with tamarind trees, an old red
brick poultry shed at the edge of town, a half-built two-storey concrete
house with bamboo scaffolding, the narrow winding road climbing Chamundi
Hill above Mysore, and at the very top a great flat granite outcrop
overlooking the green Deccan plain. Painted throughout in Ghibli
watercolor with hand-painted skies and rich South Indian flora —
flame-of-the-forest trees, jacaranda, neem, banana fronds, distant
paddy fields. Only one human figure appears in any scene, ever: young
Jaggi.

The episode follows the ordinary afternoon of a twenty-five-year-old
entrepreneur who rides his motorcycle up Chamundi Hill on September the
twenty-third, nineteen eighty-two, sits on a rock with his eyes open,
and is reorganised entirely. The pacing is slow, breath-paced, reverent.

NARRATIVE ORDER IS STRICTLY LINEAR. The story moves only forward
through Arcs 1 → 9 once and ends with the descent. Do NOT loop back
to the morning, the poultry shed, the building site, or the ride out
after Arc 7. Do NOT repeat earlier locations after the rock. Every
scene after Arc 6 takes place on the rock or on the descending road —
nowhere else. The final scene of the episode is the last beat of Arc
9: Jaggi walking the bike down through golden light, forever changed.

ARC 1 — Joyful morning in Mysore (small dusty city street, golden
morning). Young Jaggi bursts out of a low ochre-walled house onto a
quiet sunlit street with a wide easy grin, alone — no other people
anywhere. He tilts his face up to the bright South Indian sky and
laughs once, openly, eyes squinting in the sun. He bounds down the
empty lane between tamarind trees with long buoyant strides, hands
loose at his sides. He reaches his parked Czech-made motorcycle, slaps
the dusty fuel tank with affection, swings a leg over the seat, and
flashes a delighted look toward the green ridge of Chamundi Hill on
the horizon as if it were a friend.

ARC 2 — Poultry farm and building site, full of life (edge of town,
late morning). Jaggi alone inside a long red brick poultry shed, dust
motes spinning in slanted light, striding down the central aisle with
the ledger tucked under one arm and a grin still on his face. He
crouches lightly to check a feed trough, springs back up, makes a note
without breaking pace. Outside, alone on the half-built concrete
second floor with bamboo scaffolding, he walks the unfinished wall
sure-footed as an acrobat, balances briefly on one foot at the corner
for the joy of it, then leaps down onto the lower slab and lands light
and laughing. He claps mortar dust off his palms and grins out at the
town below.

ARC 3 — Riding out toward the hill (open road at the edge of Mysore,
midday). Jaggi alone astride his motorcycle on a long straight road,
neem trees flickering past on either side, hair lifted by the warm
wind, mustache and grin both wide. The camera holds on his face —
sun-tanned, eyes bright with delight, the smile of a man perfectly at
home in his own body and his own afternoon. He leans confidently into
a curve, body and bike one motion. The green dome of Chamundi Hill
rises ahead. The road begins to climb.

ARC 4 — Climbing Chamundi Hill (winding mountain road, early
afternoon). The motorcycle carves smoothly through hairpin turns under
flame-of-the-forest trees in full bloom, orange petals drifting down
around him like confetti. Jaggi alone, exhilarated, taking each curve
with practised pleasure. He throws his head back once and laughs aloud
at the sheer beauty of the climb. The Mysore plain spreads far below
in soft watercolor haze, paddy fields and the white needle of the
palace. He takes the last bend with easy skill.

ARC 5 — Arriving at the top, the rock (open clearing near the summit,
afternoon). He brakes lightly on a patch of red dirt at the edge of a
clearing and swings off the bike in one fluid athletic motion before
it has fully stopped rocking. He kicks down the stand, claps the seat,
strides through dry grass toward a broad flat granite outcrop the size
of a small house, sun-warm and weathered. He vaults up onto it with
the easy spring of a young man whose body has never refused him,
straightens to his full height on the rock, and grins out over the
whole green valley spread below — king of his own afternoon.

ARC 6 — Sitting on the rock (top of Chamundi Hill, mid afternoon).
Still grinning, Jaggi drops cross-legged into the centre of the great
flat rock, hands resting easily on his knees, eyes wide open and
bright. The warm wind tousles his short black hair. Far below, the
patchwork of fields and town. A pair of black kites circle silently in
the high blue sky. He is not meditating — he has never meditated and
would laugh at the idea. He is simply sitting for a few minutes
before riding back, full of life, looking out at the world he has
always known. The shadow of the kites slides slowly across the rock.
His grin softens, very gradually, into a quiet open look of attention.

ARC 7 — The boundary dissolves (close on Jaggi on the rock, afternoon
light shifting). Close on his face — eyes still open, suddenly very
still. A small breath catches in his throat. The fine line where his
skin ends and the air begins seems, for one impossible instant, to
soften. Pull wider — his hand rests on the warm granite and he can no
longer say where his palm stops and the stone begins. Wider still — the
trees at the edge of the clearing, the wind, the distant valley, the
circling kites, are all somehow inside him. His eyes brim. He does not
move.

ARC 8 — Vastness (the rock and the whole valley, light moving across
the sky). The sun shifts perceptibly across the sky behind him, shadows
on the rock lengthening, then shortening again as if time itself is
breathing. Jaggi sits unmoving in the centre of the frame, tears
running freely down his sun-tanned cheeks, mouth softly open in
something between laughter and weeping. The valley below glows. A
single silent black kite drifts past at eye level. He is alone on the
rock and yet, in his face, plainly not alone in any way he has words
for.

ARC 9 — Coming back, the long walk down (the rock to the road to the
foothills, late afternoon deepening into golden hour). He blinks, very
slowly, the way someone wakes from a dream they want to remember.
He brings his hands up before his eyes and turns them over with
startled wonder — palms, backs, the small lines of his fingertips,
all of it new. He presses one open palm against his own chest and
breathes, feeling the warmth there. He lowers his hands to his lap
and looks out at the valley — the same valley as before, and
completely changed. A long shaft of late sun reaches across the rock
to his face. He smiles, very softly — a different smile now, no
teeth, no grin, just a deep quiet warmth in his eyes. He uncrosses
his legs with the care of a man learning to use his body for the
first time. He climbs down off the granite outcrop hand by hand. He
stands a moment beside the warm rock and lays his palm on it in
silent thanks. He walks slowly through the dry grass to his
motorcycle. He does not mount it. He grips the handlebar with one
hand and begins to push it gently along the warm red dirt. The
descending road curves away through flame-of-the-forest trees in
late bloom; orange petals drift around him. The valley spreads
golden below. He pauses once at a bend, looks out over Mysore in the
distance, and the soft smile returns. He walks on, pushing the
bike, alone on the empty road. Last frame: Jaggi walking the
motorcycle slowly down the winding road into the golden valley, his
face wet with dried tears, calm and luminous and forever changed.
The image holds. End.
"""


def build_story_text() -> str:
    return (
        f"{STYLE}\n\n"
        f"Character: {JAGGI}\n\n"
        f"{STORY_BODY.strip()}\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://localhost:8002")
    parser.add_argument("--duration", type=float, default=180.0,
                        help="Total target duration in seconds (default 180 = 3 min)")
    parser.add_argument("--title", default="Jaggi — The Rock on Chamundi Hill")
    args = parser.parse_args()

    payload = {
        "title": args.title,
        "original_story_text": build_story_text(),
        "total_target_duration_seconds": args.duration,
        "pipeline_profile": "wan22_text_only",
    }
    try:
        r = requests.post(f"{args.api}/api/projects", json=payload, timeout=30)
        r.raise_for_status()
    except requests.RequestException as e:
        print(f"✗ failed to create project: {e}", file=sys.stderr)
        return 1

    data = r.json()
    print(f"✓ created project id={data['id']} status={data.get('status')}")
    print(f"  target_duration={args.duration}s → ~{int(args.duration // 5)} scenes "
          f"@ 5s/scene (Wan22 fixed)")
    print("  queue_scanner will pick it up FIFO once any active project finishes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
