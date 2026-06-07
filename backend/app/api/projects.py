"""Projects API router — CRUD operations for projects."""

import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.character import Character
from app.models.episode import Episode, EpisodeStatus
from app.models.location import Location
from app.models.project import Project, ProjectStatus
from app.models.scene import Scene
from app.api._common import NOT_FOUND_RESPONSE, get_or_404
from app.orchestration.profiles import DEFAULT_PROFILE, PROFILES, list_profiles
from app.schemas.project import ProjectCreate, ProjectList, ProjectRead, ProjectUpdate
from app.utils.gpu_routing import assign_project_gpu

router = APIRouter(tags=["projects"], responses=NOT_FOUND_RESPONSE)

_ACTIVE_EP_STATUSES = (
    EpisodeStatus.analyzing, EpisodeStatus.planning, EpisodeStatus.prompting,
    EpisodeStatus.audio_planning, EpisodeStatus.reviewing,
    EpisodeStatus.image_pregen, EpisodeStatus.generating, EpisodeStatus.stitching,
)


async def _project_read_with_counts(project: Project, db: AsyncSession) -> ProjectRead:
    """Serialize a project with its scene/character/location counts populated."""
    result = ProjectRead.model_validate(project)
    result.scene_count = await db.scalar(
        select(func.count(Scene.id)).where(Scene.project_id == project.id)
    ) or 0
    result.character_count = await db.scalar(
        select(func.count(Character.id)).where(Character.project_id == project.id)
    ) or 0
    result.location_count = await db.scalar(
        select(func.count(Location.id)).where(Location.project_id == project.id)
    ) or 0
    return result


@router.get("/pipelines")
async def get_pipelines():
    """Available pipeline profiles for the FE model-selection dropdown."""
    return list_profiles()


@router.get("/projects", response_model=List[ProjectList])
async def list_projects(db: AsyncSession = Depends(get_db)):
    """List all projects with scene counts."""
    stmt = (
        select(
            Project,
            func.count(Scene.id).label("scene_count"),
        )
        .outerjoin(Scene, Scene.project_id == Project.id)
        .group_by(Project.id)
        .order_by(Project.updated_at.desc())
    )
    result = await db.execute(stmt)
    rows = result.all()

    projects = []
    for project, scene_count in rows:
        p = ProjectList.model_validate(project)
        p.scene_count = scene_count
        projects.append(p)
    return projects


@router.post("/projects", response_model=ProjectRead, status_code=201)
async def create_project(data: ProjectCreate, db: AsyncSession = Depends(get_db)):
    """Create a new project. Auto-triggers the full pipeline if story text is provided."""
    profile_name = data.pipeline_profile or DEFAULT_PROFILE
    if profile_name not in PROFILES:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown pipeline_profile {profile_name!r}. Choices: {sorted(PROFILES)}",
        )
    project = Project(
        title=data.title,
        original_story_text=data.original_story_text,
        total_target_duration_seconds=data.total_target_duration_seconds,
        pipeline_profile=profile_name,
        status=ProjectStatus.draft,
    )
    db.add(project)
    await db.flush()

    # YouTube URL on the project form configures Episode 0: probe duration,
    # force skip_audio, and use the clip length as the episode target so the
    # video matches the audio.
    yt_url = (data.youtube_audio_url or "").strip() or None
    yt_dur: float | None = None
    ep_target = data.total_target_duration_seconds
    ep_skip_audio = data.skip_audio
    yt_bg = bool(data.youtube_as_background_music)
    if yt_url:
        from app.api.episodes import _probe_youtube_or_400
        yt_dur = _probe_youtube_or_400(yt_url)
        ep_target = yt_dur
        # bg-music mode keeps narration ON (YT is mixed under it).
        # replace mode (default) forces skip_audio so YT is the only audio.
        if not yt_bg:
            ep_skip_audio = True

    theme = (data.theme_hint or "").strip() or None
    story_text = data.original_story_text or ""

    # Every project gets an Episode 0 mirroring its initial story_text/theme.
    # The multi-episode pipeline resolves the project's active episode and reads
    # story/beats/audio_plan from it.
    db.add(Episode(
        project_id=project.id,
        order_index=0,
        title=data.title or "Episode 1",
        status=EpisodeStatus.draft,
        original_story_text=story_text,
        theme_hint=theme,
        target_duration_seconds=ep_target,
        continue_from_previous=False,
        skip_audio=ep_skip_audio,
        youtube_audio_url=yt_url,
        youtube_audio_duration_seconds=yt_dur,
        youtube_as_background_music=yt_bg,
    ))
    await db.flush()
    await db.refresh(project)

    # Auto-trigger full pipeline if EITHER story text OR a theme hint is given.
    has_seed = bool(story_text.strip()) or bool(theme)
    if has_seed:
        # Scanner gates on project.original_story_text != ''; mirror a stub
        # when only a theme was provided so the scanner picks the project up.
        if not story_text.strip() and theme:
            project.original_story_text = " "
        # Only allow one project pipeline running at a time.
        active_statuses = [
            ProjectStatus.analyzing, ProjectStatus.planning,
            ProjectStatus.prompting, ProjectStatus.audio_planning,
            ProjectStatus.reviewing, ProjectStatus.generating,
            ProjectStatus.stitching,
        ]
        active_count = await db.scalar(
            select(func.count(Project.id)).where(Project.status.in_(active_statuses))
        )
        if active_count and active_count > 0:
            # Another project is running — leave this one in draft, user can trigger later
            pass
        else:
            project.status = ProjectStatus.analyzing
            # Commit BEFORE dispatching so the worker can find the project
            await db.commit()
            await db.refresh(project)
            from app.orchestration.tasks import task_run_full_pipeline
            task_run_full_pipeline.delay(str(project.id))

    return ProjectRead.model_validate(project)


@router.post("/projects/{project_id}/reset", response_model=ProjectRead)
async def reset_project(
    project_id: uuid.UUID, hard: bool = False, db: AsyncSession = Depends(get_db),
):
    """Reset a project back to draft so it can be re-dispatched cleanly.

    Default: only non-terminal episodes are reset (rescues a stuck/failed run).
    ``hard=true``: reset ALL episodes (incl. complete/failed), clear their
    analysis (beat_list_json) so story analysis re-runs, and DELETE all scenes
    so scene planning + prompts regenerate from scratch. Rendered video assets
    are preserved on disk (scene_id is SET NULL, not deleted)."""
    project = await get_or_404(db, Project, project_id, "Project")
    project.status = ProjectStatus.draft
    if hard:
        await db.execute(delete(Scene).where(Scene.project_id == project_id))
        eps = (await db.execute(
            select(Episode).where(Episode.project_id == project_id)
        )).scalars().all()
        for e in eps:
            e.status = EpisodeStatus.draft
            e.beat_list_json = None
    else:
        eps = (await db.execute(
            select(Episode).where(Episode.project_id == project_id,
                                  Episode.status.in_(_ACTIVE_EP_STATUSES))
        )).scalars().all()
        for e in eps:
            e.status = EpisodeStatus.draft
    await db.commit()
    from app.orchestration.locks import clear_all_locks_for_project
    clear_all_locks_for_project(str(project_id))
    await db.refresh(project)
    return await _project_read_with_counts(project, db)


@router.post("/projects/{project_id}/redo-all-prompts")
async def redo_all_prompts(project_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Regenerate analysis + scenes + prompts for EVERY episode, NO rendering.
    Use after a hard reset to rebuild all prompts first; then call /dispatch to
    render (the pipeline skips the already-done prompt stages)."""
    await get_or_404(db, Project, project_id, "Project")
    from app.orchestration.tasks import task_redo_all_prompts
    r = task_redo_all_prompts.delay(str(project_id))
    return {"project_id": str(project_id), "task_id": r.id, "status": "redoing_prompts"}


@router.post("/projects/{project_id}/dispatch", response_model=ProjectRead)
async def dispatch_project(
    project_id: uuid.UUID, gpu: int = 0, db: AsyncSession = Depends(get_db),
):
    """Pin the project to GPU ``gpu`` (its render tasks route to that card) and
    dispatch the full pipeline. Promotes the project to ``analyzing`` first so
    the pipeline doesn't short-circuit."""
    project = await get_or_404(db, Project, project_id, "Project")
    assign_project_gpu(str(project_id), gpu)
    project.status = ProjectStatus.analyzing
    await db.commit()
    await db.refresh(project)
    from app.orchestration.tasks import task_run_full_pipeline
    task_run_full_pipeline.delay(str(project_id))
    return await _project_read_with_counts(project, db)


@router.get("/projects/{project_id}", response_model=ProjectRead)
async def get_project(project_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Get project details."""
    project = await get_or_404(db, Project, project_id, "Project")
    return await _project_read_with_counts(project, db)


@router.put("/projects/{project_id}", response_model=ProjectRead)
async def update_project(
    project_id: uuid.UUID,
    data: ProjectUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update a project."""
    project = await get_or_404(db, Project, project_id, "Project")
    update_data = data.model_dump(exclude_unset=True)
    if "pipeline_profile" in update_data and update_data["pipeline_profile"] not in PROFILES:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown pipeline_profile {update_data['pipeline_profile']!r}. "
                   f"Choices: {sorted(PROFILES)}",
        )
    for key, value in update_data.items():
        setattr(project, key, value)

    await db.flush()
    await db.refresh(project)
    return await _project_read_with_counts(project, db)


@router.delete("/projects/{project_id}", status_code=204)
async def delete_project(project_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Delete a project and all related data immediately using database cascade."""
    await get_or_404(db, Project, project_id, "Project")
    # Execute a direct delete query so the DB handles cascades immediately
    # rather than loading all relations into Python memory
    await db.execute(delete(Project).where(Project.id == project_id))
