"""Base image generation provider interface."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class ImageSettings:
    """Settings for image generation."""
    width: int = 768
    height: int = 1024
    num_inference_steps: int = 95
    guidance_scale: float = 7.5
    seed: int = 42
    no_t5: bool = True           # Skip T5 encoder — saves ~5GB VRAM
    init_image_path: Optional[str] = None  # Reference image for img2img identity lock
    strength: float = 0.72       # Img2img denoising strength (0=copy original, 1=ignore it)
    identity_strength: float = 0.80  # Identity-conditioning strength (PuLID/InstantID)
    pose_image_path: Optional[str] = None  # Reference image for OpenPose body-pose ControlNet
    pose_strength: float = 0.65  # OpenPose ControlNet strength when pose_image_path is set


@dataclass
class IdentityRef:
    """Face-identity reference for identity-aware providers (InstantID, PuLID).

    `embedding_path` points to a cached face-embedding `.pt` next to the
    portrait — extracted once and re-used across every still so we never
    pay the InsightFace cost twice. Mtime-keyed; a portrait re-render
    invalidates the cache. `portrait_path` is the source PNG used to
    build the embedding (also passed straight to InstantID for IdentityNet
    keypoint conditioning).
    """
    portrait_path: str
    embedding_path: str


@dataclass
class ImageResult:
    """Result of an image generation."""
    success: bool
    file_path: Optional[str] = None
    error: Optional[str] = None
    metadata: dict = field(default_factory=dict)


class ImageProvider(ABC):
    """Abstract base class for image generation providers."""

    # Per-class flag: True when the provider supports identity-locked
    # generation via `generate_with_identity`. Action-stills checks this
    # to decide whether to route through the face-embedding path or fall
    # back to plain text-to-image.
    supports_identity: bool = False

    @abstractmethod
    async def generate_image(
        self,
        prompt: str,
        negative_prompt: str,
        output_path: Path,
        settings: Optional[ImageSettings] = None,
    ) -> ImageResult:
        """Generate an image from a text prompt."""
        ...

    async def generate_with_identity(
        self,
        prompt: str,
        negative_prompt: str,
        output_path: Path,
        identity: IdentityRef,
        settings: Optional[ImageSettings] = None,
    ) -> ImageResult:
        """Generate an image locked to a character identity. Default impl
        falls back to plain text-to-image — providers that genuinely
        support identity (InstantID, PuLID) MUST override this AND set
        `supports_identity = True`."""
        return await self.generate_image(prompt, negative_prompt, output_path, settings)
