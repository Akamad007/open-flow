"""Stage and pipeline lock semantics — exercised against fakeredis."""

from __future__ import annotations

import fakeredis
import pytest
from celery.exceptions import Ignore

import app.orchestration.locks as locks_mod


@pytest.fixture(autouse=True)
def _swap_redis(monkeypatch):
    """Replace the module-level Redis client with fakeredis for every test."""
    fake = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(locks_mod, "_redis", fake)
    yield fake
    fake.flushall()


def test_acquire_stage_lock_returns_true_when_free(_swap_redis):
    assert locks_mod.acquire_stage_lock("p1", "analyze", "task-A") is True


def test_acquire_stage_lock_returns_false_when_held(_swap_redis):
    assert locks_mod.acquire_stage_lock("p1", "analyze", "task-A") is True
    assert locks_mod.acquire_stage_lock("p1", "analyze", "task-B") is False


def test_release_stage_lock_only_if_owner(_swap_redis):
    locks_mod.acquire_stage_lock("p1", "analyze", "task-A")
    locks_mod.release_stage_lock("p1", "analyze", "task-B")  # not owner
    # Lock should still be held by task-A.
    assert _swap_redis.get(locks_mod._stage_key("p1", "analyze")) == "task-A"

    locks_mod.release_stage_lock("p1", "analyze", "task-A")
    assert _swap_redis.get(locks_mod._stage_key("p1", "analyze")) is None


def test_stage_lock_context_manager_holds_then_releases(_swap_redis):
    with locks_mod.stage_lock("p1", "stage", "task-A"):
        assert _swap_redis.get(locks_mod._stage_key("p1", "stage")) == "task-A"
    assert _swap_redis.get(locks_mod._stage_key("p1", "stage")) is None


def test_stage_lock_context_manager_raises_ignore_on_duplicate(_swap_redis):
    with locks_mod.stage_lock("p1", "stage", "task-A"):
        with pytest.raises(Ignore):
            with locks_mod.stage_lock("p1", "stage", "task-B"):
                pytest.fail("Should not enter body when duplicate")


def test_stage_lock_context_manager_releases_on_exception(_swap_redis):
    with pytest.raises(RuntimeError, match="boom"):
        with locks_mod.stage_lock("p1", "stage", "task-A"):
            raise RuntimeError("boom")
    assert _swap_redis.get(locks_mod._stage_key("p1", "stage")) is None


def test_pipeline_lock_basic(_swap_redis):
    assert locks_mod.acquire_pipeline_lock("p1", "task-A") is True
    assert locks_mod.acquire_pipeline_lock("p1", "task-B") is False

    locks_mod.release_pipeline_lock("p1", "task-A")
    assert locks_mod.acquire_pipeline_lock("p1", "task-B") is True


def test_pipeline_lock_release_only_if_owner(_swap_redis):
    locks_mod.acquire_pipeline_lock("p1", "task-A")
    locks_mod.release_pipeline_lock("p1", "task-B")
    assert _swap_redis.get(locks_mod._pipeline_key("p1")) == "task-A"


def test_clear_all_locks_for_project(_swap_redis):
    locks_mod.acquire_stage_lock("p1", "stage1", "task-A")
    locks_mod.acquire_stage_lock("p1", "stage2", "task-B")
    locks_mod.acquire_pipeline_lock("p1", "task-C")
    locks_mod.acquire_stage_lock("p2", "stage1", "task-D")

    locks_mod.clear_all_locks_for_project("p1")

    assert _swap_redis.get(locks_mod._stage_key("p1", "stage1")) is None
    assert _swap_redis.get(locks_mod._stage_key("p1", "stage2")) is None
    assert _swap_redis.get(locks_mod._pipeline_key("p1")) is None
    # Other project untouched.
    assert _swap_redis.get(locks_mod._stage_key("p2", "stage1")) == "task-D"


def test_redis_failure_is_fail_open(monkeypatch):
    """If Redis raises, acquire_* returns True so the task still runs."""
    class Boom:
        def set(self, *a, **kw):
            from redis.exceptions import RedisError
            raise RedisError("redis down")

        def get(self, *a, **kw):
            from redis.exceptions import RedisError
            raise RedisError("redis down")

        def delete(self, *a, **kw):
            from redis.exceptions import RedisError
            raise RedisError("redis down")

    monkeypatch.setattr(locks_mod, "_redis", Boom())
    assert locks_mod.acquire_stage_lock("p1", "stage", "task-A") is True
    assert locks_mod.acquire_pipeline_lock("p1", "task-A") is True
