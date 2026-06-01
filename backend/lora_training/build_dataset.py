"""Generate a 20-image LoRA training dataset of the same character.

Pipeline:
  1. For each of 20 distinct pose prompts:
       a. SD3.5 t2i renders a generic-person pose reference (full-body)
       b. InstantID + OpenPose dual-CN renders the SAME character in
          that pose (face from portrait, body from pose ref)
       c. Save both the synthetic character image AND a caption .txt
          (DreamBooth needs <name>.png + <name>.txt pairs)

The output directory becomes the `--instance_data_dir` for
`train_dreambooth_lora_sdxl.py`. The unique token "ohwx man" is
injected into every caption so the LoRA learns to associate that token
with the trained identity at inference time.
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import settings as cfg
from app.providers.image.base import ImageSettings
from app.providers.image.sd35_provider import SD35ImageProvider

GPU_PYTHON = sys.executable  # whichever python this script runs under
INSTANTID_POSE = Path.home() / "instantid" / "generate_instantid_pose.py"

DATASET_DIR = Path(__file__).parent / "dataset_runner_man"
PORTRAIT = ROOT / "storage" / "smoke_img2img" / "01_character.png"

INSTANCE_TOKEN = "ohwx man"

# Real-photo overrides: poses where SD3.5 t2i couldn't reliably synthesise
# the canonical body geometry, so we substitute a real photo whose
# OpenPose skeleton drives the dual-CN render. Identity still comes from
# PORTRAIT — the override only contributes the body pose.
REAL_POSE_REFS: dict[str, Path] = {
    "sitting_lacing": Path.home() / "lacing_ref.png",
}

# Per-label dual-CN strength overrides for poses where the default
# (id=0.80, pose=0.65) loses to InstantID's identity pull and collapses
# back toward a standing portrait. Keys → (id_strength, pose_strength).
STRENGTH_OVERRIDES: dict[str, tuple[float, float]] = {
    "sitting_lacing": (0.40, 1.10),
}


# 20 distinct pose prompts that span the action vocabulary an ad would
# need: standing, walking, running, jumping, sitting, kneeling,
# stretching, etc. Each is rendered as a generic-person SD3.5 t2i pose
# ref → InstantID dual-CN → SAME character in that pose.
POSES = [
    ("standing_neutral", "standing in a neutral upright pose, three-quarter front view, arms relaxed at sides, both feet flat on the ground"),
    ("walking_side", "mid-stride walking pose, side profile, one foot forward, arms swinging in opposition"),
    ("running_side", "mid-stride running pose, side profile, both feet briefly off ground, arms pumping"),
    ("running_three_quarter", "mid-stride running pose, three-quarter front view facing the camera, athletic gait"),
    ("jumping_vertical", "mid-air vertical jump, arms raised, knees slightly bent, side profile, feet off ground"),
    ("jumping_forward", "mid-air forward jump, body extended, arms forward for balance, side profile"),
    ("sitting_bench", "sitting on a low concrete bench with buttocks on the bench, knees bent at right angle, both feet flat on ground, hands resting on knees, side profile"),
    ("sitting_lacing", "down on one knee in an athletic crouch tying shoelaces — the left knee resting flat on the ground, the right foot planted flat on the ground in front with the right knee bent at 90 degrees, body leaning forward over the right knee, BOTH HANDS at the laces of the right trainer (left hand pulling the left lace end, right hand pulling the right lace end into a bow), eyes looking down at the shoe, side profile from the right, full body head to toe in frame, both feet visible"),
    ("kneeling_one_knee", "kneeling on one knee, the other knee bent up, both hands resting on the raised knee, three-quarter side view"),
    ("crouching_low", "crouching low with both knees deeply bent, hands pressing on the ground for balance, side profile"),
    ("stretching_forward", "standing with legs apart, bending forward at the waist, both hands reaching toward the toes, side profile"),
    ("stretching_overhead", "standing upright, both arms stretched fully overhead, hands clasped, side profile"),
    ("squat_low", "deep squat with knees bent past 90 degrees, hips below knees, arms forward for balance, side profile"),
    ("lunge_forward", "forward lunge pose, one leg extended forward bent at the knee, the back leg straight, arms at sides, side profile"),
    ("plank_floor", "high plank pose, body horizontal, weight on hands and toes, looking forward, side profile"),
    ("standing_arms_crossed", "standing upright with arms crossed over the chest, three-quarter front view, both feet flat on ground"),
    ("standing_hands_on_hips", "standing upright with hands on hips, three-quarter front view, both feet flat on ground"),
    ("looking_up", "standing upright, head tilted back to look up at the sky, arms at sides, three-quarter front view"),
    ("walking_back_to_camera", "walking away from the camera, full body from behind, mid-stride, arms swinging"),
    ("standing_profile_side", "standing upright in a perfectly side profile, both feet visible, arms hanging at side"),

    # v2 additions — camera-angle variety + ad-context actions
    ("standing_facing_camera", "standing upright facing the camera directly, full frontal view, arms relaxed at sides, both feet flat on ground"),
    ("standing_three_quarter_back", "standing upright, three-quarter view from behind, head turned slightly toward the camera, arms relaxed at sides"),
    ("walking_three_quarter", "mid-stride walking pose, three-quarter front view, one foot forward, arms swinging naturally"),
    ("running_back_to_camera", "running away from the camera, full body from behind, mid-stride, both feet briefly off ground"),
    ("presenting_to_camera", "standing facing the camera, one arm extended forward presenting an open palm, the other hand at the side, three-quarter front view"),
    ("gesturing_explaining", "standing facing the camera, both hands open at chest height as if explaining something mid-sentence, three-quarter front view"),
    ("looking_surprised", "standing upright, eyes wide and mouth slightly open in a surprised expression, hands raised at chest height, three-quarter front view"),
    ("looking_confident", "standing upright with chin slightly raised, confident expression, one hand at hip the other at side, three-quarter front view"),
    ("smiling_at_camera", "standing upright, broad genuine smile at the camera, hands relaxed at sides, three-quarter front view"),
    ("looking_down_thinking", "standing upright, head tilted down in thought, one hand at the chin, side profile"),
    ("throwing_overhand", "mid-throw overhand pitching motion, arm cocked back, body twisted, opposite leg forward, side profile"),
    ("catching_high", "stretching upward with both hands high overhead reaching to catch an object, on tiptoes, three-quarter front view"),
    ("lifting_overhead", "standing upright, arms extended overhead lifting a generic weight or object, side profile"),
    ("pushing_forward", "standing leaning forward, both hands extended pushing against an invisible surface, side profile"),
    ("pulling_back", "standing leaning back, both hands pulling toward the chest as if pulling a rope, side profile"),
    ("kicking_forward", "mid-action forward kick, one leg extended forward, the other planted, arms balanced for stability, side profile"),
    ("dancing_pose", "dynamic dance pose, one arm raised up, one knee bent, body twisted in motion, three-quarter front view"),
    ("bowing_slight", "standing upright in a slight forward bow with hands together at chest, three-quarter front view"),
    ("turning_pivot", "mid-pivot turn, one foot anchored, body twisting, arms swinging across chest, three-quarter view"),
    ("sitting_floor_relaxed", "sitting on the floor with legs extended forward and slightly apart, leaning back on both hands behind, three-quarter front view"),
]
POSE_PROMPT_TEMPLATE = (
    "Full-body, head to toe in frame, both feet visible. A generic athletic "
    "person {pose}. Athletic build, plain athletic wear (plain tee, plain "
    "shorts, plain trainers, generic colors). Plain neutral grey studio "
    "backdrop, soft even lighting, sharp focus, photorealistic."
)
POSE_PROMPT_NEG = (
    "cropped feet, cropped legs, head-and-shoulders, bust shot, close-up, "
    "macro, partial body, blurry, ugly, watermark, text, logo, deformed, "
    "extra limbs, multiple people, crowd"
)

# The LoRA target image: SAME character in this pose. Identity comes from
# the portrait embedding; body pose comes from the OpenPose skeleton of the
# SD3.5 pose ref. The prompt describes scene/clothing only.
INSTANCE_PROMPT_TEMPLATE = (
    "{token}, full-body photo, athletic young man with short dark brown "
    "hair wearing a charcoal grey performance tee, dark technical shorts, "
    "and white athletic trainers. Plain neutral studio backdrop, soft "
    "even lighting, sharp focus, photorealistic."
)
INSTANCE_NEG = (
    "lowres, low quality, worst quality, cropped feet, cropped legs, "
    "head-and-shoulders, bust shot, close-up, macro, partial body, "
    "deformed, mutated, cross-eyed, ugly, disfigured, blurry, "
    "extra limbs, fused fingers, watermark, text, logo, multiple people"
)


async def gen_pose_ref(provider: SD35ImageProvider, label: str, action: str,
                       refs_dir: Path) -> Path:
    out = refs_dir / f"{label}.png"
    real = REAL_POSE_REFS.get(label)
    if real and real.exists():
        # Letterbox onto a 768x1024 white canvas (pose-ref dim) anchored
        # bottom-centre so OpenPose has full headroom to extract the
        # whole skeleton — feet, knees, hips, shoulders, head.
        src = Image.open(real).convert("RGB")
        sw, sh = src.size
        tw, th = 768, 1024
        scale = min(tw / sw, th / sh)
        nw, nh = int(sw * scale), int(sh * scale)
        canvas = Image.new("RGB", (tw, th), (255, 255, 255))
        canvas.paste(src.resize((nw, nh), Image.LANCZOS),
                     ((tw - nw) // 2, th - nh))
        canvas.save(out)
        print(f"[pose-ref real-photo] {label} ← {real} (letterboxed)")
        return out
    if out.exists():
        return out
    prompt = POSE_PROMPT_TEMPLATE.format(pose=action)
    seed = 700 + sum(ord(c) for c in label) % 999
    print(f"[t2i pose-ref] {label}")
    res = await provider.generate_image(
        prompt, POSE_PROMPT_NEG, out,
        settings=ImageSettings(
            width=cfg.sd35_char_width, height=cfg.sd35_char_height,
            num_inference_steps=cfg.sd35_steps,
            guidance_scale=cfg.sd35_guidance, seed=seed,
        ),
    )
    if not res.success:
        raise RuntimeError(f"pose ref failed for {label}: {res.error}")
    return out


def gen_lora_image(label: str, idx: int, portrait: Path, pose_ref: Path,
                   out_dir: Path) -> Path:
    img = out_dir / f"{idx:02d}_{label}.png"
    if img.exists():
        return img
    prompt = INSTANCE_PROMPT_TEMPLATE.format(token=INSTANCE_TOKEN)
    id_s, pose_s = STRENGTH_OVERRIDES.get(label, (0.80, 0.65))
    cmd = [
        GPU_PYTHON, str(INSTANTID_POSE),
        "--prompt", prompt,
        "--negative", INSTANCE_NEG,
        "--out", str(img),
        "--portrait", str(portrait),
        "--pose-image", str(pose_ref),
        "--width", "768", "--height", "1024",
        "--steps", "40", "--guidance", "5.0",
        "--id-strength", str(id_s), "--pose-strength", str(pose_s),
        "--seed", str(900 + idx),
    ]
    print(f"\n[InstantID dual-CN] {idx:02d} {label} → {img.name}")
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        print("STDERR:", proc.stderr[-1500:])
        raise RuntimeError(f"dual-CN failed for {label}")
    # DreamBooth wants a matching <name>.txt caption per image
    img.with_suffix(".txt").write_text(prompt + "\n")
    return img


async def main() -> None:
    if not PORTRAIT.exists():
        sys.exit(f"Portrait missing: {PORTRAIT}")
    DATASET_DIR.mkdir(parents=True, exist_ok=True)
    refs_dir = DATASET_DIR / "_pose_refs"
    refs_dir.mkdir(parents=True, exist_ok=True)
    print(f"Dataset → {DATASET_DIR}")

    sd = SD35ImageProvider()
    for idx, (label, action) in enumerate(POSES):
        ref = await gen_pose_ref(sd, label, action, refs_dir)
        gen_lora_image(label, idx, PORTRAIT, ref, DATASET_DIR)

    print(f"\nDone. {len(POSES)} pairs generated.")
    pngs = sorted(p for p in DATASET_DIR.iterdir() if p.suffix == ".png")
    print(f"Total .png in dataset (excluding pose refs): {len(pngs)}")


if __name__ == "__main__":
    asyncio.run(main())
