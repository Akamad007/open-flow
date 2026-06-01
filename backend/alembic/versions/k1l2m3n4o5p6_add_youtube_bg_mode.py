"""add_youtube_as_background_music_to_episodes

Revision ID: k1l2m3n4o5p6
Revises: j0k1l2m3n4o5
Create Date: 2026-05-25 16:30:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "k1l2m3n4o5p6"
down_revision: Union[str, None] = "j0k1l2m3n4o5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("episodes", sa.Column(
        "youtube_as_background_music", sa.Boolean,
        nullable=False, server_default=sa.false(),
    ))


def downgrade() -> None:
    op.drop_column("episodes", "youtube_as_background_music")
