"""add_youtube_audio_url_to_episodes

Revision ID: j0k1l2m3n4o5
Revises: i9j0k1l2m3n4
Create Date: 2026-05-25 13:30:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "j0k1l2m3n4o5"
down_revision: Union[str, None] = "i9j0k1l2m3n4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("episodes",
        sa.Column("youtube_audio_url", sa.String(length=1000), nullable=True))
    op.add_column("episodes",
        sa.Column("youtube_audio_duration_seconds", sa.Float, nullable=True))


def downgrade() -> None:
    op.drop_column("episodes", "youtube_audio_duration_seconds")
    op.drop_column("episodes", "youtube_audio_url")
