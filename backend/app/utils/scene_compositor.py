"""
Background removal utility for character portraits.

Uses rembg u2net_human_seg — a neural network specifically trained for
human segmentation. Works on ANY background color (not color-keying).
"""

import logging
import threading
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Module-level session caches, one per rembg model. Each model loads once
# per process and is reused for all portraits using it.
_rembg_session_cache: dict[str, object] = {}
_rembg_session_lock = threading.Lock()


def _get_rembg_session(model: str = "u2net_human_seg"):
    """Return cached rembg session for `model`. Loads once per process."""
    if model not in _rembg_session_cache:
        with _rembg_session_lock:
            if model not in _rembg_session_cache:
                from rembg import new_session
                logger.info("Loading rembg %s model (first use)...", model)
                _rembg_session_cache[model] = new_session(model)
                logger.info("rembg %s session ready", model)
    return _rembg_session_cache[model]


def remove_background(
    image_path: str,
    output_path: Optional[str] = None,
    subject_kind: str = "human",
) -> str:
    """Remove the background from a portrait image using rembg.

    `subject_kind` selects the segmentation model:
      - "human"  → u2net_human_seg (trained on people)
      - "mascot" | "creature" | "object" → u2net (general foreground/background)
    The default human model annihilates non-human subjects, so non-human
    portraits MUST pass the right kind here. Saves a transparent PNG.
    """
    out = output_path or image_path  # overwrite in-place by default
    model = "u2net_human_seg" if (subject_kind or "human").lower() == "human" else "u2net"
    try:
        from rembg import remove
        from PIL import Image

        session = _get_rembg_session(model)

        with Image.open(image_path) as img:
            result = remove(
                img.convert("RGBA"),
                session=session,
                alpha_matting=True,
                alpha_matting_foreground_threshold=240,
                alpha_matting_background_threshold=10,
                alpha_matting_erode_size=10,
            )
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        out_png = str(Path(out).with_suffix(".png"))
        result.save(out_png)
        logger.info("Background removed (%s) → %s", model, out_png)
        return out_png
    except ImportError:
        logger.warning("rembg not installed — skipping background removal")
        return image_path
    except Exception as e:
        logger.warning("Background removal failed (%s) — using original", e)
        return image_path
