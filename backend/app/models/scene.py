"""Scene ORM model with many-to-many character association."""

import enum
import uuid

from sqlalchemy import Boolean, Column, Enum, Float, ForeignKey, Integer, String, Table, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

# Many-to-many: scenes <-> characters
scene_characters = Table(
    "scene_characters",
    Base.metadata,
    Column("scene_id", UUID(as_uuid=True), ForeignKey("scenes.id", ondelete="CASCADE"), primary_key=True),
    Column("character_id", UUID(as_uuid=True), ForeignKey("characters.id", ondelete="CASCADE"), primary_key=True),
)

# Many-to-many: scenes <-> products. `product_role` lets one scene express
# the product as hero / holding / background; `shows_product` lets a scene
# explicitly opt out (e.g. atmospheric establishing shot).
scene_products = Table(
    "scene_products",
    Base.metadata,
    Column("scene_id", UUID(as_uuid=True), ForeignKey("scenes.id", ondelete="CASCADE"), primary_key=True),
    Column("product_id", UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), primary_key=True),
    Column("product_role", String(20), nullable=False, default="holding"),
    Column("shows_product", Boolean, nullable=False, default=True),
)


class SceneStatus(str, enum.Enum):
    planned = "planned"
    prompted = "prompted"
    approved = "approved"
    generating = "generating"
    generated = "generated"
    failed = "failed"


class Scene(Base):
    __tablename__ = "scenes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    episode_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("episodes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=4.0)
    scene_purpose: Mapped[str | None] = mapped_column(Text, nullable=True)
    visual_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    audio_alignment_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    continuity_from_previous: Mapped[str | None] = mapped_column(Text, nullable=True)
    continuity_to_next: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_audio_segment_start: Mapped[float | None] = mapped_column(Float, nullable=True)
    target_audio_segment_end: Mapped[float | None] = mapped_column(Float, nullable=True)
    location_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("locations.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[SceneStatus] = mapped_column(
        Enum(SceneStatus), nullable=False, default=SceneStatus.planned
    )
    locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    skip_last_frame_chain: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    scene_ref_image_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    evaluation_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    project = relationship("Project", back_populates="scenes")
    episode = relationship("Episode", back_populates="scenes")
    prompt = relationship(
        "ScenePrompt", back_populates="scene", uselist=False, cascade="all, delete-orphan"
    )
    characters = relationship("Character", secondary=scene_characters, lazy="selectin")
    products = relationship("Product", secondary=scene_products, lazy="selectin")
    location = relationship("Location", lazy="selectin")
    assets = relationship("Asset", back_populates="scene", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Scene {self.id} order={self.order_index} status={self.status.value}>"
