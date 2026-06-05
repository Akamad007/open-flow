"""Base stitching provider interface."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class SceneClip:
    """A scene video clip with its target duration for stitching."""
    scene_id: str
    file_path: Path
    order_index: int
    target_duration: float  # target duration in seconds
    actual_duration: float | None = None  # actual clip duration
    caption: str | None = None  # optional on-screen caption burned in at stitch time


@dataclass
class StitchSettings:
    """Settings for the final stitch."""
    output_format: str = "mp4"
    video_codec: str = "libx264"
    audio_codec: str = "aac"
    crf: int = 18  # Quality (lower = better)
    preset: str = "medium"
    apply_crossfades: bool = True
    crossfade_duration: float = 0.3


@dataclass
class StitchResult:
    """Result of a stitching operation."""
    success: bool
    file_path: Optional[str] = None
    total_duration: float = 0.0
    error: Optional[str] = None
    metadata: dict = field(default_factory=dict)


class StitchingProvider(ABC):
    """Abstract base class for video stitching."""

    @abstractmethod
    async def stitch(
        self,
        scene_clips: list[SceneClip],
        audio_path: Optional[Path],
        output_path: Path,
        stitch_settings: Optional[StitchSettings] = None,
    ) -> StitchResult:
        """
        Stitch scene clips together. Audio overlay is optional.

        Args:
            scene_clips: Ordered list of scene clips.
            audio_path: Path to the full-story audio file, or None for a
                silent background render the caller will dub themselves.
            output_path: Where to write the final output.
            stitch_settings: Encoding and transition settings.

        Returns:
            StitchResult with the final file path and duration.
        """
        ...
