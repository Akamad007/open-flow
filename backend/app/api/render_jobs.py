"""Render Jobs API router."""

import uuid
from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api._common import NOT_FOUND_RESPONSE, get_or_404
from app.database import get_db
from app.models.render_job import RenderJob
from app.schemas.render_job import RenderJobRead

router = APIRouter(tags=["render_jobs"], responses=NOT_FOUND_RESPONSE)


@router.get("/projects/{project_id}/jobs", response_model=List[RenderJobRead])
async def list_jobs(project_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    stmt = (
        select(RenderJob)
        .where(RenderJob.project_id == project_id)
        .order_by(RenderJob.created_at.asc())   # pipeline execution order
    )
    result = await db.execute(stmt)
    return [RenderJobRead.model_validate(j) for j in result.scalars().all()]


@router.get("/jobs/{job_id}", response_model=RenderJobRead)
async def get_job(job_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    job = await get_or_404(db, RenderJob, job_id, "Job")
    return RenderJobRead.model_validate(job)
