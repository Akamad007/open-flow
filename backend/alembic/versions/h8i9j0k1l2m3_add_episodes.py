"""add_episodes_table_and_backfill

Revision ID: h8i9j0k1l2m3
Revises: g7h8i9j0k1l2
Create Date: 2026-05-24 23:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "h8i9j0k1l2m3"
down_revision: Union[str, None] = "g7h8i9j0k1l2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


EPISODE_STATUS_VALUES = (
    "draft", "analyzing", "planning", "prompting", "audio_planning",
    "reviewing", "image_pregen", "generating", "stitching", "complete", "failed",
)


def upgrade() -> None:
    op.create_table(
        "episodes",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", sa.dialects.postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("order_index", sa.Integer, nullable=False, server_default="0"),
        sa.Column("title", sa.String(length=500), nullable=False, server_default="Episode 1"),
        sa.Column("status", sa.Enum(*EPISODE_STATUS_VALUES, name="episodestatus"),
                  nullable=False, server_default="draft"),
        sa.Column("theme_hint", sa.Text, nullable=True),
        sa.Column("original_story_text", sa.Text, nullable=False, server_default=""),
        sa.Column("target_duration_seconds", sa.Float, nullable=True),
        sa.Column("final_audio_duration_seconds", sa.Float, nullable=True),
        sa.Column("story_summary", sa.Text, nullable=True),
        sa.Column("beat_list_json", sa.Text, nullable=True),
        sa.Column("pacing_notes", sa.Text, nullable=True),
        sa.Column("style_lock", sa.Text, nullable=True),
        sa.Column("final_evaluation_json", sa.Text, nullable=True),
        sa.Column("continue_from_previous", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("final_video_path", sa.String(length=1000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("project_id", "order_index", name="uq_episode_project_order"),
    )

    op.add_column("scenes",
        sa.Column("episode_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("audio_plans",
        sa.Column("episode_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("assets",
        sa.Column("episode_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True))

    op.execute("""
        INSERT INTO episodes (
          id, project_id, order_index, title, status, original_story_text,
          target_duration_seconds, final_audio_duration_seconds,
          story_summary, beat_list_json, pacing_notes, style_lock,
          final_evaluation_json, continue_from_previous, created_at, updated_at
        )
        SELECT
          gen_random_uuid(), p.id, 0,
          COALESCE(NULLIF(p.title,''), 'Episode 1'),
          p.status::text::episodestatus,
          COALESCE(p.original_story_text, ''),
          p.total_target_duration_seconds,
          p.final_audio_duration_seconds,
          p.story_summary, p.beat_list_json, p.pacing_notes, p.style_lock,
          p.final_evaluation_json, true,
          p.created_at, p.updated_at
        FROM projects p
    """)

    op.execute("""
        UPDATE scenes SET episode_id = e.id
        FROM episodes e
        WHERE scenes.project_id = e.project_id AND e.order_index = 0
    """)
    op.execute("""
        UPDATE audio_plans SET episode_id = e.id
        FROM episodes e
        WHERE audio_plans.project_id = e.project_id AND e.order_index = 0
    """)
    op.execute("""
        UPDATE assets SET episode_id = e.id
        FROM episodes e
        WHERE assets.project_id = e.project_id
          AND e.order_index = 0
          AND assets.asset_type IN ('full_story_audio','final_render')
    """)

    op.alter_column("scenes", "episode_id", nullable=False)

    op.create_index("ix_scenes_episode_id", "scenes", ["episode_id"])
    op.create_index("ix_assets_episode_id", "assets", ["episode_id"])
    op.create_index("ix_audio_plans_episode_id", "audio_plans", ["episode_id"])

    op.create_foreign_key("fk_scenes_episode_id", "scenes", "episodes",
                          ["episode_id"], ["id"], ondelete="CASCADE")
    op.create_foreign_key("fk_audio_plans_episode_id", "audio_plans", "episodes",
                          ["episode_id"], ["id"], ondelete="CASCADE")
    op.create_foreign_key("fk_assets_episode_id", "assets", "episodes",
                          ["episode_id"], ["id"], ondelete="CASCADE")

    op.drop_index("ix_audio_plans_project_id", "audio_plans")
    op.create_index("ix_audio_plans_project_id", "audio_plans", ["project_id"])
    op.create_unique_constraint("uq_audio_plans_episode_id", "audio_plans", ["episode_id"])


def downgrade() -> None:
    op.drop_constraint("uq_audio_plans_episode_id", "audio_plans", type_="unique")
    op.drop_index("ix_audio_plans_project_id", "audio_plans")
    op.create_index("ix_audio_plans_project_id", "audio_plans", ["project_id"], unique=True)
    op.drop_constraint("fk_assets_episode_id", "assets", type_="foreignkey")
    op.drop_constraint("fk_audio_plans_episode_id", "audio_plans", type_="foreignkey")
    op.drop_constraint("fk_scenes_episode_id", "scenes", type_="foreignkey")
    op.drop_index("ix_audio_plans_episode_id", "audio_plans")
    op.drop_index("ix_assets_episode_id", "assets")
    op.drop_index("ix_scenes_episode_id", "scenes")
    op.drop_column("assets", "episode_id")
    op.drop_column("audio_plans", "episode_id")
    op.drop_column("scenes", "episode_id")
    op.drop_table("episodes")
    op.execute("DROP TYPE episodestatus")
