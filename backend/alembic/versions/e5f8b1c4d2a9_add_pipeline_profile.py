"""add_pipeline_profile

Revision ID: e5f8b1c4d2a9
Revises: d4f7a9c1b3e2
Create Date: 2026-05-08 13:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e5f8b1c4d2a9"
down_revision: Union[str, None] = "d4f7a9c1b3e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column(
            "pipeline_profile",
            sa.String(length=64),
            nullable=False,
            server_default="ltx_text_only",
        ),
    )


def downgrade() -> None:
    op.drop_column("projects", "pipeline_profile")
