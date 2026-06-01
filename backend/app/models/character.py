"""Character ORM model."""

import uuid

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Character(Base):
    __tablename__ = "characters"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    canonical_name: Mapped[str] = mapped_column(String(300), nullable=False)
    # human | mascot | creature | object — controls portrait template choice.
    # Non-human kinds skip human-anatomy guards and the "wearing {outfit}" splice.
    character_kind: Mapped[str | None] = mapped_column(String(32), nullable=True, default="human")
    physical_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    clothing_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    personality_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    voice_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    continuity_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    reference_image_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    # Relationships
    project = relationship("Project", back_populates="characters")

    def __repr__(self) -> str:
        return f"<Character {self.id} name={self.canonical_name!r}>"
