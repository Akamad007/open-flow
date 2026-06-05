"""Characters API router."""

import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.character import Character
from app.models.project import Project
from app.schemas.character import CharacterCreate, CharacterRead, CharacterUpdate

router = APIRouter(tags=["characters"])


@router.get("/projects/{project_id}/characters", response_model=List[CharacterRead])
async def list_characters(project_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    stmt = select(Character).where(Character.project_id == project_id).order_by(Character.canonical_name)
    result = await db.execute(stmt)
    return [CharacterRead.model_validate(c) for c in result.scalars().all()]


@router.post("/projects/{project_id}/characters", response_model=CharacterRead, status_code=201)
async def create_character(
    project_id: uuid.UUID,
    data: CharacterCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a character in a project."""
    if not await db.get(Project, project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    character = Character(project_id=project_id, **data.model_dump())
    db.add(character)
    await db.flush()
    await db.refresh(character)
    return CharacterRead.model_validate(character)


@router.get("/characters/{character_id}", response_model=CharacterRead)
async def get_character(character_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    character = await db.get(Character, character_id)
    if not character:
        raise HTTPException(status_code=404, detail="Character not found")
    return CharacterRead.model_validate(character)


@router.put("/characters/{character_id}", response_model=CharacterRead)
async def update_character(
    character_id: uuid.UUID,
    data: CharacterUpdate,
    db: AsyncSession = Depends(get_db),
):
    character = await db.get(Character, character_id)
    if not character:
        raise HTTPException(status_code=404, detail="Character not found")

    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(character, key, value)

    await db.flush()
    await db.refresh(character)
    return CharacterRead.model_validate(character)


@router.delete("/characters/{character_id}", status_code=204)
async def delete_character(character_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Delete a character."""
    character = await db.get(Character, character_id)
    if not character:
        raise HTTPException(status_code=404, detail="Character not found")
    await db.delete(character)
