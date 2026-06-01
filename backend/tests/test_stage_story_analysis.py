"""End-to-end test of `stages.story_analysis.run` against Postgres + FakeLLM."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from app.models.character import Character
from app.models.episode import Episode, EpisodeStatus
from app.models.location import Location
from app.models.project import Project, ProjectStatus
from app.models.render_job import JobStatus, JobType, RenderJob
from app.orchestration import _common
from app.orchestration._common import ProjectCancelledError
from app.orchestration.stages import story_analysis


pytestmark = pytest.mark.slow


CANNED_LLM_OUTPUT = {
    "story_summary": "A runner moves through SF.",
    "pacing_notes": "fast → reflective",
    "beats": [{"description": "Sets out at dawn"}, {"description": "Reaches the bridge"}],
    "characters": [
        {
            "canonical_name": "Lena",
            "gender": "female",
            "ethnicity": "asian",
            "skin_tone": "light",
            "physical_description": "athletic, ponytail",
            "clothing_description": "red windbreaker",
            "personality_notes": "determined",
            "voice_notes": "soft alto",
        },
    ],
    "locations": [{"name": "SF Streets", "description": "fog, hills, cable cars"}],
    "style_lock": "cinematic urban dawn, soft fog light, cool blue tones, subtle film grain, contemplative mood",
}


async def _make_project(db_session) -> Project:
    project = Project(
        title="run",
        original_story_text="A runner.",
        status=ProjectStatus.draft,
        total_target_duration_seconds=30.0,
    )
    # status=draft is "inactive" for the cancellation guard, so flip to analyzing first
    # — except the test wants run() to flip it from draft itself? Actually the original
    # behavior is: pipeline expects an active status. Use 'analyzing' for the test setup.
    project.status = ProjectStatus.analyzing
    db_session.add(project)
    await db_session.flush()
    db_session.add(Episode(
        project_id=project.id, order_index=0, title="Episode 1",
        status=EpisodeStatus.draft, original_story_text="A runner.",
        target_duration_seconds=30.0, continue_from_previous=False,
    ))
    await db_session.commit()
    return project


async def test_runs_story_analysis_happy_path(db_session, monkeypatch, fake_llm):
    project = await _make_project(db_session)
    fake_llm._queue = [CANNED_LLM_OUTPUT]
    monkeypatch.setattr(_common, "get_llm_provider", lambda: fake_llm)
    monkeypatch.setattr(story_analysis, "get_llm_provider", lambda: fake_llm)

    await story_analysis.run(str(project.id))

    await db_session.refresh(project)
    assert project.status == ProjectStatus.planning
    assert project.story_summary == CANNED_LLM_OUTPUT["story_summary"]
    assert json.loads(project.beat_list_json) == CANNED_LLM_OUTPUT["beats"]
    assert project.pacing_notes == CANNED_LLM_OUTPUT["pacing_notes"]

    chars = (await db_session.execute(
        select(Character).where(Character.project_id == project.id)
    )).scalars().all()
    assert len(chars) == 1
    assert chars[0].canonical_name == "Lena"
    assert "Gender: female" in chars[0].physical_description
    assert "Ethnicity: asian" in chars[0].physical_description
    assert chars[0].clothing_description == "red windbreaker"

    locs = (await db_session.execute(
        select(Location).where(Location.project_id == project.id)
    )).scalars().all()
    assert len(locs) == 1
    assert locs[0].name == "SF Streets"

    jobs = (await db_session.execute(
        select(RenderJob).where(RenderJob.project_id == project.id)
    )).scalars().all()
    assert len(jobs) == 1
    assert jobs[0].job_type == JobType.story_analysis
    assert jobs[0].status == JobStatus.complete


async def test_idempotent_skips_when_already_analyzed(db_session, monkeypatch, fake_llm):
    project = await _make_project(db_session)
    project.beat_list_json = json.dumps([{"description": "already done"}])
    # Idempotency now keys off the episode's beat list, not the project's.
    ep = (await db_session.execute(
        select(Episode).where(Episode.project_id == project.id)
    )).scalar_one()
    ep.beat_list_json = json.dumps([{"description": "already done"}])
    db_session.add(Character(
        project_id=project.id, canonical_name="Lena", physical_description="x",
    ))
    await db_session.commit()

    fake_llm._queue = [CANNED_LLM_OUTPUT]  # would crash test if called
    monkeypatch.setattr(story_analysis, "get_llm_provider", lambda: fake_llm)

    await story_analysis.run(str(project.id))

    await db_session.refresh(project)
    assert project.status == ProjectStatus.planning
    assert fake_llm.calls == [], "LLM should not have been called on idempotent skip"


async def test_marks_project_failed_on_agent_error(db_session, monkeypatch):
    project = await _make_project(db_session)

    class BoomLLM:
        async def complete_json(self, *_, **__):
            raise RuntimeError("LLM down")

    monkeypatch.setattr(story_analysis, "get_llm_provider", lambda: BoomLLM())

    with pytest.raises(RuntimeError):
        await story_analysis.run(str(project.id))

    await db_session.refresh(project)
    assert project.status == ProjectStatus.failed

    job = (await db_session.execute(
        select(RenderJob).where(RenderJob.project_id == project.id)
    )).scalar_one()
    assert job.status == JobStatus.failed
    assert "LLM down" in (job.error_text or "")


async def test_short_circuits_when_project_inactive(db_session, monkeypatch, fake_llm):
    project = Project(
        title="t", original_story_text="s",
        status=ProjectStatus.complete,  # terminal
        total_target_duration_seconds=10.0,
    )
    db_session.add(project)
    await db_session.commit()

    monkeypatch.setattr(story_analysis, "get_llm_provider", lambda: fake_llm)

    with pytest.raises(ProjectCancelledError):
        await story_analysis.run(str(project.id))

    assert fake_llm.calls == []
