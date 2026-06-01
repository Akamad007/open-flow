"""Base video generation provider interface."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class VideoSettings:
    """Settings for video generation."""
    height: int = 480
    width: int = 704
    num_frames: int = 49
    fps: int = 16
    num_inference_steps: int = 60
    guidance_scale: float = 3.5
    seed: int = 42


@dataclass
class VideoResult:
    """Result of a video generation."""
    success: bool
    file_path: Optional[str] = None
    duration_seconds: float = 0.0
    error: Optional[str] = None
    metadata: dict = field(default_factory=dict)


class VideoProvider(ABC):
    """Abstract base class for video generation providers."""

    @abstractmethod
    async def generate_video(
        self,
        prompt: str,
        negative_prompt: str,
        output_path: Path,
        video_settings: Optional[VideoSettings] = None,
        condition_image_path: Optional[str] = None,       # I2V: last frame of previous scene
        character_image_path: Optional[str] = None,       # Static character portrait
        background_image_path: Optional[str] = None,      # Background plate
        scene_action_images: Optional[list[str]] = None,  # Per-second action stills (N images)
        lora_plan_json: Optional[str] = None,             # Wan22: pre-computed LoRA + shot pick
    ) -> VideoResult:
        """Generate a video clip from a text prompt."""
        ...


    @abstractmethod
    async def get_status(self, job_id: str) -> str:
        """Get the status of a running generation job."""
        ...

    @abstractmethod
    async def cancel(self, job_id: str) -> None:
        """Cancel a running generation job."""
        ...
