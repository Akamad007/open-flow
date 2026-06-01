"""Composite a bg-removed product hero onto a bg-removed character render.

InstantID + OpenPose dual-CN locks face identity and body pose, but it
has no signal for arbitrary product placement — so a "character holding
cola" prompt produces a great Sadhguru with empty hands. PRODUCT-IMG2IMG
goes the other way and bulldozes the character. This compositor fills
the gap by alpha-pasting the product onto the already-rendered character
at a role-appropriate scale and position.

Inputs are RGBA PNGs (rembg-cleaned). Output overwrites the character
render in place — that file is what `scene_action_seq` Asset rows point
to and what LTX-Video receives as conditioning.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image

logger = logging.getLogger(__name__)


# Per-role product sizing as a fraction of canvas height, plus a position
# anchor expressed in canvas-fractional (x, y) coordinates measured from
# the centre of the product's bbox. Roles map to ad intent:
#   hero    — product dominates the frame, slightly off-centre next to character
#   holding — product is in the character's hand area (right of centre, lower-mid)
#   background — small product on a surface, lower-left
_ROLE_LAYOUT = {
    "hero":       {"scale": 0.55, "anchor": (0.66, 0.55)},
    "holding":    {"scale": 0.28, "anchor": (0.62, 0.62)},
    "background": {"scale": 0.18, "anchor": (0.18, 0.82)},
}


def _bbox_or_full(im: Image.Image) -> tuple[int, int, int, int]:
    """rembg outputs RGBA with alpha=0 background; bbox of alpha gives us
    the actual subject. Falls back to full canvas if image is opaque."""
    if im.mode != "RGBA":
        return (0, 0, im.width, im.height)
    bb = im.split()[-1].getbbox()
    return bb if bb else (0, 0, im.width, im.height)


def composite_product(
    character_path: Path | str,
    product_path: Path | str,
    role: str,
    *,
    output_path: Path | str | None = None,
) -> Path:
    """Paste `product_path` onto `character_path` at role-appropriate
    scale + position. Both inputs must be PNGs; `product_path` must be
    bg-removed (alpha channel). Output is RGBA PNG written to
    `output_path` (defaults to overwriting `character_path`)."""
    char_p = Path(character_path)
    prod_p = Path(product_path)
    out_p = Path(output_path) if output_path else char_p

    layout = _ROLE_LAYOUT.get((role or "holding").lower(), _ROLE_LAYOUT["holding"])
    with Image.open(char_p) as char_raw, Image.open(prod_p) as prod_raw:
        char = char_raw.convert("RGBA")
        prod = prod_raw.convert("RGBA")
        prod = prod.crop(_bbox_or_full(prod))

        target_h = max(64, int(char.height * layout["scale"]))
        scale = target_h / prod.height
        target_w = max(32, int(prod.width * scale))
        prod_resized = prod.resize((target_w, target_h), Image.LANCZOS)

        ax, ay = layout["anchor"]
        cx = int(char.width * ax)
        cy = int(char.height * ay)
        x = max(0, min(char.width - target_w, cx - target_w // 2))
        y = max(0, min(char.height - target_h, cy - target_h // 2))

        canvas = char.copy()
        canvas.alpha_composite(prod_resized, dest=(x, y))
        canvas.save(out_p)
    logger.info(
        "Composited product onto %s (role=%s scale=%.2f size=%dx%d at %d,%d)",
        out_p.name, role, layout["scale"], target_w, target_h, x, y,
    )
    return out_p
