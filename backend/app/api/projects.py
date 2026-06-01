"""Projects API router — CRUD operations for projects."""

import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.episode import Episode, EpisodeStatus
from app.models.project import Project, ProjectStatus
from app.models.scene import Scene
from app.orchestration.profiles import DEFAULT_PROFILE, PROFILES, list_profiles
from app.schemas.project import ProjectCreate, ProjectList, ProjectRead, ProjectUpdate

router = APIRouter(tags=["projects"])


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


@router.get("/projects/{project_id}", response_model=ProjectRead)
async def get_project(project_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Get project details."""
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Get counts
    scene_count = await db.scalar(
        select(func.count(Scene.id)).where(Scene.project_id == project_id)
    )
    result = ProjectRead.model_validate(project)
    result.scene_count = scene_count or 0
    return result


@router.put("/projects/{project_id}", response_model=ProjectRead)
async def update_project(
    project_id: uuid.UUID,
    data: ProjectUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update a project."""
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

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
    return ProjectRead.model_validate(project)


@router.delete("/projects/{project_id}", status_code=204)
async def delete_project(project_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Delete a project and all related data immediately using database cascade."""
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
        
    # Execute a direct delete query so the DB handles cascades immediately
    # rather than loading all relations into Python memory
    await db.execute(delete(Project).where(Project.id == project_id))
