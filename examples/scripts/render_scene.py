"""Render one scene directly (no celery). GPU pinned via WAN22_GPU_INDEX env.

Usage: WAN22_GPU_INDEX=0 python scripts/render_scene.py <project_id> <scene_id> [--force]
"""
import asyncio
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
# storage_root is relative ("storage"); cwd MUST be backend/ so renders write
# to the same tree the backend/celery serve from.
os.chdir(BACKEND)

from app.orchestration.pipeline import Pipeline  # noqa: E402


async def _main() -> None:
    project_id, scene_id = sys.argv[1], sys.argv[2]
    force = "--force" in sys.argv[3:]
    result = await Pipeline().generate_single_scene(project_id, scene_id, force=force)
    print("RESULT:", result)


if __name__ == "__main__":
    asyncio.run(_main())
