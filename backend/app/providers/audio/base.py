"""Base audio generation provider interface."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class AudioSettings:
    """Settings for audio generation."""
    sample_rate: int = 44100
    channels: int = 2
    format: str = "wav"
    voice: str = "default"
    speed: float = 1.0


@dataclass
class AudioResult:
    """Result of an audio generation."""
    success: bool
    file_path: Optional[str] = None
    duration_seconds: float = 0.0
    error: Optional[str] = None
    metadata: dict = field(default_factory=dict)


class AudioProvider(ABC):
    """Abstract base class for full-story audio generation."""

    @abstractmethod
    async def generate_full_story_audio(
        self,
        narration_text: str,
        output_path: Path,
        target_duration: Optional[float] = None,
        audio_settings: Optional[AudioSettings] = None,
    ) -> AudioResult:
        """
        Generate one continuous audio file for the full story.

        Args:
            narration_text: The full narration script.
            output_path: Where to write the output file.
            target_duration: Target duration in seconds to aim for.
            audio_settings: Generation settings.

        Returns:
            AudioResult with the file path and actual duration.
        """
        ...

    @abstractmethod
    async def get_status(self, job_id: str) -> str:
        """Get status of a running audio generation."""
        ...

    @abstractmethod
    async def cancel(self, job_id: str) -> None:
        """Cancel a running audio generation."""
        ...
