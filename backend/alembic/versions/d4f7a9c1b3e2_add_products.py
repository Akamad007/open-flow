"""add_products

Adds the `products` table (1:N projects→products) and the `scene_products`
M2M (with product_role + shows_product on the join). Also adds the
`product_ref` value to the assettype enum.

Revision ID: d4f7a9c1b3e2
Revises: b2c3d4e5f6a7
Create Date: 2026-05-06 11:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "d4f7a9c1b3e2"
down_revision: Union[str, None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "products",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("canonical_name", sa.String(length=300), nullable=False),
        sa.Column("category", sa.String(length=50), nullable=True),
        sa.Column("physical_description", sa.Text(), nullable=True),
        sa.Column("brand_marks", sa.Text(), nullable=True),
        sa.Column("color_palette", sa.Text(), nullable=True),
        sa.Column("hero_angle", sa.Text(), nullable=True),
        sa.Column("user_uploaded_path", sa.String(length=1000), nullable=True),
        sa.Column("reference_image_path", sa.String(length=1000), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_products_project_id", "products", ["project_id"])

    op.create_table(
        "scene_products",
        sa.Column("scene_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "product_role",
            sa.String(length=20),
            nullable=False,
            server_default="holding",
        ),
        sa.Column(
            "shows_product",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.ForeignKeyConstraint(["scene_id"], ["scenes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("scene_id", "product_id"),
    )

    op.execute("ALTER TYPE assettype ADD VALUE IF NOT EXISTS 'product_ref'")


def downgrade() -> None:
    op.drop_table("scene_products")
    op.drop_index("ix_products_project_id", table_name="products")
    op.drop_table("products")
    # Postgres has no clean "remove enum value"; leaving 'product_ref' in
    # the type is harmless and keeps the downgrade idempotent.
