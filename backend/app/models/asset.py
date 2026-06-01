"""Asset ORM model — tracks all generated media files."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class AssetType(str, enum.Enum):
    scene_video = "scene_video"
    full_story_audio = "full_story_audio"
    final_render = "final_render"
    character_ref = "character_ref"    # SD 3.5 character portrait
    background_ref = "background_ref"  # SD 3.5 background plate
    scene_ref = "scene_ref"            # Composited scene reference
    scene_action = "scene_action"      # SD 3.5 action still — character doing scene-specific action
    scene_action_2 = "scene_action_2"  # SD 3.5 secondary action still (legacy — 2-image system)
    scene_action_seq = "scene_action_seq"  # Per-second sequenced action stills (N per scene)
    product_ref = "product_ref"        # SD 3.5 product hero shot (bg-removed)



class AssetStatus(str, enum.Enum):
    pending = "pending"
    generating = "generating"
    complete = "complete"
    failed = "failed"


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    episode_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("episodes.id", ondelete="CASCADE"), nullable=True, index=True
    )
    scene_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scenes.id", ondelete="SET NULL"), nullable=True, index=True
    )
    asset_type: Mapped[AssetType] = mapped_column(Enum(AssetType), nullable=False)
    file_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    generation_provider: Mapped[str | None] = mapped_column(String(200), nullable=True)
    generation_params_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[AssetStatus] = mapped_column(
        Enum(AssetStatus), nullable=False, default=AssetStatus.pending
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    project = relationship("Project", back_populates="assets")
    scene = relationship("Scene", back_populates="assets")

    def __repr__(self) -> str:
        return f"<Asset {self.id} type={self.asset_type.value} status={self.status.value}>"
