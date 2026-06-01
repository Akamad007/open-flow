"""add_youtube_uploads_table

Revision ID: l2m3n4o5p6q7
Revises: k1l2m3n4o5p6
Create Date: 2026-05-26 14:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "l2m3n4o5p6q7"
down_revision: Union[str, None] = "k1l2m3n4o5p6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    privacy_enum = sa.Enum("private", "unlisted", "public", name="youtubeprivacy")
    status_enum = sa.Enum("queued", "uploading", "complete", "failed", name="youtubeuploadstatus")
    op.create_table(
        "youtube_uploads",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("episode_id", sa.dialects.postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("episodes.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("asset_id", sa.dialects.postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("assets.id", ondelete="SET NULL"), nullable=True),
        sa.Column("title", sa.String(100), nullable=False),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("privacy", privacy_enum, nullable=False, server_default="private"),
        sa.Column("status", status_enum, nullable=False, server_default="queued"),
        sa.Column("youtube_id", sa.String(64), nullable=True),
        sa.Column("progress", sa.Float, nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("youtube_uploads")
    op.execute("DROP TYPE IF EXISTS youtubeuploadstatus")
    op.execute("DROP TYPE IF EXISTS youtubeprivacy")
