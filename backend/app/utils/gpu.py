"""Async GPU pool for parallel subprocess providers.

Each image-gen subprocess (SD3.5, InstantID, Chatterbox) wants exclusive
ownership of one GPU (via CUDA_VISIBLE_DEVICES). When two stills can be
generated in parallel, we want each to land on a different GPU. The pool
hands out distinct device indices and recycles them on release, so
asyncio.gather over N tasks naturally fans out across N GPUs.

The pool is lazily created per asyncio event loop. Celery's per-task
asyncio.run() pattern means each task gets a fresh loop, and the
WeakKeyDictionary cleans up automatically when the loop is gc'd.
"""

import asyncio
import os
import subprocess
import weakref
from contextlib import asynccontextmanager
from functools import lru_cache
from typing import AsyncIterator


@lru_cache(maxsize=1)
def _gpu_count() -> int:
    try:
        out = subprocess.run(
            ["nvidia-smi", "-L"],
            capture_output=True, text=True, timeout=2,
        )
        if out.returncode != 0:
            return 0
        return sum(1 for line in out.stdout.splitlines() if line.startswith("GPU "))
    except (FileNotFoundError, subprocess.SubprocessError):
        return 0


def gpu_count() -> int:
    """Number of physical GPUs visible (min 0). Public wrapper over the
    cached probe — used by the multi-GPU router to size the queue set."""
    return _gpu_count()


@lru_cache(maxsize=1)
def non_largest_gpu_index() -> int:
    """CUDA index of a GPU that is NOT the largest — used for audio gen
    (Chatterbox) and other non-video work so it doesn't compete for VRAM
    with Wan22 video gen on the big card. Falls back to the only GPU
    when there's just one."""
    if _gpu_count() <= 1:
        return 0
    biggest = largest_gpu_index()
    return 1 - biggest if biggest in (0, 1) else 0


@lru_cache(maxsize=1)
def largest_gpu_index() -> int:
    """CUDA index (under PCI_BUS_ID ordering) of the GPU with most VRAM.

    Video gen (Wan22 / Phantom) is single-process and must always land on
    the larger card — otherwise it OOMs on the smaller one when worker
    identity or PCI order shifts.
    """
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=2,
            env={"CUDA_DEVICE_ORDER": "PCI_BUS_ID"},
        )
        if out.returncode != 0:
            return 0
        mems = [int(s.strip()) for s in out.stdout.splitlines() if s.strip()]
        if not mems:
            return 0
        return max(range(len(mems)), key=lambda i: mems[i])
    except (FileNotFoundError, subprocess.SubprocessError, ValueError):
        return 0


class GPUPool:
    """Async pool of CUDA device indices. acquire() blocks until a GPU is free."""

    def __init__(self, gpu_indices: list[int]):
        self._q: asyncio.Queue[int] = asyncio.Queue()
        for idx in gpu_indices:
            self._q.put_nowait(idx)
        self._size = len(gpu_indices)

    @property
    def size(self) -> int:
        return self._size

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[int]:
        idx = await self._q.get()
        try:
            yield idx
        finally:
            self._q.put_nowait(idx)


_pools: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, GPUPool]" = (
    weakref.WeakKeyDictionary()
)


def get_pool() -> GPUPool:
    """Return the GPUPool bound to the running event loop, creating it on first use.

    Pool size = number of physical GPUs (min 1). With 0 GPUs visible we
    still hand out index 0 so callers run unpinned (CPU/whatever the
    subprocess defaults to)."""
    loop = asyncio.get_event_loop()
    pool = _pools.get(loop)
    if pool is None:
        pin = os.environ.get("IMAGE_GEN_GPU_INDEX")
        if pin is not None:
            pool = GPUPool([int(pin)])
        else:
            n = _gpu_count()
            pool = GPUPool(list(range(n)) if n > 0 else [0])
        _pools[loop] = pool
    return pool


def apply_gpu_env(env: dict, gpu_index: int) -> dict:
    """Pin a subprocess env to a single GPU index (mutates env in place)."""
    env["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
    env["CUDA_VISIBLE_DEVICES"] = str(gpu_index)
    return env
