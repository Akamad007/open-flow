"""add lora_plan_json to scene_prompts

Revision ID: m3n4o5p6q7r8
Revises: l2m3n4o5p6q7
Create Date: 2026-05-26 18:30:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "m3n4o5p6q7r8"
down_revision: Union[str, None] = "l2m3n4o5p6q7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "scene_prompts",
        sa.Column("lora_plan_json", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("scene_prompts", "lora_plan_json")
