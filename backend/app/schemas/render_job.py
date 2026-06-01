"""RenderJob Pydantic schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from app.models.render_job import JobStatus, JobType


class RenderJobRead(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    job_type: JobType
    status: JobStatus
    payload_json: Optional[str] = None
    result_json: Optional[str] = None
    error_text: Optional[str] = None
    celery_task_id: Optional[str] = None
    job_type_detail: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
