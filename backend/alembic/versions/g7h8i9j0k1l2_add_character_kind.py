"""add_character_kind

Revision ID: g7h8i9j0k1l2
Revises: f1a2b3c4d5e6
Create Date: 2026-05-23 11:40:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "g7h8i9j0k1l2"
down_revision: Union[str, None] = "f1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "characters",
        sa.Column("character_kind", sa.String(length=32), nullable=True, server_default="human"),
    )
    op.execute("UPDATE characters SET character_kind = 'human' WHERE character_kind IS NULL")


def downgrade() -> None:
    op.drop_column("characters", "character_kind")
