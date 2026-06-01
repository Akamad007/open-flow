"""Post-stitch evaluation task.

Runs the video evaluator on every scene MP4 + the final stitched output and
writes the metrics + suggested lever deltas back to the DB so the FE can
display them. CPU-only by default to avoid contending with later GPU runs.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.agents.video_evaluator import Levers, evaluate, suggest, to_dict
from app.database import async_session_factory
from app.models.asset import Asset, AssetStatus, AssetType
from app.models.project import Project
from app.models.scene import Scene
from app.models.scene_prompt import ScenePrompt
from app.orchestration.tasks._app import celery_app
from app.orchestration.tasks._runtime import run_async, to_uuid

logger = logging.getLogger(__name__)

CURRENT_LEVERS = Levers()  # provider defaults; mirror wan_phantom_provider.py


async def _scene_video_paths(db, project_uuid) -> dict[str, str]:
    rows = (await db.execute(
        select(Asset).where(
            Asset.project_id == project_uuid,
            Asset.asset_type == AssetType.scene_video,
            Asset.status == AssetStatus.complete,
        )
    )).scalars().all()
    return {str(a.scene_id): a.file_path for a in rows if a.scene_id and a.file_path}


async def _final_video_path(db, project_uuid) -> str | None:
    a = (await db.execute(
        select(Asset).where(
            Asset.project_id == project_uuid,
            Asset.asset_type == AssetType.final_render,
            Asset.status == AssetStatus.complete,
        ).order_by(Asset.created_at.desc()).limit(1)
    )).scalar_one_or_none()
    return a.file_path if a and a.file_path else None


async def _character_portrait(db, project_uuid, scene: Scene) -> str | None:
    if not scene.characters:
        return None
    char_id = scene.characters[0].id
    a = (await db.execute(
        select(Asset).where(
            Asset.project_id == project_uuid,
            Asset.asset_type == AssetType.character_ref,
            Asset.status == AssetStatus.complete,
        )
    )).scalars().all()
    # Match by character name in filename — character_ref assets are not
    # FK-linked to Character rows in this codebase.
    name_slug = scene.characters[0].canonical_name.lower().replace(" ", "_") if scene.characters else ""
    for asset in a:
        if asset.file_path and name_slug and name_slug.split("_")[0] in asset.file_path.lower():
            return asset.file_path
    return a[0].file_path if a else None


async def _evaluate_one(video_path: Path, prompt: str | None, ref: Path | None) -> dict:
    m = evaluate(video_path, prompt, ref, n_frames=6, device="cpu")
    sug = suggest(m, CURRENT_LEVERS)
    return {"metrics": to_dict(m), "suggestion": sug}


async def _run(project_id: str) -> dict:
    project_uuid = to_uuid(project_id)
    async with async_session_factory() as db:
        project = await db.get(Project, project_uuid)
        if not project:
            logger.warning("evaluate: project %s not found", project_id)
            return {"skipped": "project_not_found"}

        scenes = (await db.execute(
            select(Scene)
            .where(Scene.project_id == project_uuid)
            .options(selectinload(Scene.characters), selectinload(Scene.prompt))
            .order_by(Scene.order_index)
        )).scalars().all()

        scene_videos = await _scene_video_paths(db, project_uuid)
        final_path = await _final_video_path(db, project_uuid)

        scene_results = {}
        for sc in scenes:
            vp = scene_videos.get(str(sc.id))
            if not vp or not Path(vp).exists():
                continue
            prompt = sc.prompt.video_prompt if sc.prompt else None
            ref = await _character_portrait(db, project_uuid, sc)
            ref_p = Path(ref) if ref and Path(ref).exists() else None
            try:
                res = await _evaluate_one(Path(vp), prompt, ref_p)
            except Exception as e:
                logger.warning("eval scene %s failed: %s", sc.id, e)
                res = {"error": str(e)}
            sc.evaluation_json = json.dumps(res)
            scene_results[str(sc.id)] = res

        final_result = None
        if final_path and Path(final_path).exists():
            try:
                final_result = await _evaluate_one(
                    Path(final_path), project.story_summary or None, None,
                )
            except Exception as e:
                logger.warning("eval final failed: %s", e)
                final_result = {"error": str(e)}
            project.final_evaluation_json = json.dumps(final_result)

        await db.commit()
        logger.info(
            "Evaluation complete: project %s — %d scenes scored, final=%s",
            project_id, len(scene_results), "yes" if final_result else "no",
        )
        return {"scenes": len(scene_results), "final": bool(final_result)}


@celery_app.task(name="storyvideo.evaluate_project", bind=True, max_retries=1)
def task_evaluate_project(self, project_id: str):
    """Post-stitch eval — runs CLIP/identity/motion/smoothness per scene + final."""
    logger.info("[Eval] Starting post-stitch evaluation for project %s", project_id)
    try:
        return run_async(_run(project_id))
    except Exception as e:
        logger.exception("evaluate_project failed: %s", e)
        return {"error": str(e)}
