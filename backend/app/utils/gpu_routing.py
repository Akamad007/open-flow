"""Per-project GPU assignment + celery router for multi-GPU rendering.

Each physical GPU gets its own celery queue ``gpu{i}`` served by a worker
pinned to that card (WAN22/IMAGE/AUDIO _GPU_INDEX env). A project is assigned
one GPU at dispatch time; all its GPU-side tasks (image pregen, video, audio)
route to that queue, so N projects render on N GPUs in parallel without
stealing each other's card. CPU/LLM stages stay on the shared ``cpu`` worker.

Assignment lives in Redis (re-asserted on every dispatch), so no migration
and it survives worker restarts. Falls back to GPU 0 when unset — single-GPU
setups behave exactly as before, just on queue ``gpu0`` instead of ``gpu``.
"""
from __future__ import annotations

from typing import Iterable, Optional

from app.utils.gpu import gpu_count

# GPU-side task names. Everything else runs on the shared `cpu` worker.
GPU_TASKS = frozenset({
    "storyvideo.pregen_images",
    "storyvideo.dispatch_video_chord",
    "storyvideo.generate_scene_video",
    "storyvideo.generate_audio",
})

_ASSIGN_KEY = "gpu:assign:{}"
_ASSIGN_TTL = 7 * 24 * 3600  # a week; re-asserted on every dispatch anyway


def gpu_queue(index: int) -> str:
    return f"gpu{index}"


def _redis():
    from app.orchestration.locks import _get_redis
    return _get_redis()


def assign_project_gpu(project_id: str, index: int) -> int:
    """Pin a project to GPU ``index`` for all its GPU-side tasks."""
    idx = int(index)
    try:
        _redis().set(_ASSIGN_KEY.format(project_id), idx, ex=_ASSIGN_TTL)
    except Exception:
        pass
    return idx


def assigned_gpu(project_id: str) -> int:
    """GPU index assigned to a project; 0 when unset/unreachable."""
    try:
        v = _redis().get(_ASSIGN_KEY.format(project_id))
        return int(v) if v is not None else 0
    except Exception:
        return 0


def pick_free_gpu(busy_project_ids: Iterable[str]) -> Optional[int]:
    """Lowest GPU index not assigned to any currently-busy project, or None
    when every card is taken."""
    taken = {assigned_gpu(str(pid)) for pid in busy_project_ids}
    for i in range(max(gpu_count(), 1)):
        if i not in taken:
            return i
    return None


def route_task(name, args=None, kwargs=None, options=None, task=None, **kw):
    """Celery router: all GPU-side tasks → one shared ``gpu`` queue that EVERY
    GPU worker (one per card) consumes, so Celery load-balances scene renders
    across all cards in parallel. Returns None for non-GPU tasks so the static
    cpu routes apply."""
    if name not in GPU_TASKS:
        return None
    return {"queue": "gpu"}
