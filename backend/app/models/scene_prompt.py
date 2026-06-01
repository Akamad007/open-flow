"""ScenePrompt ORM model — the cinematic generation prompt for a scene."""

import uuid

from sqlalchemy import Boolean, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ScenePrompt(Base):
    __tablename__ = "scene_prompts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    scene_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scenes.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    video_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    negative_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    style_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    camera_plan: Mapped[str | None] = mapped_column(Text, nullable=True)
    subject_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    environment_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    action_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    continuity_guardrails: Mapped[str | None] = mapped_column(Text, nullable=True)
    scene_breakdown: Mapped[str | None] = mapped_column(Text, nullable=True)  # per-second beat plan
    camera_angle: Mapped[str | None] = mapped_column(Text, nullable=True)     # explicit angle label
    critic_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # JSON string: {"loras": [{"id": "...", "weight": 0.5}, ...], "shot_type": "wide", "rationale": "..."}
    lora_plan_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Relationships
    scene = relationship("Scene", back_populates="prompt")

    def __repr__(self) -> str:
        return f"<ScenePrompt {self.id} scene_id={self.scene_id} approved={self.approved}>"
