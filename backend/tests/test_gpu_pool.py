"""GPU pool: hands out distinct device indices, recycles on release."""

from __future__ import annotations

import asyncio

import pytest

from app.utils.gpu import GPUPool, apply_gpu_env


@pytest.mark.asyncio
async def test_pool_fans_out_to_distinct_gpus():
    pool = GPUPool([0, 1])
    seen: list[int] = []

    async def worker():
        async with pool.acquire() as idx:
            await asyncio.sleep(0)
            seen.append(idx)
            await asyncio.sleep(0)

    await asyncio.gather(*(worker() for _ in range(2)))
    assert sorted(seen) == [0, 1]


@pytest.mark.asyncio
async def test_pool_blocks_when_exhausted_then_recycles():
    pool = GPUPool([0])
    timeline: list[str] = []

    async def task(name):
        async with pool.acquire() as idx:
            timeline.append(f"{name}-acq{idx}")
            await asyncio.sleep(0.05)
            timeline.append(f"{name}-rel{idx}")

    await asyncio.gather(task("a"), task("b"))
    assert timeline.index("a-rel0") < timeline.index("b-acq0")


def test_apply_gpu_env_sets_visible_devices_and_order():
    env: dict = {}
    apply_gpu_env(env, 1)
    assert env["CUDA_VISIBLE_DEVICES"] == "1"
    assert env["CUDA_DEVICE_ORDER"] == "PCI_BUS_ID"
