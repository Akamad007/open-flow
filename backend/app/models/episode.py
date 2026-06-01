"""Episode ORM model — a self-contained video inside a project."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class EpisodeStatus(str, enum.Enum):
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


class Episode(Base):
    __tablename__ = "episodes"
    __table_args__ = (UniqueConstraint("project_id", "order_index", name="uq_episode_project_order"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    title: Mapped[str] = mapped_column(String(500), nullable=False, default="Episode 1")
    status: Mapped[EpisodeStatus] = mapped_column(
        Enum(EpisodeStatus, name="episodestatus"), nullable=False, default=EpisodeStatus.draft,
    )
    theme_hint: Mapped[str | None] = mapped_column(Text, nullable=True)
    original_story_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    target_duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    final_audio_duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)

    story_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    beat_list_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    pacing_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    style_lock: Mapped[str | None] = mapped_column(Text, nullable=True)
    final_evaluation_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    continue_from_previous: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # True = every scene uses scene 0's first frame as I2V condition (no chain drift).
    # False (default) = each scene chains off the previous scene's last frame.
    anchor_first_frame: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    skip_audio: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    youtube_audio_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    youtube_audio_duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    # False (default) = YT track REPLACES narration. True = mix YT under narration as bg music.
    youtube_as_background_music: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    final_video_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
    )

    project = relationship("Project", back_populates="episodes")
    scenes = relationship(
        "Scene", back_populates="episode", cascade="all, delete-orphan",
        order_by="Scene.order_index",
    )
    audio_plan = relationship(
        "AudioPlan", back_populates="episode", uselist=False, cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Episode {self.id} order={self.order_index} status={self.status.value}>"
