"""Build/extend the pose library.

Two modes:
  1. SEED from existing dataset pose refs (already generated for LoRA
     training). Takes the 20 photos in `_pose_refs/`, copies them to
     `storage/pose_library/`, and writes the manifest with sensible
     keywords.
  2. EXTEND with new categories — for each (label, prompt, keywords)
     not yet in the library, render a generic-person photo via SD3.5 and
     append to the manifest.

This script is run once to bootstrap, then any time you want to add new
pose categories.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import settings as cfg
from app.providers.image.base import ImageSettings
from app.providers.image.sd35_provider import SD35ImageProvider

LIB_DIR = cfg.storage_root / "pose_library"
MANIFEST = LIB_DIR / "manifest.json"

SEED_FROM = ROOT / "lora_training" / "_train_hold" / "_pose_refs"  # safe default
SEED_FALLBACK = ROOT / "lora_training" / "dataset_runner_man" / "_pose_refs"


# (label, keywords, prompt-or-None-if-already-have-photo)
# When prompt is None we expect the photo to already exist (seed mode).
ENTRIES: list[tuple[str, list[str], str | None]] = [
    # Seeded from the 20 dual-CN training poses
    ("standing_neutral", ["standing", "neutral", "upright", "pose", "still", "wait", "wait", "idle"], None),
    ("walking_side", ["walking", "stroll", "step", "march"], None),
    ("running_side", ["running", "run", "sprint", "jog", "side"], None),
    ("running_three_quarter", ["running", "run", "jog", "sprint", "facing camera", "three-quarter"], None),
    ("jumping_vertical", ["jump", "jumping", "leap", "vertical"], None),
    ("jumping_forward", ["leap", "jump", "forward", "hurdle"], None),
    ("sitting_bench", ["sitting", "sit", "seated", "bench", "stoop", "rest"], None),
    ("sitting_lacing", ["lace", "tying", "shoelace", "tie", "shoes"], None),
    ("kneeling_one_knee", ["kneel", "kneeling", "one knee", "propose"], None),
    ("crouching_low", ["crouch", "crouching", "low", "duck"], None),
    ("stretching_forward", ["stretch", "stretching", "bend forward", "forward fold", "toe touch"], None),
    ("stretching_overhead", ["stretch", "overhead", "reach up", "arms up"], None),
    ("squat_low", ["squat", "deep squat", "knee bend"], None),
    ("lunge_forward", ["lunge", "lunging"], None),
    ("plank_floor", ["plank", "press up", "push up", "push-up"], None),
    ("standing_arms_crossed", ["arms crossed", "crossed arms", "stern"], None),
    ("standing_hands_on_hips", ["hands on hips", "akimbo", "confident"], None),
    ("looking_up", ["look up", "looking up", "gaze up", "sky"], None),
    ("walking_back_to_camera", ["walk away", "walking away", "leaving", "departure"], None),
    ("standing_profile_side", ["profile", "side", "standing"], None),

    # Extension — common ad/lifestyle poses
    ("talking_camera",
     ["speak", "talk", "say", "tell", "address", "explain", "narrate", "presenting"],
     "Full-body, head to toe in frame, both feet visible. A generic athletic "
     "person standing facing the camera, gesturing with one open hand at "
     "chest level as if explaining something, mouth slightly open mid-sentence, "
     "three-quarter front view. Athletic build, plain athletic wear, plain "
     "neutral grey studio backdrop, soft even lighting, sharp focus, "
     "photorealistic."),
    ("holding_object_up",
     ["hold up", "holding up", "show", "display", "present", "raise"],
     "Full-body, head to toe in frame, both feet visible. A generic athletic "
     "person standing upright, holding a small object in their right hand "
     "raised to shoulder height, eyes on the object, three-quarter front "
     "view. Athletic build, plain athletic wear, plain neutral grey studio "
     "backdrop, soft even lighting, sharp focus, photorealistic."),
    ("holding_phone",
     ["phone", "smartphone", "mobile", "scroll", "text"],
     "Full-body, head to toe in frame, both feet visible. A generic athletic "
     "person standing upright, looking down at a smartphone held in both "
     "hands at chest level, three-quarter front view. Athletic build, plain "
     "athletic wear, plain neutral grey studio backdrop, soft even lighting, "
     "sharp focus, photorealistic."),
    ("drinking_can",
     ["drink", "drinking", "sip", "sipping", "cola", "beverage", "soda"],
     "Full-body, head to toe in frame, both feet visible. A generic athletic "
     "person standing upright, holding a generic beverage can to their "
     "lips with the right hand, head tilted slightly back, side profile. "
     "Athletic build, plain athletic wear, plain neutral grey studio "
     "backdrop, soft even lighting, sharp focus, photorealistic."),
    ("laughing_open",
     ["laugh", "laughing", "joy", "laughing", "happy"],
     "Full-body, head to toe in frame, both feet visible. A generic athletic "
     "person standing upright, head tilted back mid-laugh, mouth open, both "
     "hands relaxed at the sides, three-quarter front view. Athletic build, "
     "plain athletic wear, plain neutral grey studio backdrop, soft even "
     "lighting, sharp focus, photorealistic."),
    ("leaning_wall",
     ["lean", "leaning", "wall", "rest"],
     "Full-body, head to toe in frame, both feet visible. A generic athletic "
     "person standing leaning back against a plain wall, weight on one leg, "
     "the other foot crossed in front, arms folded loosely, three-quarter "
     "front view. Athletic build, plain athletic wear, plain neutral grey "
     "studio backdrop, soft even lighting, sharp focus, photorealistic."),
    ("sitting_cross_legged",
     ["meditate", "meditation", "yoga", "lotus", "cross-legged", "seated cross-legged", "sitting on the floor"],
     "Full-body, head to toe in frame, both feet visible. A generic athletic "
     "person sitting cross-legged on the floor, hands resting on knees, "
     "spine upright, three-quarter front view. Athletic build, plain "
     "athletic wear, plain neutral grey studio backdrop, soft even "
     "lighting, sharp focus, photorealistic."),
    ("yoga_warrior",
     ["warrior", "yoga", "warrior pose", "asana"],
     "Full-body, head to toe in frame, both feet visible. A generic athletic "
     "person in a yoga warrior pose: front leg bent at 90 degrees, back leg "
     "straight extended behind, both arms stretched horizontally, side "
     "profile. Athletic build, plain athletic wear, plain neutral grey "
     "studio backdrop, soft even lighting, sharp focus, photorealistic."),
    ("typing_laptop",
     ["type", "typing", "laptop", "keyboard", "work", "office"],
     "Full-body, head to toe in frame, both feet visible. A generic athletic "
     "person sitting on a high stool at a counter, typing on a generic "
     "laptop, eyes on the screen, three-quarter front view. Athletic build, "
     "plain athletic wear, plain neutral grey studio backdrop, soft even "
     "lighting, sharp focus, photorealistic."),
    ("pointing_camera",
     ["point", "pointing", "you", "direct address"],
     "Full-body, head to toe in frame, both feet visible. A generic athletic "
     "person standing upright, pointing one extended index finger directly "
     "at the camera, slight forward lean, three-quarter front view. "
     "Athletic build, plain athletic wear, plain neutral grey studio "
     "backdrop, soft even lighting, sharp focus, photorealistic."),
    ("waving_hello",
     ["wave", "waving", "hello", "hi", "greet"],
     "Full-body, head to toe in frame, both feet visible. A generic athletic "
     "person standing upright, waving with the right hand raised at head "
     "height, smiling, three-quarter front view. Athletic build, plain "
     "athletic wear, plain neutral grey studio backdrop, soft even "
     "lighting, sharp focus, photorealistic."),
    ("opening_jar",
     ["open", "opening", "twist", "unscrew"],
     "Full-body, head to toe in frame, both feet visible. A generic athletic "
     "person standing upright, holding a generic jar in both hands at chest "
     "level, twisting the lid off, eyes on the jar, three-quarter front "
     "view. Athletic build, plain athletic wear, plain neutral grey studio "
     "backdrop, soft even lighting, sharp focus, photorealistic."),
]
NEG = (
    "cropped feet, cropped legs, head-and-shoulders, bust shot, close-up, "
    "macro, partial body, blurry, ugly, watermark, text, logo, deformed, "
    "extra limbs, multiple people, crowd"
)


def _seed_from(src: Path) -> int:
    """Copy already-generated pose photos into the library."""
    n = 0
    for label, _kw, prompt in ENTRIES:
        if prompt is not None:
            continue  # extension entry, not a seed
        src_path = src / f"{label}.png"
        dst_path = LIB_DIR / f"{label}.png"
        if not src_path.exists():
            continue
        if dst_path.exists():
            n += 1
            continue
        shutil.copy2(src_path, dst_path)
        n += 1
    return n


async def _extend(provider: SD35ImageProvider) -> int:
    """Render any extension entries that don't yet have a photo."""
    n = 0
    for label, _kw, prompt in ENTRIES:
        if prompt is None:
            continue
        dst = LIB_DIR / f"{label}.png"
        if dst.exists():
            continue
        seed = 800 + sum(ord(c) for c in label) % 999
        print(f"[t2i pose-lib] {label}")
        res = await provider.generate_image(
            prompt, NEG, dst,
            settings=ImageSettings(
                width=cfg.sd35_char_width, height=cfg.sd35_char_height,
                num_inference_steps=cfg.sd35_steps,
                guidance_scale=cfg.sd35_guidance, seed=seed,
            ),
        )
        if not res.success:
            print(f"  FAIL: {res.error}")
            continue
        n += 1
    return n


def _write_manifest() -> int:
    """Write/refresh the manifest based on which photos are on disk."""
    rows = []
    for label, kw, _prompt in ENTRIES:
        photo = LIB_DIR / f"{label}.png"
        if not photo.exists():
            continue
        rows.append({"label": label, "photo": photo.name, "keywords": kw})
    MANIFEST.write_text(json.dumps(rows, indent=2))
    return len(rows)


async def main() -> None:
    LIB_DIR.mkdir(parents=True, exist_ok=True)
    src = SEED_FROM if SEED_FROM.exists() else SEED_FALLBACK
    seeded = _seed_from(src)
    print(f"Seeded from {src}: {seeded} photo(s)")

    provider = SD35ImageProvider()
    extended = await _extend(provider)
    print(f"Extended via SD3.5: {extended} new photo(s)")

    n = _write_manifest()
    print(f"Manifest: {n} entries → {MANIFEST}")


if __name__ == "__main__":
    asyncio.run(main())
