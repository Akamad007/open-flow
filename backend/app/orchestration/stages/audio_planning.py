"""Stage 4: audio planning — full-story narration + timing map (episode-scoped)."""

from __future__ import annotations

import json
import logging

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.agents.audio_director import AudioDirectorAgent
from app.database import async_session_factory
from app.models.audio_plan import AudioPlan
from app.models.character import Character
from app.models.episode import EpisodeStatus
from app.models.project import ProjectStatus
from app.models.render_job import JobStatus, JobType, RenderJob
from app.models.scene import Scene
from app.orchestration._common import assert_project_active, get_llm_provider
from app.orchestration.episode_helpers import resolve_active_episode
from app.orchestration.stages.audio_generation import _sum_scene_video_durations

logger = logging.getLogger(__name__)


async def _load_scenes_for_audio(db, episode_id):
    result = await db.execute(
        select(Scene)
        .options(selectinload(Scene.prompt))
        .where(Scene.episode_id == episode_id)
        .order_by(Scene.order_index)
    )
    out = []
    for s in result.scalars().all():
        scene_data = {
            "order_index": s.order_index,
            "duration_seconds": s.duration_seconds,
            "visual_summary": s.visual_summary,
            "scene_purpose": s.scene_purpose,
        }
        if s.prompt and s.prompt.video_prompt:
            scene_data["video_prompt"] = s.prompt.video_prompt
        out.append(scene_data)
    return out


async def _load_characters_for_audio(db, project_id):
    result = await db.execute(select(Character).where(Character.project_id == project_id))
    return [
        {"canonical_name": c.canonical_name, "voice_notes": c.voice_notes}
        for c in result.scalars().all()
    ]


async def _get_or_create_plan(db, project_id, episode_id) -> AudioPlan:
    existing = await db.execute(
        select(AudioPlan).where(AudioPlan.episode_id == episode_id)
    )
    plan = existing.scalar_one_or_none()
    if not plan:
        plan = AudioPlan(project_id=project_id, episode_id=episode_id)
        db.add(plan)
    return plan


def _populate_plan(plan: AudioPlan, data: dict) -> None:
    plan.full_story_narration_text = data.get("full_story_narration_text")
    plan.full_story_dialogue_plan = data.get("full_story_dialogue_plan")
    plan.full_story_audio_prompt = data.get("full_story_audio_prompt")
    plan.ambience_progression_notes = data.get("ambience_progression_notes")
    plan.sound_transition_notes = data.get("sound_transition_notes")
    plan.total_estimated_audio_duration = data.get("total_estimated_audio_duration")
    plan.timing_map_json = json.dumps(data.get("timing_map", []))


async def _apply_timing_map(db, episode_id, timing_map):
    if not timing_map:
        return
    result = await db.execute(
        select(Scene).where(Scene.episode_id == episode_id).order_by(Scene.order_index)
    )
    scene_list = result.scalars().all()
    for tm in timing_map:
        idx = tm.get("scene_index", -1)
        if 0 <= idx < len(scene_list):
            scene_list[idx].target_audio_segment_start = tm.get("audio_segment_start")
            scene_list[idx].target_audio_segment_end = tm.get("audio_segment_end")


async def run(project_id: str) -> None:
    async with async_session_factory() as db:
        project = await assert_project_active(db, project_id, "audio_planning")
        episode = await resolve_active_episode(db, project_id)
        if episode is None:
            raise RuntimeError(f"No episode for project {project_id}")

        if episode.skip_audio:
            logger.info("Episode %s skip_audio=true — bypassing audio planning", episode.id)
            episode.status = EpisodeStatus.reviewing
            project.status = ProjectStatus.reviewing
            await db.commit()
            return

        existing = await db.execute(
            select(AudioPlan).where(AudioPlan.episode_id == episode.id)
        )
        plan = existing.scalar_one_or_none()
        if plan and plan.full_story_narration_text:
            logger.info("Audio plan already exists for episode %s, skipping", episode.id)
            episode.status = EpisodeStatus.reviewing
            project.status = ProjectStatus.reviewing
            await db.commit()
            return

        job = RenderJob(
            project_id=project.id, job_type=JobType.audio_planning,
            status=JobStatus.running,
        )
        db.add(job)
        await db.flush()

        try:
            scenes = await _load_scenes_for_audio(db, episode.id)
            characters = await _load_characters_for_audio(db, project.id)
            # Stage now runs AFTER the video chord — probe the rendered scene
            # clips and target THAT duration so the narration text length matches
            # the actual video. Falls back to planned target only if no clips
            # are on disk yet (shouldn't happen in normal pipeline order).
            actual_video_dur = await _sum_scene_video_durations(db, episode.id)
            planned = (
                episode.target_duration_seconds
                or project.total_target_duration_seconds
            )
            target_total = actual_video_dur if actual_video_dur > 0 else planned
            logger.info(
                "Episode %s: audio_planning target = %.2fs (actual_video=%.2fs, planned=%s)",
                episode.id, target_total, actual_video_dur, planned,
            )

            job.payload_json = json.dumps({
                "system_prompt_path": "app/prompts/audio_director.txt",
                "episode_id": str(episode.id),
                "num_scenes": len(scenes),
                "target_duration_seconds": target_total,
                "actual_video_duration_seconds": actual_video_dur,
                "planned_duration_seconds": planned,
                "num_characters": len(characters),
            })
            await db.flush()

            agent = AudioDirectorAgent(get_llm_provider())
            result = await agent.run({
                "story_text": episode.original_story_text,
                "scenes": scenes,
                "characters": characters,
                "target_duration_seconds": target_total,
            })
            if not result.success:
                raise RuntimeError(f"Audio planning failed: {result.errors}")

            audio_plan = await _get_or_create_plan(db, project.id, episode.id)
            _populate_plan(audio_plan, result.data)
            await _apply_timing_map(db, episode.id, result.data.get("timing_map", []))

            episode.status = EpisodeStatus.reviewing
            project.status = ProjectStatus.reviewing
            job.status = JobStatus.complete

        except Exception as e:
            logger.exception("Audio planning failed")
            job.status = JobStatus.failed
            job.error_text = str(e)
            episode.status = EpisodeStatus.failed
            project.status = ProjectStatus.failed
            await db.commit()
            raise

        await db.commit()
