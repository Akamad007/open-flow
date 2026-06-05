"""
Asset Generation Orchestrator — manages video and audio generation jobs.

Scene continuity: after generating scene N, extracts its last frame and feeds
it as the conditioning image (I2V) for scene N+1, anchoring character appearance,
lighting, and composition across cuts.
"""

import asyncio
import json
import logging
import uuid
from pathlib import Path
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.asset import Asset, AssetStatus, AssetType
from app.models.scene import Scene, SceneStatus
from app.providers.audio.base import AudioProvider
from app.providers.video.base import VideoProvider, VideoSettings
from app.utils.ltx_validator import validate_scene_video

logger = logging.getLogger(__name__)


class AssetOrchestrator:
    """Coordinates video/audio asset generation with status tracking."""

    def __init__(
        self,
        video_provider: VideoProvider,
        audio_provider: AudioProvider,
        provider_settings: Optional[dict] = None,
    ):
        self.video = video_provider
        self.audio = audio_provider
        # Profile-supplied overrides (Wan: 832×480/81f/50 steps; LTX leaves None
        # → falls back to settings.ltx_*). Set by scene_video stage from the
        # project's pipeline_profile.
        self.provider_settings = provider_settings or {}

    async def _extract_last_frame(self, video_path: str, frame_path: str) -> bool:
        """Extract the last frame of a video using ltx_generate.py --extract-last-frame."""
        script_path = Path(__file__).parent.parent.parent.parent / "engines" / "ltx_generate.py"
        cmd = [
            settings.gpu_python_path, str(script_path),
            "--extract-last-frame", video_path,
            "--output", frame_path,
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                logger.warning("Frame extraction timed out for %s", video_path)
                return False
            if proc.returncode == 0:
                logger.info("Extracted last frame → %s", frame_path)
                return True
            else:
                logger.warning("Frame extraction failed: %s", stderr.decode()[-200:])
                return False
        except Exception:
            logger.exception("Frame extraction error")
            return False

    async def _extract_first_frame(self, video_path: str, frame_path: str) -> bool:
        """Extract the first frame of a video using ffmpeg."""
        cmd = ["ffmpeg", "-i", video_path, "-vframes", "1", "-update", "1", "-q:v", "2", frame_path, "-y"]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
            if proc.returncode == 0:
                logger.info("Extracted first frame → %s", frame_path)
                return True
            logger.warning("First frame extraction failed: %s", stderr.decode()[-200:])
            return False
        except Exception:
            logger.exception("First frame extraction error")
            return False

    def _video_settings(self) -> VideoSettings:
        ps = self.provider_settings
        return VideoSettings(
            num_frames=ps.get("num_frames", settings.ltx_num_frames),
            fps=ps.get("fps", settings.ltx_fps),
            height=ps.get("height", settings.ltx_height),
            width=ps.get("width", settings.ltx_width),
            num_inference_steps=ps.get("steps", settings.ltx_inference_steps),
            guidance_scale=ps.get("guidance_text", settings.ltx_guidance_scale),
        )

    async def _finalize_scene_video(
        self, asset: Asset, scene: Scene, result, vs: VideoSettings,
    ) -> None:
        """Validate the rendered file and persist status + stats."""
        if not result.success:
            asset.status = AssetStatus.failed
            asset.metadata_json = json.dumps({"error": result.error})
            scene.status = SceneStatus.failed
            return
        report = await asyncio.to_thread(
            validate_scene_video, result.file_path, vs.num_frames, vs.fps,
        )
        meta = {**(result.metadata or {}), "validation_stats": report.stats}
        asset.file_path = result.file_path
        if report.ok:
            asset.status = AssetStatus.complete
            asset.metadata_json = json.dumps(meta)
            scene.status = SceneStatus.generated
        else:
            logger.warning(
                "LTX post-render validation failed for scene %s: %s",
                scene.id, report.errors,
            )
            asset.status = AssetStatus.failed
            asset.metadata_json = json.dumps({**meta, "validation_errors": report.errors})
            scene.status = SceneStatus.failed

    async def generate_scene_video(
        self,
        scene: Scene,
        project_id: uuid.UUID,
        db: AsyncSession,
        condition_image_path: Optional[str] = None,
        character_image_path: Optional[str] = None,
        background_image_path: Optional[str] = None,
        scene_action_images: Optional[list[str]] = None,
    ) -> Asset:
        """Generate video for a single scene, conditioned on character + background images."""
        prompt = scene.prompt
        if not prompt or not prompt.video_prompt:
            raise ValueError(f"Scene {scene.id} has no video prompt")

        filename = f"scene_{scene.order_index:03d}_{scene.id}.mp4"
        output_path = settings.storage_root / "videos" / str(project_id) / filename

        asset = Asset(
            project_id=project_id, scene_id=scene.id,
            asset_type=AssetType.scene_video, status=AssetStatus.generating,
            generation_provider=self.video.__class__.__name__,
            generation_params_json=json.dumps({
                "duration": scene.duration_seconds,
                "i2v": condition_image_path is not None,
                "has_character": character_image_path is not None,
                "has_background": background_image_path is not None,
                "has_action_stills": len(scene_action_images or []),
            }),
        )
        db.add(asset)
        scene.status = SceneStatus.generating
        await db.flush()

        vs = self._video_settings()
        result = await self.video.generate_video(
            prompt=prompt.video_prompt,
            negative_prompt=prompt.negative_prompt or "",
            output_path=output_path,
            video_settings=vs,
            condition_image_path=condition_image_path,
            character_image_path=character_image_path,
            background_image_path=background_image_path,
            scene_action_images=scene_action_images,
            lora_plan_json=prompt.lora_plan_json,
        )
        await self._finalize_scene_video(asset, scene, result, vs)
        await db.flush()
        return asset

    async def generate_full_story_audio(
        self, narration_text: str, project_id: uuid.UUID,
        target_duration: float, db: AsyncSession,
    ) -> Asset:
        """Generate the full-story continuous audio."""
        filename = f"full_story_audio_{project_id}.wav"
        output_path = settings.storage_root / "audio" / str(project_id) / filename

        asset = Asset(
            project_id=project_id, asset_type=AssetType.full_story_audio,
            status=AssetStatus.generating,
            generation_provider=self.audio.__class__.__name__,
            generation_params_json=json.dumps({"target_duration": target_duration}),
        )
        db.add(asset)
        await db.flush()

        result = await self.audio.generate_full_story_audio(
            narration_text=narration_text, output_path=output_path,
            target_duration=target_duration,
        )

        if result.success:
            asset.status = AssetStatus.complete
            asset.file_path = result.file_path
            asset.metadata_json = json.dumps({**result.metadata, "actual_duration": result.duration_seconds})
        else:
            asset.status = AssetStatus.failed
            asset.metadata_json = json.dumps({"error": result.error})

        await db.flush()
        return asset
