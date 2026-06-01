"""add_evaluation_columns

Revision ID: f1a2b3c4d5e6
Revises: e5f8b1c4d2a9
Create Date: 2026-05-17 23:30:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, None] = "e5f8b1c4d2a9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("scenes", sa.Column("evaluation_json", sa.Text(), nullable=True))
    op.add_column("projects", sa.Column("final_evaluation_json", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("projects", "final_evaluation_json")
    op.drop_column("scenes", "evaluation_json")
