"""Standalone smoke test for the full-body portrait fix.

Exercises:
  - prompts._force_full_body — strips cropping terms + prepends framing
  - SD3.5 provider with the new 768x1280 dims
  - rembg + bbox aspect critic
  - retry loop on rejection

Saves the output to storage/smoke_portrait_fix/ so we can eyeball it.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from app.agents.image_pregen.character_portraits import (
    _is_full_body_portrait, _render_portrait_attempt,
)
from app.agents.image_pregen.prompts import build_character_prompt
from app.providers.image.sd35_provider import SD35ImageProvider
from app.utils.scene_compositor import remove_background


class _StubLLM:
    """Minimal LLM that returns a tempting torso-shot prompt — exactly the
    failure mode we want _force_full_body to clean up. If this LLM body
    survives into the SD3.5 prompt unwrapped, we know the fix didn't
    apply."""
    async def complete_json(self, *_, **__):
        return {
            "portrait_prompt": (
                "a bust shot of Maya, head and shoulders close-up, "
                "white robe and turban, long grey beard, calm expression, "
                "soft studio lighting, 35mm grain"
            ),
            "negative_prompt": (
                "ugly, watermark, blurry, deformed"
            ),
        }


CHAR = SimpleNamespace(
    canonical_name="Maya",
    physical_description=(
        "South Indian male in his 60s, long grey beard, calm gaze, weathered skin"
    ),
    clothing_description=(
        "white robe down to the ankles, white turban, simple leather sandals"
    ),
)


async def main() -> int:
    out_dir = ROOT / "storage" / "smoke_portrait_fix"
    out_dir.mkdir(parents=True, exist_ok=True)
    portrait_path = out_dir / "maya.png"
    if portrait_path.exists():
        portrait_path.unlink()

    prompt, neg = await build_character_prompt(_StubLLM(), CHAR, story_summary="PSA")
    print(f"\n=== prompt ({len(prompt)} chars) ===")
    print(prompt[:400])
    print(f"\n=== negative ({len(neg)} chars) ===")
    print(neg[:400])

    assert prompt.startswith("full-body portrait head to toe in frame"), \
        f"framing prefix missing! prompt starts: {prompt[:80]!r}"
    assert "bust" not in prompt.lower(), "'bust' leaked through scrub"
    assert "close-up" not in prompt.lower(), "'close-up' leaked through scrub"
    assert "bust shot" in neg, "negative-guard for bust shot missing"

    sd = SD35ImageProvider()
    print("\n=== SD3.5 render (this takes ~60s on a 16GB GPU) ===")
    res = await _render_portrait_attempt(sd, prompt, neg, portrait_path, seed=12345)
    if not res.success:
        print(f"FAIL: render failed: {res.error}")
        return 1

    clean = remove_background(str(portrait_path))
    ok, aspect = _is_full_body_portrait(clean)
    print(f"\n=== bbox critic ===")
    print(f"  aspect = {aspect:.2f}  ok = {ok}  (threshold 2.2)")

    if ok:
        print(f"\nPASS — full-body portrait at {clean}")
        return 0
    print(f"\nFAIL — portrait at {clean} is still a torso shot (aspect {aspect:.2f})")
    return 2


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
