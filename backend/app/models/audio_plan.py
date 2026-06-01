"""AudioPlan ORM model — full-story continuous audio plan."""

import uuid

from sqlalchemy import Boolean, Float, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class AudioPlan(Base):
    __tablename__ = "audio_plans"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    episode_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("episodes.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    full_story_narration_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    full_story_dialogue_plan: Mapped[str | None] = mapped_column(Text, nullable=True)
    full_story_audio_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    ambience_progression_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    sound_transition_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    total_estimated_audio_duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    # JSON serialized timing map: list of {scene_id, audio_segment_start, audio_segment_end, ...}
    timing_map_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Relationships
    project = relationship("Project", back_populates="audio_plans")
    episode = relationship("Episode", back_populates="audio_plan")

    def __repr__(self) -> str:
        return f"<AudioPlan {self.id} project_id={self.project_id}>"
