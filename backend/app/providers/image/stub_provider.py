"""Stub image provider for testing without GPU."""

import logging
import shutil
from pathlib import Path
from typing import Optional

from app.providers.image.base import ImageProvider, ImageResult, ImageSettings

logger = logging.getLogger(__name__)


class StubImageProvider(ImageProvider):
    """Returns a placeholder image immediately — for testing."""

    async def generate_image(
        self,
        prompt: str,
        negative_prompt: str,
        output_path: Path,
        settings_: Optional[ImageSettings] = None,
    ) -> ImageResult:
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Create a minimal 1×1 white PNG as placeholder
        try:
            from PIL import Image
            img = Image.new("RGB", (768, 1024), color=(240, 220, 180))
            img.save(str(output_path))
        except ImportError:
            # If PIL not available, write empty file
            output_path.write_bytes(b"")

        logger.info("Stub image generated → %s (prompt: %s...)", output_path.name, prompt[:50])
        return ImageResult(
            success=True,
            file_path=str(output_path),
            metadata={"provider": "stub"},
        )
