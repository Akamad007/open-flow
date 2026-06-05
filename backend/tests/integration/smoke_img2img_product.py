"""Standalone smoke test for the product img2img bake.

Exercises the SD3.5 provider directly — no DB, no celery, no LLM. Generates:
  1. A character portrait (text-to-image)
  2. A product hero shot (text-to-image, bg-removed)
  3. Action stills with the product baked in via img2img (init = product hero,
     strength = settings.product_img2img_strength)
  4. One control still with no init (pure t2i) — to compare
"""

from __future__ import annotations

import asyncio
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.config import settings
from app.providers.image.base import ImageSettings
from app.providers.image.sd35_provider import SD35ImageProvider
from app.utils.scene_compositor import remove_background

OUT_DIR = Path(__file__).parent / "storage" / "smoke_img2img"


CHAR_PROMPT = (
    "Full-body portrait, head to toe in frame, both feet visible, neutral "
    "standing pose, three-quarter front view. A man in his early 30s with "
    "light to medium warm tan skin, short dark brown hair, lean athletic "
    "build. Wearing a charcoal grey short-sleeve performance tee, dark "
    "technical shorts above the knee, and plain white athletic trainers. "
    "Plain neutral grey studio backdrop, soft even lighting, sharp focus, "
    "high detail."
)
CHAR_NEG = (
    "cropped, head-and-shoulders, bust shot, close-up, cropped feet, cropped "
    "legs, partial body, blurry, ugly, watermark, text, logo, extra limbs, "
    "deformed, mutated, low quality, bad quality, out of focus, multiple "
    "people, crowd"
)

PRODUCT_PROMPT = (
    "Bright orange high-performance running shoe, three-quarter front low "
    "angle, sleek mesh upper, white midsole, dark rubber outsole, subtle "
    "embossed side panel without text, centred subject, clean neutral soft-grey "
    "studio backdrop, soft product lighting."
)
PRODUCT_NEG = (
    "text, letters, words, wordmark, logo, watermark, label text, brand name, "
    "hand, finger, person, character, environment, scenery, blurry, deformed shape"
)


ACTION_PROMPTS = [
    (
        "running",
        "Mid-stride run, full body in frame, side profile, both feet off "
        "ground in athletic gait, arms swinging in opposition. The same lean "
        "athletic man in his early 30s, charcoal performance tee and dark "
        "shorts, bright orange running shoes on his feet. Sharp focus.",
    ),
    (
        "sitting_lacing",
        "Seated low on a stoop, leaning forward, both hands tying the laces "
        "of one running shoe, full body visible from the side. The same lean "
        "athletic man in his early 30s, charcoal performance tee and dark "
        "shorts, bright orange running shoes on his feet. Sharp focus.",
    ),
    (
        "jumping",
        "Mid-air jump in full extension, arms raised, knees slightly bent, "
        "full body in frame, side profile. The same lean athletic man in his "
        "early 30s, charcoal performance tee and dark shorts, bright orange "
        "running shoes on his feet. Sharp focus.",
    ),
]
ACTION_NEG = (
    "bad anatomy, deformed hands, extra digits, fused fingers, text, watermark, "
    "logo, multiple people, crowd, blurry, low quality, environment, scenery, "
    "lighting, time of day, weather, cinematic effects"
)


async def gen_text2img(provider, prompt: str, neg: str, out: Path,
                       width: int, height: int, seed: int) -> Path:
    print(f"\n[t2i] {out.name} ({width}x{height})")
    res = await provider.generate_image(
        prompt, neg, out,
        settings=ImageSettings(
            width=width, height=height,
            num_inference_steps=settings.sd35_steps,
            guidance_scale=settings.sd35_guidance,
            seed=seed,
        ),
    )
    if not res.success:
        raise RuntimeError(f"t2i failed: {res.error}")
    print(f"  → {res.file_path}")
    return Path(res.file_path)


async def gen_img2img(provider, prompt: str, neg: str, out: Path,
                      init: Path, strength: float, width: int, height: int,
                      seed: int) -> Path:
    print(f"\n[img2img] {out.name} init={init.name} strength={strength:.2f}")
    res = await provider.generate_image(
        prompt, neg, out,
        settings=ImageSettings(
            width=width, height=height,
            num_inference_steps=settings.sd35_steps,
            guidance_scale=settings.sd35_guidance,
            seed=seed,
            init_image_path=str(init),
            strength=strength,
        ),
    )
    if not res.success:
        raise RuntimeError(f"img2img failed: {res.error}")
    print(f"  → {res.file_path}")
    return Path(res.file_path)


async def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Output dir: {OUT_DIR}")
    print(f"product_img2img_strength = {settings.product_img2img_strength}")
    print(f"sd35_steps = {settings.sd35_steps}, guidance = {settings.sd35_guidance}")

    provider = SD35ImageProvider()

    # 1. Character portrait
    char_path = await gen_text2img(
        provider, CHAR_PROMPT, CHAR_NEG, OUT_DIR / "01_character.png",
        width=settings.sd35_char_width, height=settings.sd35_char_height, seed=42,
    )

    # 2. Product hero — square, then bg-remove (same as products.py)
    product_raw = await gen_text2img(
        provider, PRODUCT_PROMPT, PRODUCT_NEG, OUT_DIR / "02_product_hero_raw.png",
        width=1024, height=1024, seed=42,
    )
    # Keep an opaque copy, then bg-remove a separate "_cutout" we'll use as init.
    product_cutout = OUT_DIR / "02_product_hero_cutout.png"
    shutil.copy2(product_raw, product_cutout)
    remove_background(str(product_cutout))
    print(f"  bg-removed → {product_cutout}")

    # 3. Action stills — img2img with the bg-removed product hero as init.
    for i, (label, prompt) in enumerate(ACTION_PROMPTS):
        out = OUT_DIR / f"03_action_{i:02d}_{label}_img2img.png"
        await gen_img2img(
            provider, prompt, ACTION_NEG, out,
            init=product_cutout,
            strength=settings.product_img2img_strength,
            width=settings.sd35_char_width,
            height=settings.sd35_char_height,
            seed=100 + i,
        )

    # 4. Control: same first action prompt, pure t2i (no init) — for comparison.
    label, prompt = ACTION_PROMPTS[0]
    await gen_text2img(
        provider, prompt, ACTION_NEG,
        OUT_DIR / f"04_control_{label}_t2i.png",
        width=settings.sd35_char_width, height=settings.sd35_char_height, seed=100,
    )

    print("\nDone. Outputs:")
    for f in sorted(OUT_DIR.iterdir()):
        size_kb = f.stat().st_size // 1024
        print(f"  {f.name}  ({size_kb} KB)")


if __name__ == "__main__":
    asyncio.run(main())
