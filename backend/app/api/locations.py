"""Locations API router."""

import uuid
from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api._common import NOT_FOUND_RESPONSE, get_or_404
from app.database import get_db
from app.models.location import Location
from app.models.project import Project
from app.schemas.location import LocationCreate, LocationRead, LocationUpdate

router = APIRouter(tags=["locations"], responses=NOT_FOUND_RESPONSE)


@router.get("/projects/{project_id}/locations", response_model=List[LocationRead])
async def list_locations(project_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    stmt = select(Location).where(Location.project_id == project_id).order_by(Location.name)
    result = await db.execute(stmt)
    return [LocationRead.model_validate(loc) for loc in result.scalars().all()]


@router.post("/projects/{project_id}/locations", response_model=LocationRead, status_code=201)
async def create_location(
    project_id: uuid.UUID,
    data: LocationCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a location in a project."""
    await get_or_404(db, Project, project_id, "Project")
    location = Location(project_id=project_id, **data.model_dump())
    db.add(location)
    await db.flush()
    await db.refresh(location)
    return LocationRead.model_validate(location)


@router.get("/locations/{location_id}", response_model=LocationRead)
async def get_location(location_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    location = await get_or_404(db, Location, location_id, "Location")
    return LocationRead.model_validate(location)


@router.put("/locations/{location_id}", response_model=LocationRead)
async def update_location(
    location_id: uuid.UUID,
    data: LocationUpdate,
    db: AsyncSession = Depends(get_db),
):
    location = await get_or_404(db, Location, location_id, "Location")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(location, key, value)

    await db.flush()
    await db.refresh(location)
    return LocationRead.model_validate(location)


@router.delete("/locations/{location_id}", status_code=204)
async def delete_location(location_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Delete a location."""
    location = await get_or_404(db, Location, location_id, "Location")
    await db.delete(location)
