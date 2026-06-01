"""RenderJob ORM model — tracks async job execution."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class JobType(str, enum.Enum):
    story_analysis = "story_analysis"
    scene_planning = "scene_planning"
    prompt_generation = "prompt_generation"
    audio_planning = "audio_planning"
    consistency_review = "consistency_review"
    image_pregen = "image_pregen"          # SD 3.5 character/background/scene ref generation
    video_generation = "video_generation"
    audio_generation = "audio_generation"
    stitching = "stitching"
    full_pipeline = "full_pipeline"        # top-level workflow job


class JobStatus(str, enum.Enum):
    queued = "queued"
    running = "running"
    complete = "complete"
    failed = "failed"
    cancelled = "cancelled"


class RenderJob(Base):
    __tablename__ = "render_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    job_type: Mapped[JobType] = mapped_column(Enum(JobType), nullable=False)
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus), nullable=False, default=JobStatus.queued
    )
    payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    celery_task_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    job_type_detail: Mapped[str | None] = mapped_column(String(200), nullable=True)  # e.g. "scene:{uuid}"
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    project = relationship("Project", back_populates="render_jobs")

    def __repr__(self) -> str:
        return f"<RenderJob {self.id} type={self.job_type.value} status={self.status.value}>"
