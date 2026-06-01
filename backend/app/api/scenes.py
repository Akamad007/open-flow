"""Scenes API router."""

import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.scene import Scene
from app.models.scene_prompt import ScenePrompt
from app.schemas.scene import SceneCreate, SceneRead, SceneReorder, SceneUpdate
from app.schemas.scene_prompt import ScenePromptUpdate

router = APIRouter(tags=["scenes"])


@router.get("/projects/{project_id}/scenes", response_model=List[SceneRead])
async def list_scenes(project_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """List all scenes for a project, ordered by order_index."""
    stmt = (
        select(Scene)
        .where(Scene.project_id == project_id)
        .options(selectinload(Scene.prompt), selectinload(Scene.characters))
        .order_by(Scene.order_index)
    )
    result = await db.execute(stmt)
    scenes = result.scalars().all()
    return [SceneRead.model_validate(s) for s in scenes]


@router.get("/scenes/{scene_id}", response_model=SceneRead)
async def get_scene(scene_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Get scene details."""
    stmt = (
        select(Scene)
        .where(Scene.id == scene_id)
        .options(selectinload(Scene.prompt), selectinload(Scene.characters))
    )
    result = await db.execute(stmt)
    scene = result.scalar_one_or_none()
    if not scene:
        raise HTTPException(status_code=404, detail="Scene not found")
    return SceneRead.model_validate(scene)


@router.put("/scenes/{scene_id}", response_model=SceneRead)
async def update_scene(
    scene_id: uuid.UUID,
    data: SceneUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update a scene."""
    stmt = (
        select(Scene)
        .where(Scene.id == scene_id)
        .options(selectinload(Scene.prompt), selectinload(Scene.characters))
    )
    result = await db.execute(stmt)
    scene = result.scalar_one_or_none()
    if not scene:
        raise HTTPException(status_code=404, detail="Scene not found")

    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(scene, key, value)

    await db.flush()
    await db.refresh(scene)
    return SceneRead.model_validate(scene)


@router.put("/scenes/{scene_id}/prompt", response_model=SceneRead)
async def update_scene_prompt(
    scene_id: uuid.UUID,
    data: ScenePromptUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update the prompt for a scene."""
    stmt = (
        select(Scene)
        .where(Scene.id == scene_id)
        .options(selectinload(Scene.prompt), selectinload(Scene.characters))
    )
    result = await db.execute(stmt)
    scene = result.scalar_one_or_none()
    if not scene:
        raise HTTPException(status_code=404, detail="Scene not found")

    if not scene.prompt:
        scene.prompt = ScenePrompt(scene_id=scene_id)
        db.add(scene.prompt)

    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(scene.prompt, key, value)

    await db.flush()
    await db.refresh(scene)
    return SceneRead.model_validate(scene)


@router.post("/projects/{project_id}/scenes/reorder", response_model=List[SceneRead])
async def reorder_scenes(
    project_id: uuid.UUID,
    data: SceneReorder,
    db: AsyncSession = Depends(get_db),
):
    """Reorder scenes by providing the scene_ids in desired order."""
    for idx, scene_id in enumerate(data.scene_ids):
        stmt = select(Scene).where(Scene.id == scene_id, Scene.project_id == project_id)
        result = await db.execute(stmt)
        scene = result.scalar_one_or_none()
        if scene:
            scene.order_index = idx

    await db.flush()

    # Return updated list
    stmt = (
        select(Scene)
        .where(Scene.project_id == project_id)
        .options(selectinload(Scene.prompt), selectinload(Scene.characters))
        .order_by(Scene.order_index)
    )
    result = await db.execute(stmt)
    scenes = result.scalars().all()
    return [SceneRead.model_validate(s) for s in scenes]
