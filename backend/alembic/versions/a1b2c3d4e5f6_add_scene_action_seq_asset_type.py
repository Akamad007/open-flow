"""add_scene_action_seq_asset_type

Revision ID: a1b2c3d4e5f6
Revises: 0e599f8e64f9
Create Date: 2026-05-04 20:30:00.000000
"""

from typing import Sequence, Union

from alembic import op


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '0e599f8e64f9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE assettype ADD VALUE IF NOT EXISTS 'scene_action_seq'")


def downgrade() -> None:
    pass
