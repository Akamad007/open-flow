"""Pipeline facade — delegates each stage to its module under `stages/`."""

from __future__ import annotations

from typing import Optional

from app.orchestration._common import (
    ProjectCancelledError,
    get_audio_provider,
    get_image_provider,
    get_llm_provider,
    get_stitching_provider,
    get_video_provider,
)
from app.orchestration.stages import (
    audio_generation,
    audio_planning,
    canonical_portrait,
    consistency_review,
    image_pregen,
    prompt_generation,
    scene_planning,
    scene_video,
    stitching,
    story_analysis,
)


__all__ = [
    "Pipeline",
    "ProjectCancelledError",
    "get_llm_provider",
    "get_video_provider",
    "get_audio_provider",
    "get_stitching_provider",
    "get_image_provider",
]


class Pipeline:
    """Thin facade — every method delegates to a stage module."""

    async def run_story_analysis(self, project_id: str) -> None:
        await story_analysis.run(project_id)

    async def run_scene_planning(self, project_id: str) -> None:
        await scene_planning.run(project_id)

    async def run_prompt_generation(
        self, project_id: str, critique_feedback: Optional[dict] = None,
    ) -> None:
        await prompt_generation.run(project_id, critique_feedback=critique_feedback)

    async def run_audio_planning(self, project_id: str) -> None:
        await audio_planning.run(project_id)

    async def run_consistency_review(self, project_id: str) -> None:
        await consistency_review.run(project_id)

    async def run_image_pregen(self, project_id: str) -> None:
        await image_pregen.run(project_id)

    async def run_canonical_portrait(self, project_id: str) -> None:
        await canonical_portrait.run(project_id)

    async def run_audio_generation(self, project_id: str) -> None:
        await audio_generation.run(project_id)

    async def run_stitching(self, project_id: str) -> None:
        await stitching.run(project_id)

    async def generate_single_scene(
        self, project_id: str, scene_id: str, force: bool = False,
    ) -> dict:
        return await scene_video.generate_single(project_id, scene_id, force)

    async def get_scene_ids_with_prompts(self, project_id: str) -> list[str]:
        return await scene_video.get_scene_ids_with_prompts(project_id)

    async def finalize_videos(self, project_id: str, results: list[dict]) -> None:
        await scene_video.finalize_videos(project_id, results)
