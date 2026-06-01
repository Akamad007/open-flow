"""The Pipeline facade re-exports the public API and delegates each method."""

from __future__ import annotations

import pytest

from app.orchestration import pipeline


def test_facade_exports_provider_factories():
    assert callable(pipeline.get_llm_provider)
    assert callable(pipeline.get_video_provider)
    assert callable(pipeline.get_audio_provider)
    assert callable(pipeline.get_stitching_provider)
    assert callable(pipeline.get_image_provider)


def test_facade_exports_cancellation_error():
    assert issubclass(pipeline.ProjectCancelledError, RuntimeError)


def test_pipeline_class_has_expected_methods():
    p = pipeline.Pipeline()
    expected = {
        "run_story_analysis", "run_scene_planning", "run_prompt_generation",
        "run_audio_planning", "run_consistency_review", "run_image_pregen",
        "run_audio_generation", "run_stitching", "generate_single_scene",
        "get_scene_ids_with_prompts", "finalize_videos",
    }
    assert expected.issubset({name for name in dir(p) if not name.startswith("_")})


@pytest.mark.parametrize("method,stage_module,stage_attr", [
    ("run_story_analysis", "story_analysis", "run"),
    ("run_scene_planning", "scene_planning", "run"),
    ("run_audio_planning", "audio_planning", "run"),
    ("run_consistency_review", "consistency_review", "run"),
    ("run_image_pregen", "image_pregen", "run"),
    ("run_audio_generation", "audio_generation", "run"),
    ("run_stitching", "stitching", "run"),
])
async def test_pipeline_methods_delegate_to_stage_modules(monkeypatch, method, stage_module, stage_attr):
    from app.orchestration import stages
    target_module = getattr(stages, stage_module)

    calls = []

    async def fake_run(project_id, *args, **kwargs):
        calls.append((stage_module, project_id, args, kwargs))

    monkeypatch.setattr(target_module, stage_attr, fake_run)

    p = pipeline.Pipeline()
    await getattr(p, method)("project-xyz")
    assert calls == [(stage_module, "project-xyz", (), {})]


async def test_run_prompt_generation_passes_critique_kwarg(monkeypatch):
    from app.orchestration.stages import prompt_generation
    captured = {}

    async def fake_run(project_id, critique_feedback=None):
        captured["pid"] = project_id
        captured["critique"] = critique_feedback

    monkeypatch.setattr(prompt_generation, "run", fake_run)

    feedback = {"issues": [], "suggestions": ["fix lighting"]}
    await pipeline.Pipeline().run_prompt_generation("p", critique_feedback=feedback)
    assert captured == {"pid": "p", "critique": feedback}


async def test_generate_single_scene_delegates(monkeypatch):
    from app.orchestration.stages import scene_video
    captured = {}

    async def fake_generate(project_id, scene_id, force=False):
        captured.update(project_id=project_id, scene_id=scene_id, force=force)
        return {"scene_id": scene_id, "status": "complete", "file": "/x.mp4"}

    monkeypatch.setattr(scene_video, "generate_single", fake_generate)

    result = await pipeline.Pipeline().generate_single_scene("p", "s", force=True)
    assert result["status"] == "complete"
    assert captured == {"project_id": "p", "scene_id": "s", "force": True}


async def test_finalize_videos_delegates(monkeypatch):
    from app.orchestration.stages import scene_video
    captured = {}

    async def fake_finalize(project_id, results):
        captured.update(project_id=project_id, results=results)

    monkeypatch.setattr(scene_video, "finalize_videos", fake_finalize)

    await pipeline.Pipeline().finalize_videos("p", [{"status": "complete"}])
    assert captured == {"project_id": "p", "results": [{"status": "complete"}]}


async def test_get_scene_ids_with_prompts_delegates(monkeypatch):
    from app.orchestration.stages import scene_video

    async def fake(project_id):
        return ["a", "b"]

    monkeypatch.setattr(scene_video, "get_scene_ids_with_prompts", fake)

    assert await pipeline.Pipeline().get_scene_ids_with_prompts("p") == ["a", "b"]
