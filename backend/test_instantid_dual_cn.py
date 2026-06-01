"""Same character → 3 different poses via InstantID + OpenPose dual ControlNet.

Steps:
  1. Use SD3.5 to render 3 generic-person pose references (full-body
     running, sitting on a stoop, mid-air jumping). These give us the
     OpenPose skeletons we need.
  2. For each pose, run the dual-ControlNet InstantID pipeline:
       - face identity ← character portrait
       - body pose     ← OpenPose skeleton from pose reference
     Result: SAME character in that target pose.

Re-uses the running reference from the earlier smoke test
(storage/smoke_img2img/04_control_running_t2i.png). Only sitting and
jumping references are generated fresh.
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.config import settings as cfg
from app.providers.image.base import ImageSettings
from app.providers.image.sd35_provider import SD35ImageProvider

GPU_PYTHON = "/home/akash/.pyenv/versions/video-app/bin/python"
INSTANTID_POSE = Path.home() / "instantid" / "generate_instantid_pose.py"

OUT_DIR = Path(__file__).parent / "storage" / "smoke_instantid_dualcn"
PORTRAIT = Path(__file__).parent / "storage" / "smoke_img2img" / "01_character.png"
EXISTING_RUNNING_REF = (
    Path(__file__).parent / "storage" / "smoke_img2img" / "04_control_running_t2i.png"
)

POSE_REF_NEG = (
    "cropped feet, cropped legs, head-and-shoulders, bust shot, close-up, "
    "macro, partial body, blurry, ugly, watermark, text, logo, extra limbs, "
    "deformed, mutated, low quality"
)
POSE_REFS_TO_GENERATE = [
    (
        "sitting_lacing",
        "Full-body side profile of a man sitting on the edge of a tall "
        "concrete bench with his buttocks on the bench surface and both "
        "feet flat on the ground below, knees bent at a clear right angle. "
        "He is leaning forward and reaching down with both hands to tie "
        "the laces of one trainer. Athletic build, charcoal performance "
        "tee, dark shorts, white athletic trainers. Both feet visible, "
        "head to toe in frame. Plain neutral studio backdrop, soft even "
        "lighting, sharp focus."
    ),
    (
        "jumping",
        "Full-body, head to toe in frame, both feet visible. A man mid-air "
        "in a vertical jump, knees slightly bent, arms raised, side profile, "
        "feet clearly off the ground. Athletic build, charcoal performance "
        "tee, dark shorts, athletic trainers. Plain neutral studio backdrop, "
        "soft even lighting, sharp focus."
    ),
]

# Final InstantID prompts — describe the SCENE, not the identity (identity
# comes from the portrait embedding) and not the pose (pose comes from the
# OpenPose ControlNet).
FINAL_PROMPTS = {
    "running": (
        "Cinematic full-body action photo, athletic young man wearing a "
        "charcoal grey performance tee, dark technical shorts, white "
        "athletic trainers. Plain neutral studio backdrop, soft natural "
        "lighting, sharp focus, photorealistic."
    ),
    "sitting_lacing": (
        "Cinematic full-body lifestyle photo, athletic young man wearing a "
        "charcoal grey performance tee, dark technical shorts, white "
        "athletic trainers. Plain neutral studio backdrop, soft natural "
        "lighting, sharp focus, photorealistic."
    ),
    "jumping": (
        "Cinematic full-body action photo, athletic young man wearing a "
        "charcoal grey performance tee, dark technical shorts, white "
        "athletic trainers. Plain neutral studio backdrop, soft natural "
        "lighting, sharp focus, photorealistic."
    ),
}
FINAL_NEG = (
    "lowres, low quality, worst quality, text, watermark, logo, "
    "deformed, mutated, cross-eyed, ugly, disfigured, blurry, "
    "cropped feet, cropped legs, head-and-shoulders, bust shot, close-up, "
    "extra limbs, fused fingers"
)


async def gen_pose_refs() -> dict[str, Path]:
    """Generate the missing pose-reference images via SD3.5 (re-using the
    existing running reference)."""
    refs_dir = OUT_DIR / "pose_refs"
    refs_dir.mkdir(parents=True, exist_ok=True)

    # Re-use the running reference from the previous smoke test.
    running_ref = refs_dir / "running.png"
    if not running_ref.exists():
        shutil.copy2(EXISTING_RUNNING_REF, running_ref)
        print(f"Re-using running reference: {EXISTING_RUNNING_REF.name}")

    provider = SD35ImageProvider()
    out: dict[str, Path] = {"running": running_ref}
    for label, prompt in POSE_REFS_TO_GENERATE:
        ref_path = refs_dir / f"{label}.png"
        out[label] = ref_path
        if ref_path.exists():
            print(f"Pose ref {label} exists; skipping")
            continue
        print(f"\n[SD3.5 t2i] generating pose reference: {label}")
        res = await provider.generate_image(
            prompt, POSE_REF_NEG, ref_path,
            settings=ImageSettings(
                width=cfg.sd35_char_width, height=cfg.sd35_char_height,
                num_inference_steps=cfg.sd35_steps,
                guidance_scale=cfg.sd35_guidance,
                seed=300 + sum(ord(c) for c in label) % 1000,
            ),
        )
        if not res.success:
            raise RuntimeError(f"SD3.5 failed for {label}: {res.error}")
        print(f"  → {ref_path.name}")
    return out


def run_instantid_pose(prompt: str, output_path: Path, portrait: Path,
                       pose_image: Path, seed: int) -> None:
    cmd = [
        GPU_PYTHON, str(INSTANTID_POSE),
        "--prompt", prompt,
        "--negative", FINAL_NEG,
        "--out", str(output_path),
        "--portrait", str(portrait),
        "--pose-image", str(pose_image),
        "--width", "768", "--height", "1024",
        "--steps", "40", "--guidance", "5.0",
        "--id-strength", "0.8", "--pose-strength", "0.65",
        "--seed", str(seed),
    ]
    print(f"\n→ InstantID dual-CN: {output_path.name} pose_ref={pose_image.name}")
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        print("STDERR:", proc.stderr[-2000:])
        raise RuntimeError(f"InstantID dual-CN failed for {output_path.name}")
    print(proc.stdout[-300:])


async def main() -> None:
    if not PORTRAIT.exists():
        sys.exit(f"Portrait missing: {PORTRAIT}")
    if not EXISTING_RUNNING_REF.exists():
        sys.exit(f"Running ref missing: {EXISTING_RUNNING_REF}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(PORTRAIT, OUT_DIR / "00_input_portrait.png")

    refs = await gen_pose_refs()

    for i, label in enumerate(["running", "sitting_lacing", "jumping"]):
        out = OUT_DIR / f"0{i+1}_{label}.png"
        run_instantid_pose(
            FINAL_PROMPTS[label], out, PORTRAIT, refs[label], seed=400 + i,
        )

    print("\nOutputs:")
    for f in sorted(OUT_DIR.iterdir()):
        if f.is_file():
            size_kb = f.stat().st_size // 1024
            print(f"  {f.name}  ({size_kb} KB)")


if __name__ == "__main__":
    asyncio.run(main())
