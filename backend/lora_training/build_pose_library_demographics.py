"""Extend the pose library with demographic diversity.

Adds ~20 women's poses + ~10 kids' poses. The OpenPose skeletons we
extract from these will encode different proportions (hip width, leg
length, head-to-body ratio, gait) — letting the dual-CN pipeline drive
ANY character through movement that reads naturally for women and
children, not just adult men.

Each entry's keywords overlap with the existing male equivalents so
`pose_library.match()` can pick the most demographically-appropriate
skeleton when scene context implies it (e.g. "the young girl jumps" →
kid_jumping, "she walks toward the camera" → woman_walking).
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import settings as cfg
from app.providers.image.base import ImageSettings
from app.providers.image.sd35_provider import SD35ImageProvider

LIB_DIR = cfg.storage_root / "pose_library"
MANIFEST = LIB_DIR / "manifest.json"

# (label, keywords, t2i prompt). Same template as build_pose_library.py
# extension entries.
WOMEN_POSES = [
    ("woman_standing_neutral",
     ["she", "woman", "standing", "neutral", "still"],
     "Full-body, head to toe in frame, both feet visible. A generic woman in her 30s standing in a neutral upright pose, three-quarter front view, arms relaxed at sides, both feet flat on ground. Plain athletic wear. Plain neutral grey studio backdrop, soft even lighting, sharp focus, photorealistic."),
    ("woman_walking_side",
     ["she walks", "woman walking", "walks", "stroll"],
     "Full-body, head to toe in frame, both feet visible. A generic woman in her 30s mid-stride walking pose, side profile, one foot forward, arms swinging in opposition. Plain athletic wear. Plain neutral grey studio backdrop, soft even lighting, sharp focus, photorealistic."),
    ("woman_running_three_quarter",
     ["she runs", "woman running", "she sprints"],
     "Full-body, head to toe in frame, both feet visible. A generic woman in her 30s mid-stride running pose, three-quarter front view facing the camera, athletic gait, both feet briefly off ground. Plain athletic wear. Plain neutral grey studio backdrop, soft even lighting, sharp focus, photorealistic."),
    ("woman_jumping_vertical",
     ["she jumps", "woman jumping", "she leaps"],
     "Full-body, head to toe in frame, both feet visible. A generic woman in her 30s mid-air vertical jump, arms raised, knees slightly bent, side profile, feet off ground. Plain athletic wear. Plain neutral grey studio backdrop, soft even lighting, sharp focus, photorealistic."),
    ("woman_sitting_floor",
     ["she sits", "woman sitting", "seated woman"],
     "Full-body, head to toe in frame, both feet visible. A generic woman in her 30s sitting on the floor with legs extended forward, leaning back on both hands, three-quarter front view. Plain athletic wear. Plain neutral grey studio backdrop, soft even lighting, sharp focus, photorealistic."),
    ("woman_kneeling_one_knee",
     ["she kneels", "woman kneeling"],
     "Full-body, head to toe in frame, both feet visible. A generic woman in her 30s kneeling on one knee, the other knee bent up, both hands resting on the raised knee, three-quarter side view. Plain athletic wear. Plain neutral grey studio backdrop, soft even lighting, sharp focus, photorealistic."),
    ("woman_yoga_warrior",
     ["she yoga", "woman yoga", "yoga warrior", "warrior pose"],
     "Full-body, head to toe in frame, both feet visible. A generic woman in her 30s in a yoga warrior pose: front leg bent at 90 degrees, back leg straight extended behind, both arms stretched horizontally, side profile. Plain athletic wear. Plain neutral grey studio backdrop, soft even lighting, sharp focus, photorealistic."),
    ("woman_stretching_overhead",
     ["she stretches", "woman stretching", "stretches up"],
     "Full-body, head to toe in frame, both feet visible. A generic woman in her 30s standing upright, both arms stretched fully overhead, hands clasped, side profile. Plain athletic wear. Plain neutral grey studio backdrop, soft even lighting, sharp focus, photorealistic."),
    ("woman_dancing_pose",
     ["she dances", "woman dancing", "dancing"],
     "Full-body, head to toe in frame, both feet visible. A generic woman in her 30s in a dynamic dance pose, one arm raised up, one knee bent, body twisted in motion, three-quarter front view. Plain athletic wear. Plain neutral grey studio backdrop, soft even lighting, sharp focus, photorealistic."),
    ("woman_holding_phone",
     ["she phone", "woman phone", "she texts", "she scrolls"],
     "Full-body, head to toe in frame, both feet visible. A generic woman in her 30s standing upright, looking down at a smartphone held in both hands at chest level, three-quarter front view. Plain athletic wear. Plain neutral grey studio backdrop, soft even lighting, sharp focus, photorealistic."),
    ("woman_talking_camera",
     ["she speaks", "woman talking", "she explains", "she presents"],
     "Full-body, head to toe in frame, both feet visible. A generic woman in her 30s standing facing the camera, gesturing with one open hand at chest level as if explaining something, mouth slightly open mid-sentence, three-quarter front view. Plain athletic wear. Plain neutral grey studio backdrop, soft even lighting, sharp focus, photorealistic."),
    ("woman_laughing_open",
     ["she laughs", "woman laughing"],
     "Full-body, head to toe in frame, both feet visible. A generic woman in her 30s standing upright, head tilted back mid-laugh, mouth open, both hands relaxed at sides, three-quarter front view. Plain athletic wear. Plain neutral grey studio backdrop, soft even lighting, sharp focus, photorealistic."),
    ("woman_drinking_can",
     ["she drinks", "woman drinking", "she sips"],
     "Full-body, head to toe in frame, both feet visible. A generic woman in her 30s standing upright, holding a generic beverage can to her lips with the right hand, head tilted slightly back, side profile. Plain athletic wear. Plain neutral grey studio backdrop, soft even lighting, sharp focus, photorealistic."),
    ("woman_pointing_camera",
     ["she points", "woman pointing"],
     "Full-body, head to toe in frame, both feet visible. A generic woman in her 30s standing upright, pointing one extended index finger directly at the camera, slight forward lean, three-quarter front view. Plain athletic wear. Plain neutral grey studio backdrop, soft even lighting, sharp focus, photorealistic."),
    ("woman_waving_hello",
     ["she waves", "woman waving", "she greets"],
     "Full-body, head to toe in frame, both feet visible. A generic woman in her 30s standing upright, waving with the right hand raised at head height, smiling, three-quarter front view. Plain athletic wear. Plain neutral grey studio backdrop, soft even lighting, sharp focus, photorealistic."),
    ("woman_thinking_pose",
     ["she thinks", "woman thinking", "she ponders"],
     "Full-body, head to toe in frame, both feet visible. A generic woman in her 30s standing upright, head tilted down in thought, one hand at the chin, side profile. Plain athletic wear. Plain neutral grey studio backdrop, soft even lighting, sharp focus, photorealistic."),
    ("woman_carrying_bag",
     ["she carries", "woman carrying", "she shops"],
     "Full-body, head to toe in frame, both feet visible. A generic woman in her 30s walking forward, carrying a generic shopping bag in one hand, three-quarter front view, mid-stride. Plain athletic wear. Plain neutral grey studio backdrop, soft even lighting, sharp focus, photorealistic."),
    ("woman_lifting_box",
     ["she lifts", "woman lifting", "she carries box"],
     "Full-body, head to toe in frame, both feet visible. A generic woman in her 30s standing upright, lifting a generic box with both hands at chest level, three-quarter front view. Plain athletic wear. Plain neutral grey studio backdrop, soft even lighting, sharp focus, photorealistic."),
    ("woman_typing_laptop",
     ["she types", "woman typing", "she works", "she keyboards"],
     "Full-body, head to toe in frame, both feet visible. A generic woman in her 30s sitting on a high stool at a counter, typing on a generic laptop, eyes on the screen, three-quarter front view. Plain athletic wear. Plain neutral grey studio backdrop, soft even lighting, sharp focus, photorealistic."),
    ("woman_arms_crossed",
     ["she arms crossed", "woman arms crossed"],
     "Full-body, head to toe in frame, both feet visible. A generic woman in her 30s standing upright with arms crossed over the chest, three-quarter front view, both feet flat on ground. Plain athletic wear. Plain neutral grey studio backdrop, soft even lighting, sharp focus, photorealistic."),
]

KIDS_POSES = [
    ("kid_standing_neutral",
     ["child", "kid", "boy", "girl", "young child", "young boy", "young girl"],
     "Full-body, head to toe in frame, both feet visible. A generic child around 8 years old standing in a neutral upright pose, three-quarter front view, arms relaxed at sides, both feet flat on ground. Plain casual kids clothing (plain tee, plain shorts). Plain neutral grey studio backdrop, soft even lighting, sharp focus, photorealistic."),
    ("kid_running_side",
     ["kid running", "child running", "boy running", "girl running"],
     "Full-body, head to toe in frame, both feet visible. A generic child around 8 years old mid-stride running pose, side profile, both feet briefly off ground, arms pumping, big enthusiastic stride. Plain casual kids clothing. Plain neutral grey studio backdrop, soft even lighting, sharp focus, photorealistic."),
    ("kid_jumping_vertical",
     ["kid jumping", "child jumping", "kid leaps"],
     "Full-body, head to toe in frame, both feet visible. A generic child around 8 years old mid-air vertical jump, arms raised high above head, knees slightly bent, side profile, feet off ground. Plain casual kids clothing. Plain neutral grey studio backdrop, soft even lighting, sharp focus, photorealistic."),
    ("kid_sitting_floor",
     ["kid sitting", "child sitting"],
     "Full-body, head to toe in frame, both feet visible. A generic child around 8 years old sitting cross-legged on the floor, hands resting on knees, three-quarter front view. Plain casual kids clothing. Plain neutral grey studio backdrop, soft even lighting, sharp focus, photorealistic."),
    ("kid_playing_ball",
     ["kid plays", "child playing", "kicking ball", "kicks ball"],
     "Full-body, head to toe in frame, both feet visible. A generic child around 8 years old mid-action kicking a generic ball forward, one leg extended forward, side profile. Plain casual kids clothing. Plain neutral grey studio backdrop, soft even lighting, sharp focus, photorealistic."),
    ("kid_waving_hello",
     ["kid waves", "child waves", "child waving"],
     "Full-body, head to toe in frame, both feet visible. A generic child around 8 years old standing upright, waving with the right hand raised high above head, big smile, three-quarter front view. Plain casual kids clothing. Plain neutral grey studio backdrop, soft even lighting, sharp focus, photorealistic."),
    ("kid_climbing_pose",
     ["kid climbs", "child climbing", "climbing"],
     "Full-body, head to toe in frame, both feet visible. A generic child around 8 years old in a climbing pose, both arms reaching upward as if grabbing a ladder rung, one leg lifted, side profile. Plain casual kids clothing. Plain neutral grey studio backdrop, soft even lighting, sharp focus, photorealistic."),
    ("kid_holding_toy",
     ["kid holds toy", "child toy", "child plays toy"],
     "Full-body, head to toe in frame, both feet visible. A generic child around 8 years old standing upright, holding a generic small toy in both hands at chest level, looking down at the toy, three-quarter front view. Plain casual kids clothing. Plain neutral grey studio backdrop, soft even lighting, sharp focus, photorealistic."),
    ("kid_laughing_open",
     ["kid laughs", "child laughing"],
     "Full-body, head to toe in frame, both feet visible. A generic child around 8 years old standing upright, head tilted back mid-laugh, mouth open in big smile, both hands at sides, three-quarter front view. Plain casual kids clothing. Plain neutral grey studio backdrop, soft even lighting, sharp focus, photorealistic."),
    ("kid_drawing_floor",
     ["kid draws", "child drawing", "kid coloring"],
     "Full-body, head to toe in frame, both feet visible. A generic child around 8 years old sitting on the floor on knees, leaning forward, holding a crayon over a piece of paper on the floor, three-quarter side view. Plain casual kids clothing. Plain neutral grey studio backdrop, soft even lighting, sharp focus, photorealistic."),
]
NEG = (
    "cropped feet, cropped legs, head-and-shoulders, bust shot, close-up, "
    "macro, partial body, blurry, ugly, watermark, text, logo, deformed, "
    "extra limbs, multiple people, crowd"
)


def _existing_manifest() -> list[dict]:
    if not MANIFEST.exists():
        return []
    try:
        return json.loads(MANIFEST.read_text())
    except Exception:
        return []


def _write_manifest(rows: list[dict]) -> int:
    MANIFEST.write_text(json.dumps(rows, indent=2))
    return len(rows)


async def _render(provider: SD35ImageProvider, label: str, prompt: str) -> Path | None:
    out = LIB_DIR / f"{label}.png"
    if out.exists():
        return out
    print(f"[t2i pose-lib] {label}")
    seed = 1100 + sum(ord(c) for c in label) % 999
    res = await provider.generate_image(
        prompt, NEG, out,
        settings=ImageSettings(
            width=cfg.sd35_char_width, height=cfg.sd35_char_height,
            num_inference_steps=cfg.sd35_steps,
            guidance_scale=cfg.sd35_guidance, seed=seed,
        ),
    )
    if not res.success:
        print(f"  FAIL: {res.error}")
        return None
    return out


async def main() -> None:
    LIB_DIR.mkdir(parents=True, exist_ok=True)
    rows = _existing_manifest()
    existing_labels = {r["label"] for r in rows}
    print(f"Existing manifest: {len(rows)} entries")

    sd = SD35ImageProvider()
    n_added = 0
    for label, kw, prompt in WOMEN_POSES + KIDS_POSES:
        if label in existing_labels:
            continue
        out = await _render(sd, label, prompt)
        if out is None:
            continue
        rows.append({"label": label, "photo": out.name, "keywords": kw})
        n_added += 1

    n = _write_manifest(rows)
    print(f"Added {n_added} entries; manifest now {n} total → {MANIFEST}")


if __name__ == "__main__":
    asyncio.run(main())
