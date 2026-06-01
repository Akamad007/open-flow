"""Locations API router."""

import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.location import Location
from app.schemas.location import LocationRead, LocationUpdate

router = APIRouter(tags=["locations"])


@router.get("/projects/{project_id}/locations", response_model=List[LocationRead])
async def list_locations(project_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    stmt = select(Location).where(Location.project_id == project_id).order_by(Location.name)
    result = await db.execute(stmt)
    return [LocationRead.model_validate(loc) for loc in result.scalars().all()]


@router.get("/locations/{location_id}", response_model=LocationRead)
async def get_location(location_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    location = await db.get(Location, location_id)
    if not location:
        raise HTTPException(status_code=404, detail="Location not found")
    return LocationRead.model_validate(location)


@router.put("/locations/{location_id}", response_model=LocationRead)
async def update_location(
    location_id: uuid.UUID,
    data: LocationUpdate,
    db: AsyncSession = Depends(get_db),
):
    location = await db.get(Location, location_id)
    if not location:
        raise HTTPException(status_code=404, detail="Location not found")

    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(location, key, value)

    await db.flush()
    await db.refresh(location)
    return LocationRead.model_validate(location)
