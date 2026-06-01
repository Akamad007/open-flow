#!/usr/bin/env python
"""Seed a 10-minute Ghibli-style mini-series episode on Buddha's enlightenment.

One project, one Episode 0, target 600s. The scene planner targets ~5s per
scene → ~120 scenes. The narrative below is structured as 30 location-arcs of
~4 beats each so backgrounds change roughly every 4 scenes while continuity
inside each arc reads as a single moment.

Usage:
    python seed_buddha_enlightenment.py
    python seed_buddha_enlightenment.py --api http://localhost:8002
"""

from __future__ import annotations

import argparse
import sys

import requests


STYLE = (
    "Studio Ghibli inspired semi-realistic anime, hand-painted watercolor "
    "backgrounds, lush detailed nature, soft cinematic painterly lighting, "
    "delicate line work, expressive lotus-shaped eyes, warm earth-toned "
    "palette of saffron, ochre, deep green and twilight gold, supremely "
    "beautiful composition. All motion slow, deliberate, breath-paced and "
    "contemplative — no fast cuts, no jittery motion, no quick action, no "
    "live action, no photorealism, no 3D-render look, no harsh outlines, "
    "no mirrors, no glass reflections."
)

SIDDHARTHA = (
    "Siddhartha Gautama is a tall slender Indian man in his mid-thirties "
    "with warm golden-brown skin, long dark wavy hair loosely tied back, "
    "calm dark almond eyes, soft brow, gentle expression, thin frame from "
    "long austerity. He wears a single plain ochre-saffron monk's robe "
    "wrapped over the left shoulder, bare feet, no jewelry. A faint inner "
    "warmth lights his face from within."
)

SUJATA = (
    "Sujata is a young Indian village girl with warm brown skin, a long "
    "single black braid, large kind dark eyes, wearing a simple cream "
    "cotton sari with a faded red border, holding a small round clay bowl "
    "of golden milk-rice."
)

SOTTHIYA = (
    "Sotthiya is a thin elderly Indian grass-cutter with weathered brown "
    "skin, a short white beard, simple grey wrapped dhoti, carrying tall "
    "bundles of long green kusha grass on his shoulder."
)

MARA = (
    "Mara is a tall shadowy figure with deep indigo skin, slow-glowing "
    "red eyes, long black flowing robes that drift like smoke, a thin "
    "black crown of thorns. He is the lord of craving and death."
)

MUCALINDA = (
    "Mucalinda the naga king is a great serpent with iridescent green-"
    "blue scales, a seven-headed golden hooded cobra crown, calm "
    "benevolent dark eyes, ancient and protective."
)

BRAHMA = (
    "Brahma Sahampati is a luminous four-faced celestial figure in flowing "
    "white and gold silks, calm faces in four directions, palms joined "
    "before his chest, descending in soft golden light."
)


STORY_BODY = """
Setting: ancient northern India around the sixth century BCE — the marble
palace of Kapilavastu, dark forest roads, the ascetic groves of Magadha, the
banks of the Nairanjana river, the great pipal tree at Uruvela (Bodh Gaya),
and the Deer Park at Isipatana near Sarnath. Every location is painted in
Ghibli watercolor with hand-painted skies and detailed flora.

The episode follows Siddhartha Gautama's six-year search for awakening,
the night under the Bodhi tree, the seven weeks after, and the first sermon
at Sarnath. The pacing is slow, reverent, breath-paced.

ARC 1 — Palace doubt (palace garden, dawn). Prince Siddhartha walks alone
through the marble palace garden of Kapilavastu, lotus ponds and jasmine
vines around him. He pauses at a balcony rail, holding a single white
blossom. He gazes toward distant forests and village huts with restless,
searching eyes. The white blossom slips from his fingers and drifts down.

ARC 2 — The sleeping family (palace bedroom, deep night). Inside the lamp-
lit bedchamber, Siddhartha stands at the doorway of a curtained bed where
his wife Yashodhara sleeps with their infant son Rahula. He steps closer.
He raises a trembling hand to touch the child's cheek, lowers it without
touching, presses his forehead briefly against the wooden bedpost, and turns
silently back to the door.

ARC 3 — The midnight ride (palace stable and gates, deep night). Siddhartha
pulls a plain dark cloak over his silk robe in the moonlit stable. He
tightens the saddle of the white horse Kanthaka. He mounts in one slow
motion. The palace gates swing open without a sound as if by unseen hands.
Horse and rider pass under the great arched gateway and glance back once at
the receding torches.

ARC 4 — The dark forest road (forest at night). Horse and rider move down a
winding forest path under tall sal trees. Fireflies drift between trunks.
An owl turns its head silently on a branch. Mist curls along the ground.
Siddhartha's face is set but calm in the moonlight.

ARC 5 — Dawn at the river (Anoma riverbank, first light). They reach a wide
silver river at first light. Siddhartha dismounts and kneels at the water,
splashes his face. The horse breathes white mist into the cool air. He
unsheathes a short sword and with one slow stroke cuts the long knot of his
bound hair. The dark coil falls into the grass.

ARC 6 — Trading the silk (riverbank clearing, morning). A passing forest
hunter in coarse ochre cloth pauses, surprised. Siddhartha gestures to his
princely silk; they exchange clothes in silence. Siddhartha stands now in
plain ochre. He strokes Kanthaka's nose, removes the bridle, lays his hand
on the horse's forehead, and turns him gently toward the road home.

ARC 7 — Alara Kalama's grove (mango grove ashram, midday). A grove of
mango trees with seated meditators in white. The old white-bearded teacher
Alara Kalama sits at the center. Siddhartha approaches barefoot, bows low,
asks for instruction. He sits in lotus. Light fades; oil lamps glow around
him.

ARC 8 — Mastery and emptiness (Alara's grove, evening to dawn). Siddhartha
attains the formless absorption of nothingness. He opens his eyes with
quiet, unsatisfied calm. At dawn he bows to Alara one last time and walks
out of the grove; the teacher watches him go with a small sad smile.

ARC 9 — Uddaka Ramaputta (banyan grove hermitage, afternoon to dusk). A
second forest hermitage under enormous banyan trees. The sharper-eyed
teacher Uddaka instructs. Siddhartha meditates deeper still and goes even
further. He surfaces — calm, but the great question is not answered. He
stands, bows, and steps back onto the road.

ARC 10 — Joining the five ascetics (Uruvela forest cave, day). Five gaunt
ascetics in white loincloths sit in a circle by a rocky cave mouth. They
recognise Siddhartha's resolve as he approaches and welcome him. He sits
down with them. They begin to fast and meditate together.

ARC 11 — Extreme austerity (Uruvela forest, full daylight). A close shot:
Siddhartha holds a single grain of rice on the tip of his finger and places
it on his tongue, cheeks hollow. He sits motionless in the sun, veins on
his temple, holding his breath until the world goes silent. His ribs become
visible; his frame shockingly thin.

ARC 12 — Near collapse (Uruvela forest path, evening). Siddhartha tries to
rise from his meditation seat and stumbles to one knee. The world tilts. He
kneels with his forehead bowed against the bare earth, breathing slowly.

ARC 13 — Memory of the rose-apple tree (childhood ploughing field, golden
afternoon — flashback in soft warm tones). A small boy in white sits cross-
legged under a rose-apple tree at the edge of a freshly ploughed field. Two
white bullocks pull a wooden plough in the distance. The boy's eyes are
half-closed; sunlight dapples his face; he is calm, joyful, free of craving.

ARC 14 — Returning to himself (Uruvela forest, present, evening). Adult
Siddhartha opens his eyes. He sees the memory clearly. He understands —
self-torture is not the way. He looks at his thin hands as if for the first
time. He rises slowly.

ARC 15 — Sujata's tree (sacred banyan clearing, golden morning). The young
village girl Sujata kneels in front of a great banyan tree, hands folded,
eyes closed. A small clay bowl of golden milk-rice sits beside her on a
fresh green leaf. She has come to thank the tree-spirit for her child.

ARC 16 — The offering (banyan clearing, morning). Sujata turns and sees
Siddhartha seated motionless beneath the tree's vast roots — so gaunt and
still that she takes him for the spirit himself. She lifts the bowl in
both hands, kneels at a respectful distance, and slides it toward him.
He inclines his head in thanks and lifts a small portion of the warm rice
to his lips. Warm color returns to his face.

ARC 17 — The five walk away (forest path edge, afternoon). The five
ascetics, watching from a distance, shake their heads in disgust. One by
one they turn and walk away into the trees. Siddhartha watches them go
without anger and without regret.

ARC 18 — Bathing in the Nairanjana (river, golden hour). Siddhartha walks
down to the wide gentle river. He bathes slowly in the clear water. Light
glitters on the surface and on his shoulders. He emerges clean. His
silhouette is steady against the sunset.

ARC 19 — Sotthiya the grass-cutter (forest road, late afternoon). On the
path he meets the elderly grass-cutter Sotthiya carrying bundles of long
green kusha grass on his shoulder. They bow to one another. Sotthiya smiles
and gives him eight handfuls. Siddhartha continues toward a great lone
pipal tree visible in a distant clearing.

ARC 20 — Spreading the grass and the vow (under the Bodhi tree, evening).
He reaches the eastern side of the great pipal tree. He spreads the kusha
grass carefully into a soft seat, runs his hand once over the rough bark in
gratitude, and sits cross-legged on the grass. Hands rest one over the
other, palms up. His lips move silently in the great vow: he will not rise
until awakening is won. The sky behind him deepens from gold to rose to
violet.

ARC 21 — Mara's armies (clearing under the tree, night). The clearing
darkens unnaturally. The tall shadowy figure Mara, lord of craving and
death, steps from the trees with red eyes. Behind him a vast silhouetted
horde of demons and beasts fills the forest. They hurl a great wave of
spears, arrows and fire toward the seated figure.

ARC 22 — Weapons become flowers (clearing under the tree, night). As each
weapon arcs through the air above Siddhartha it softens, blossoms and
becomes a slow-falling shower of petals — lotus pink, jasmine white,
marigold gold — settling around him like rain. He has not moved.

ARC 23 — Mara's three daughters (clearing under the tree, deep night).
Three beautiful figures in silk — Mara's daughters Tanha, Arati and Raga —
step from the dark and dance slowly around the seated figure, ribbons
trailing in the still air, smiling at him. He sits unmoved, eyes closed.
Their smiles falter; they thin like smoke and disappear.

ARC 24 — The earth-touching gesture (close on Siddhartha under the tree,
night). Mara himself steps closer and demands by what right this man claims
the seat of awakening. The seated figure brings his right hand slowly from
his lap and lowers it; his fingertips touch the bare earth. A deep low hum.
A soft golden glow spreads outward. The earth itself rises in the form of a
tall figure of warm light, palms together, and bows in witness. Mara's
red eyes widen — he steps back and dissolves into the night.

ARC 25 — First watch, past lives (visionary space around the Bodhi tree,
late night). A faint silver light gathers around Siddhartha's head.
Translucent images unspool in the air around him — many faces, many
bodies, many lives lived. The images flow like silk ribbons spiralling
outward into an infinite chain back through the ages, and then settle back
into him.

ARC 26 — Middle watch, the divine eye (visionary space, deep night). A
second silver light gathers. The world around the tree becomes transparent.
Countless beings appear across forests, cities, oceans and skies — born,
suffering, dying, being reborn — the glowing threads of karma woven between
them. His expression softens with deep compassion; a single tear traces
his cheek.

ARC 27 — Last watch, the Four Noble Truths (under the tree, near dawn). A
third silver light gathers. Soft glowing script forms in the air around him
in sequence — dukkha, samudaya, nirodha, magga — each word floating and
dissolving into him. The final word resolves into a soft eight-spoked
golden wheel of light hovering before him. The wheel rotates slowly, once.

ARC 28 — Dawn, the morning star (eastern horizon over the clearing, just
before sunrise). Beyond the trees, low in the eastern sky, a single bright
morning star rises clear of the horizon. Close on Siddhartha — his eyelids
lift slowly. Behind his dark eyes is something vast and still. The faintest
smile touches his lips. The first rays of the sun fall on the pipal leaves
and on his shoulders. He is the Buddha — Awakened.

ARC 29 — Week one, bliss under the tree (Bodhi tree clearing, daylight).
The Buddha sits still under the pipal tree. Soft light radiates from him.
A small pond near the tree fills with newly opened pink, white and blue
lotuses. A deer steps quietly into the clearing and lies down to one side.
A small green parakeet alights on a branch above. All quiet, all listening.

ARC 30 — Week two, the unblinking gaze (animisalocana spot beside the tree,
day to night). The Buddha rises slowly, walks a few paces from the tree,
turns, and stands facing the tree with hands folded in gratitude. The sun
climbs and lowers; he does not blink. Moonlight finds him still standing,
his face full of quiet love for the tree that sheltered him.

ARC 31 — Week three, the jewelled walkway (between the seat and the
standing place, day). A glowing path of soft jewel-light appears in the air
between the two spots. The Buddha walks slowly back and forth along it,
each step measured, hands clasped lightly. The walkway glimmers under his
feet. The light fades into dusk.

ARC 32 — Week four, the jewel house and rays of color (small luminous
chamber beside the tree, day to night). A small house of soft light
appears beside the tree. The Buddha sits within it. Six gentle rays of
color — blue, yellow, red, white, orange, and a shimmering mixture — spread
slowly outward from his body and fold back in, pulsing like a slow
heartbeat.

ARC 33 — Week five, Brahma's plea (ajapala banyan tree, evening). The
Buddha sits beneath a great banyan tree at the forest's edge. A small frown
of doubt touches his brow — is this insight too subtle for ordinary minds?
From the sky above, the luminous four-faced Brahma Sahampati descends in
soft golden light and kneels before him, palms joined, asking him to teach
for the sake of beings with little dust in their eyes. The Buddha inclines
his head — yes.

ARC 34 — Week six, the storm and the naga king (Mucalinda pool, day). The
Buddha sits beside a small forest pool. Heavy black clouds roll in. Cold
rain begins. From the pool rises the great serpent king Mucalinda — green-
blue iridescent scales, seven golden cobra heads. He coils his vast body
around the seated Buddha and lifts his sevenfold hood high overhead like a
golden canopy. Rain runs harmlessly off the scales; the Buddha sits dry
and serene.

ARC 35 — Storm ends, naga bows (Mucalinda pool, evening). The rain softens
and stops. Light returns to the pool's surface. The naga lowers his hood,
his body shrinks, and he becomes a slender young man in green silk who
bows once and slips back into the water. The Buddha rises and walks on.

ARC 36 — Week seven, the merchants Tapussa and Bhallika (rajayatana tree
clearing, midday). The Buddha sits beneath a slender white-flowered tree.
Down the path come two travelling merchants leading a small ox-cart of
trade goods. They are tired. They see him, sense something rare, unwrap
small honey rice-cakes from a cloth, kneel and offer them with both hands.

ARC 37 — The first lay disciples (rajayatana clearing, afternoon). The
Buddha accepts the cakes in cupped hands and eats slowly in silence. The
merchants take refuge in him and in the truth he has found. He places his
hand briefly on each of their heads in blessing. They rise, bow once more
and continue their journey, transformed.

ARC 38 — The road north toward Sarnath (open forest road, sunrise). The
Buddha begins to walk. Dusty road bordered by long grass. Ochre robe
glowing in the morning light. He passes a sleeping village where a child
in a doorway looks up at him with wide eyes; he smiles faintly and walks
on. The road winds through tall trees; sun-dapples move across his robe.

ARC 39 — The Deer Park at Isipatana (Sarnath deer park, evening). He
crosses a wide green plain and reaches the edge of the deer park. Spotted
deer graze in soft golden light. He walks softly between them; they lift
their heads but do not flee. He approaches a small clearing where his five
former companions sit together.

ARC 40 — The first sermon and the wheel of dharma (deer park clearing,
twilight to night). The five companions agree among themselves not to greet
him, but as he comes close something in his bearing makes them rise, one
by one, almost without choosing. They take his bowl, spread a mat, sit
before him in a half-circle. He raises his right hand in the teaching mudra
and speaks softly of the middle way and the four noble truths. As he
speaks, a luminous eight-spoked wheel of golden light forms in the air
above his right hand and rotates slowly once. The eldest, Kondanna,
breathes in sharply — his eyes brim with sudden understanding and he bows
his forehead to the earth. The Buddha touches his head gently in blessing.
Stars appear over the park. The luminous wheel of dharma expands slowly
outward into the night — a soft promise reaching into the world. End frame.
"""


def build_story_text() -> str:
    return (
        f"{STYLE}\n\n"
        f"Character: {SIDDHARTHA}\n\n"
        f"Character: {SUJATA}\n\n"
        f"Character: {SOTTHIYA}\n\n"
        f"Character: {MARA}\n\n"
        f"Character: {MUCALINDA}\n\n"
        f"Character: {BRAHMA}\n\n"
        f"{STORY_BODY.strip()}\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://localhost:8002")
    parser.add_argument("--duration", type=float, default=600.0,
                        help="Total target duration in seconds (default 600 = 10 min)")
    parser.add_argument("--title", default="Buddha — Path to Awakening")
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
