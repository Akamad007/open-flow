"""YouTubeUpload ORM model — one row per upload attempt of a final_render to YouTube."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, Float, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class YouTubePrivacy(str, enum.Enum):
    private = "private"
    unlisted = "unlisted"
    public = "public"


class YouTubeUploadStatus(str, enum.Enum):
    queued = "queued"
    uploading = "uploading"
    complete = "complete"
    failed = "failed"


class YouTubeUpload(Base):
    __tablename__ = "youtube_uploads"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    episode_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("episodes.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    asset_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("assets.id", ondelete="SET NULL"), nullable=True,
    )
    title: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    privacy: Mapped[YouTubePrivacy] = mapped_column(
        Enum(YouTubePrivacy), nullable=False, default=YouTubePrivacy.private,
    )
    status: Mapped[YouTubeUploadStatus] = mapped_column(
        Enum(YouTubeUploadStatus), nullable=False, default=YouTubeUploadStatus.queued,
    )
    youtube_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    progress: Mapped[float | None] = mapped_column(Float, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @property
    def youtube_url(self) -> str | None:
        return f"https://youtu.be/{self.youtube_id}" if self.youtube_id else None
