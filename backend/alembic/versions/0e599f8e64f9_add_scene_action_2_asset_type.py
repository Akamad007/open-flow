"""add_scene_action_2_asset_type

Revision ID: 0e599f8e64f9
Revises: 552670812883
Create Date: 2026-05-02 13:43:49.312792
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0e599f8e64f9'
down_revision: Union[str, None] = '552670812883'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # PostgreSQL enums require ALTER TYPE ... ADD VALUE (not detected by autogenerate)
    op.execute("ALTER TYPE assettype ADD VALUE IF NOT EXISTS 'scene_action_2'")


def downgrade() -> None:
    # Postgres does not support removing enum values — downgrade is a no-op
    pass
