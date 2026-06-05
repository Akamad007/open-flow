"""Provider factories, project-cancellation guard, and stage-shared helpers."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.project import Project, ProjectStatus
from app.providers.llm.base import LLMProvider


_INACTIVE_STATUSES = frozenset({
    ProjectStatus.failed,
    ProjectStatus.complete,
    ProjectStatus.draft,
})


class ProjectCancelledError(RuntimeError):
    """Raised when a pipeline stage is skipped because the project is no longer active."""


async def assert_project_active(db: AsyncSession, project_id: str, stage: str) -> Project:
    project = await db.get(Project, uuid.UUID(project_id))
    if not project:
        raise ProjectCancelledError(
            f"[{stage}] Project {project_id} no longer exists — short-circuiting."
        )
    if project.status in _INACTIVE_STATUSES:
        raise ProjectCancelledError(
            f"[{stage}] Project {project_id} is in status '{project.status.value}' "
            f"(not active) — short-circuiting."
        )
    return project


def get_llm_provider(model: str | None = None) -> LLMProvider:
    """Returns the configured LLM provider. Pass `model` to override the
    default — used by the visual_director (highest-leverage prompt) to call
    a stronger model than the cheap default."""
    if settings.llm_provider == "openai":
        from app.providers.llm.openai_provider import OpenAICompatibleProvider
        return OpenAICompatibleProvider(model=model)
    from app.providers.llm.stub_provider import StubLLMProvider
    return StubLLMProvider()


def get_strong_llm_provider() -> LLMProvider:
    """Stronger LLM for the visual_director — its prompts drive ~$2 of GPU
    work per scene, so spending more on tokens here is net-positive."""
    return get_llm_provider(model=settings.llm_strong_model)


def get_video_provider(profile_name: str | None = None):
    """Returns a video provider. If a pipeline profile is given, the profile's
    `video_provider` field overrides the global `settings.video_provider`."""
    from app.orchestration.profiles import get_profile
    name = get_profile(profile_name).video_provider if profile_name else settings.video_provider
    if name == "ltx":
        from app.providers.video.ltx_provider import LTXVideoProvider
        return LTXVideoProvider()
    if name == "wan22":
        from app.providers.video.wan22_provider import Wan22VideoProvider
        return Wan22VideoProvider()
    if name == "wan_phantom":
        from app.providers.video.wan_phantom_provider import WanPhantomVideoProvider
        return WanPhantomVideoProvider()
    from app.providers.video.stub_provider import StubVideoProvider
    return StubVideoProvider()


def get_audio_provider():
    if settings.audio_provider == "chatterbox":
        from app.providers.audio.chatterbox_provider import ChatterboxAudioProvider
        return ChatterboxAudioProvider()
    from app.providers.audio.stub_provider import StubAudioProvider
    return StubAudioProvider()


def get_stitching_provider():
    from app.providers.stitching.ffmpeg_provider import FFmpegStitchingProvider
    return FFmpegStitchingProvider()


def get_image_provider():
    """Returns the SD3.5 (or stub) provider used for portraits, backgrounds,
    products, and the t2i action-still fallback. Identity-aware action
    stills go through `get_identity_image_provider()` instead."""
    if settings.image_provider == "sd35":
        from app.providers.image.sd35_provider import SD35ImageProvider
        return SD35ImageProvider()
    from app.providers.image.stub_provider import StubImageProvider
    return StubImageProvider()


def get_identity_image_provider():
    """Returns an identity-aware provider (InstantID-XL) wrapping the
    base provider. Falls back to the base provider if the feature flag is
    off or the GPU subprocess script isn't installed — `supports_identity`
    on the returned provider tells callers whether to route stills
    through `generate_with_identity`."""
    base = get_image_provider()
    if not settings.identity_provider_enabled:
        return base
    from pathlib import Path
    instantid_dir = Path(settings.instantid_dir)
    # Either script being present is enough — the provider picks dual-CN
    # vs face-only at call time based on whether a pose ref was provided.
    if not (instantid_dir / "generate_instantid.py").exists() and not (
        instantid_dir / "generate_instantid_pose.py"
    ).exists():
        return base
    from app.providers.image.instantid_provider import InstantIDImageProvider
    return InstantIDImageProvider(fallback=base)
