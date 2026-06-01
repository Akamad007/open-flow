"""Project ORM model."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, Float, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ProjectStatus(str, enum.Enum):
    draft = "draft"
    analyzing = "analyzing"
    planning = "planning"
    prompting = "prompting"
    audio_planning = "audio_planning"
    reviewing = "reviewing"
    image_pregen = "image_pregen"
    generating = "generating"
    stitching = "stitching"
    complete = "complete"
    failed = "failed"


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False, default="Untitled Project")
    original_story_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[ProjectStatus] = mapped_column(
        Enum(ProjectStatus), nullable=False, default=ProjectStatus.draft
    )
    total_target_duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    final_audio_duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Story analysis results stored as JSON text
    story_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    beat_list_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    pacing_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    style_lock: Mapped[str | None] = mapped_column(Text, nullable=True)

    pipeline_profile: Mapped[str] = mapped_column(
        String(64), nullable=False, default="ltx_text_only", server_default="ltx_text_only"
    )
    final_evaluation_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    characters = relationship("Character", back_populates="project", cascade="all, delete-orphan")
    locations = relationship("Location", back_populates="project", cascade="all, delete-orphan")
    products = relationship("Product", back_populates="project", cascade="all, delete-orphan")
    episodes = relationship(
        "Episode", back_populates="project", cascade="all, delete-orphan",
        order_by="Episode.order_index",
    )
    scenes = relationship(
        "Scene", back_populates="project", cascade="all, delete-orphan",
        order_by="Scene.order_index"
    )
    audio_plans = relationship(
        "AudioPlan", back_populates="project", cascade="all, delete-orphan",
    )
    assets = relationship("Asset", back_populates="project", cascade="all, delete-orphan")
    render_jobs = relationship("RenderJob", back_populates="project", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Project {self.id} title={self.title!r} status={self.status.value}>"
