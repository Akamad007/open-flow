"""initial schema

Revision ID: 001
Revises: 
Create Date: 2026-04-29
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Projects
    op.create_table(
        "projects",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("title", sa.String(500), nullable=False, server_default="Untitled Project"),
        sa.Column("original_story_text", sa.Text, nullable=False, server_default=""),
        sa.Column("status", sa.Enum(
            "draft", "analyzing", "planning", "prompting", "audio_planning",
            "reviewing", "generating", "stitching", "complete", "failed",
            name="projectstatus",
        ), nullable=False, server_default="draft"),
        sa.Column("total_target_duration_seconds", sa.Float, nullable=True),
        sa.Column("final_audio_duration_seconds", sa.Float, nullable=True),
        sa.Column("story_summary", sa.Text, nullable=True),
        sa.Column("beat_list_json", sa.Text, nullable=True),
        sa.Column("pacing_notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Characters
    op.create_table(
        "characters",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("canonical_name", sa.String(300), nullable=False),
        sa.Column("physical_description", sa.Text, nullable=True),
        sa.Column("clothing_description", sa.Text, nullable=True),
        sa.Column("personality_notes", sa.Text, nullable=True),
        sa.Column("voice_notes", sa.Text, nullable=True),
        sa.Column("continuity_notes", sa.Text, nullable=True),
    )
    op.create_index("ix_characters_project_id", "characters", ["project_id"])

    # Locations
    op.create_table(
        "locations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("continuity_notes", sa.Text, nullable=True),
    )
    op.create_index("ix_locations_project_id", "locations", ["project_id"])

    # Scenes
    op.create_table(
        "scenes",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("order_index", sa.Integer, nullable=False, server_default="0"),
        sa.Column("source_excerpt", sa.Text, nullable=True),
        sa.Column("duration_seconds", sa.Float, nullable=False, server_default="4.0"),
        sa.Column("scene_purpose", sa.Text, nullable=True),
        sa.Column("visual_summary", sa.Text, nullable=True),
        sa.Column("audio_alignment_notes", sa.Text, nullable=True),
        sa.Column("continuity_from_previous", sa.Text, nullable=True),
        sa.Column("continuity_to_next", sa.Text, nullable=True),
        sa.Column("target_audio_segment_start", sa.Float, nullable=True),
        sa.Column("target_audio_segment_end", sa.Float, nullable=True),
        sa.Column("location_id", UUID(as_uuid=True), sa.ForeignKey("locations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", sa.Enum(
            "planned", "prompted", "approved", "generating", "generated", "failed",
            name="scenestatus",
        ), nullable=False, server_default="planned"),
        sa.Column("locked", sa.Boolean, nullable=False, server_default="false"),
    )
    op.create_index("ix_scenes_project_id", "scenes", ["project_id"])

    # Scene-Character association
    op.create_table(
        "scene_characters",
        sa.Column("scene_id", UUID(as_uuid=True), sa.ForeignKey("scenes.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("character_id", UUID(as_uuid=True), sa.ForeignKey("characters.id", ondelete="CASCADE"), primary_key=True),
    )

    # Scene Prompts
    op.create_table(
        "scene_prompts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("scene_id", UUID(as_uuid=True), sa.ForeignKey("scenes.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("video_prompt", sa.Text, nullable=True),
        sa.Column("negative_prompt", sa.Text, nullable=True),
        sa.Column("style_notes", sa.Text, nullable=True),
        sa.Column("camera_plan", sa.Text, nullable=True),
        sa.Column("subject_description", sa.Text, nullable=True),
        sa.Column("environment_description", sa.Text, nullable=True),
        sa.Column("action_description", sa.Text, nullable=True),
        sa.Column("continuity_guardrails", sa.Text, nullable=True),
        sa.Column("critic_notes", sa.Text, nullable=True),
        sa.Column("approved", sa.Boolean, nullable=False, server_default="false"),
    )
    op.create_index("ix_scene_prompts_scene_id", "scene_prompts", ["scene_id"])

    # Audio Plans
    op.create_table(
        "audio_plans",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("full_story_narration_text", sa.Text, nullable=True),
        sa.Column("full_story_dialogue_plan", sa.Text, nullable=True),
        sa.Column("full_story_audio_prompt", sa.Text, nullable=True),
        sa.Column("ambience_progression_notes", sa.Text, nullable=True),
        sa.Column("sound_transition_notes", sa.Text, nullable=True),
        sa.Column("total_estimated_audio_duration", sa.Float, nullable=True),
        sa.Column("timing_map_json", sa.Text, nullable=True),
        sa.Column("approved", sa.Boolean, nullable=False, server_default="false"),
    )
    op.create_index("ix_audio_plans_project_id", "audio_plans", ["project_id"])

    # Assets
    op.create_table(
        "assets",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("scene_id", UUID(as_uuid=True), sa.ForeignKey("scenes.id", ondelete="SET NULL"), nullable=True),
        sa.Column("asset_type", sa.Enum(
            "scene_video", "full_story_audio", "final_render",
            name="assettype",
        ), nullable=False),
        sa.Column("file_path", sa.String(1000), nullable=True),
        sa.Column("metadata_json", sa.Text, nullable=True),
        sa.Column("generation_provider", sa.String(200), nullable=True),
        sa.Column("generation_params_json", sa.Text, nullable=True),
        sa.Column("status", sa.Enum(
            "pending", "generating", "complete", "failed",
            name="assetstatus",
        ), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_assets_project_id", "assets", ["project_id"])
    op.create_index("ix_assets_scene_id", "assets", ["scene_id"])

    # Render Jobs
    op.create_table(
        "render_jobs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("job_type", sa.Enum(
            "story_analysis", "scene_planning", "prompt_generation",
            "audio_planning", "consistency_review", "video_generation",
            "audio_generation", "stitching",
            name="jobtype",
        ), nullable=False),
        sa.Column("status", sa.Enum(
            "queued", "running", "complete", "failed", "cancelled",
            name="jobstatus",
        ), nullable=False, server_default="queued"),
        sa.Column("payload_json", sa.Text, nullable=True),
        sa.Column("result_json", sa.Text, nullable=True),
        sa.Column("error_text", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_render_jobs_project_id", "render_jobs", ["project_id"])


def downgrade() -> None:
    op.drop_table("render_jobs")
    op.drop_table("assets")
    op.drop_table("audio_plans")
    op.drop_table("scene_prompts")
    op.drop_table("scene_characters")
    op.drop_table("scenes")
    op.drop_table("locations")
    op.drop_table("characters")
    op.drop_table("projects")

    # Drop enums
    for enum_name in [
        "projectstatus", "scenestatus", "assettype",
        "assetstatus", "jobtype", "jobstatus",
    ]:
        op.execute(f"DROP TYPE IF EXISTS {enum_name}")
