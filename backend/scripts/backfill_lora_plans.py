"""Backfill scene_prompts.lora_plan_json for every scene that has a video_prompt
but no plan yet. Runs the LoRADirectorAgent in batches per episode.

Usage:
    python scripts/backfill_lora_plans.py            # all outstanding scenes
    python scripts/backfill_lora_plans.py --dry-run  # show what would run, no LLM calls
    python scripts/backfill_lora_plans.py --project <uuid>  # restrict to one project
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.agents.lora_director import BATCH_SIZE, LoRADirectorAgent
from app.database import async_session_factory
from app.models.scene import Scene
from app.models.scene_prompt import ScenePrompt
from app.orchestration._common import get_llm_provider

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("backfill_lora")


async def find_outstanding(project_id: str | None) -> dict[str, list[Scene]]:
    """Return scenes-with-prompts-but-no-plan, grouped by episode_id."""
    async with async_session_factory() as db:
        q = (
            select(Scene)
            .join(ScenePrompt, ScenePrompt.scene_id == Scene.id)
            .where(ScenePrompt.video_prompt.isnot(None))
            .where(ScenePrompt.lora_plan_json.is_(None))
            .options(selectinload(Scene.prompt))
            .order_by(Scene.episode_id, Scene.order_index)
        )
        if project_id:
            import uuid as _u
            q = q.where(Scene.project_id == _u.UUID(project_id))
        rows = (await db.execute(q)).scalars().all()
        by_episode: dict[str, list[Scene]] = {}
        for s in rows:
            by_episode.setdefault(str(s.episode_id), []).append(s)
        return by_episode


async def backfill_episode(
    agent: LoRADirectorAgent, episode_id: str, scenes: list[Scene], dry_run: bool,
) -> tuple[int, int]:
    items = [
        {
            "_pos": pos,
            "scene_index": scene.order_index,
            "video_prompt": scene.prompt.video_prompt,
            "scene_purpose": scene.scene_purpose or "",
        }
        for pos, scene in enumerate(scenes)
    ]
    logger.info("episode=%s scenes=%d (project=%s)",
                episode_id, len(items), scenes[0].project_id)
    if dry_run:
        return len(items), 0

    selections = await agent.run_batched(items)
    saved = 0
    # Re-open session for the write — keep the read txn short.
    async with async_session_factory() as db:
        # Re-fetch ScenePrompt rows fresh by scene_id (don't re-attach stale objs)
        prompts_by_scene = {}
        scene_ids = [s.id for s in scenes]
        rows = (await db.execute(
            select(ScenePrompt).where(ScenePrompt.scene_id.in_(scene_ids))
        )).scalars().all()
        for r in rows:
            prompts_by_scene[r.scene_id] = r
        for sel, item, scene in zip(selections, items, scenes):
            if not sel:
                continue
            sp = prompts_by_scene.get(scene.id)
            if not sp or sp.lora_plan_json:
                continue
            sp.lora_plan_json = json.dumps({
                "loras": sel.get("loras", []),
                "shot_type": sel.get("shot_type", "medium"),
                "rationale": sel.get("rationale", ""),
            })
            saved += 1
        await db.commit()
    return len(items), saved


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", help="restrict to one project UUID")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    by_ep = await find_outstanding(args.project)
    total_scenes = sum(len(v) for v in by_ep.values())
    logger.info("Outstanding: %d scenes across %d episode(s)",
                total_scenes, len(by_ep))
    if not by_ep:
        return

    agent = LoRADirectorAgent(get_llm_provider())
    grand_total, grand_saved = 0, 0
    for ep_id, scenes in by_ep.items():
        n, s = await backfill_episode(agent, ep_id, scenes, args.dry_run)
        grand_total += n
        grand_saved += s
        logger.info("  -> episode %s: saved %d/%d", ep_id, s, n)
    logger.info("=== DONE: %d/%d scenes received plans ===",
                grand_saved, grand_total)


if __name__ == "__main__":
    asyncio.run(main())
