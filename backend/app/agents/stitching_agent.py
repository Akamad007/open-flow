"""
Stitching Agent — assembles final video from scene clips + continuous audio.
"""

import json
import logging
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.asset import Asset, AssetStatus, AssetType
from app.models.scene import Scene
from app.providers.stitching.base import SceneClip, StitchingProvider

logger = logging.getLogger(__name__)


class StitchingAgent:
    """Assembles scene clips and continuous audio into a final render."""

    def __init__(self, stitching_provider: StitchingProvider):
        self.stitcher = stitching_provider

    async def stitch_project(
        self, project_id: uuid.UUID, db: AsyncSession,
        episode_id: uuid.UUID | None = None,
        skip_audio: bool = False,
    ) -> Asset:
        """Stitch all scene videos + audio into final output.
        When `episode_id` is provided, only that episode's scenes are stitched
        and the final render is written under storage/renders/<project>/<episode>/.
        When `skip_audio=True`, no audio asset is required — the render is
        produced video-only so the caller can overlay their own audio later."""
        if episode_id is not None:
            stmt = select(Scene).where(Scene.episode_id == episode_id).order_by(Scene.order_index)
        else:
            stmt = select(Scene).where(Scene.project_id == project_id).order_by(Scene.order_index)
        result = await db.execute(stmt)
        scenes = result.scalars().all()

        # Get video assets for each scene
        scene_clips = []
        for scene in scenes:
            video_stmt = (
                select(Asset)
                .where(
                    Asset.scene_id == scene.id,
                    Asset.asset_type == AssetType.scene_video,
                    Asset.status == AssetStatus.complete,
                )
                .order_by(Asset.created_at.desc())
                .limit(1)
            )
            video_result = await db.execute(video_stmt)
            video_asset = video_result.scalar_one_or_none()

            if not video_asset or not video_asset.file_path:
                logger.warning("Scene %d has no completed video", scene.order_index)
                continue

            scene_clips.append(SceneClip(
                scene_id=str(scene.id),
                file_path=Path(video_asset.file_path),
                order_index=scene.order_index,
                target_duration=scene.duration_seconds,
                caption=scene.caption,
            ))

        if not scene_clips:
            raise ValueError("No scene videos available for stitching")

        # Get audio asset (episode-scoped if episode_id provided) — unless
        # we're stitching a silent background video.
        audio_asset = None
        if not skip_audio:
            audio_where = [
                Asset.asset_type == AssetType.full_story_audio,
                Asset.status == AssetStatus.complete,
            ]
            if episode_id is not None:
                audio_where.append(Asset.episode_id == episode_id)
            else:
                audio_where.append(Asset.project_id == project_id)
            audio_stmt = (
                select(Asset).where(*audio_where)
                .order_by(Asset.created_at.desc()).limit(1)
            )
            audio_result = await db.execute(audio_stmt)
            audio_asset = audio_result.scalar_one_or_none()
            if not audio_asset or not audio_asset.file_path:
                raise ValueError("No completed audio asset available")

        # Output path — segregate per episode when known
        if episode_id is not None:
            output_path = (
                settings.storage_root / "renders" / str(project_id)
                / "episodes" / str(episode_id) / "final_render.mp4"
            )
        else:
            output_path = settings.storage_root / "renders" / str(project_id) / "final_render.mp4"

        # Create render asset
        render_asset = Asset(
            project_id=project_id,
            episode_id=episode_id,
            asset_type=AssetType.final_render,
            status=AssetStatus.generating,
            generation_provider="ffmpeg",
        )
        db.add(render_asset)
        await db.flush()

        # Stitch
        stitch_result = await self.stitcher.stitch(
            scene_clips=scene_clips,
            audio_path=Path(audio_asset.file_path) if audio_asset else None,
            output_path=output_path,
        )

        if stitch_result.success:
            render_asset.status = AssetStatus.complete
            render_asset.file_path = stitch_result.file_path
            render_asset.metadata_json = json.dumps(stitch_result.metadata)
        else:
            render_asset.status = AssetStatus.failed
            render_asset.metadata_json = json.dumps({"error": stitch_result.error})

        await db.flush()
        return render_asset
