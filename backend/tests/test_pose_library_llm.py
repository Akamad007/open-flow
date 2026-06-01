"""LLM-driven pose-library selection — verifies correct label gets resolved
to a PoseEntry, and that bogus / failed LLM responses fall through to None
so the caller can use the deterministic keyword matcher as fallback."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.agents.image_pregen import pose_library


class _OKLLM:
    def __init__(self, payload):
        self._payload = payload
        self.last_user = None
    async def complete_json(self, *, system_prompt, user_prompt, max_tokens):
        self.last_user = user_prompt
        return self._payload


class _BoomLLM:
    async def complete_json(self, *, system_prompt, user_prompt, max_tokens):
        raise RuntimeError("network down")


def _seed_library(tmp_path: Path, monkeypatch) -> None:
    """Stand up a tiny pose library on disk and point pose_library at it."""
    lib = tmp_path / "pose_library"
    lib.mkdir()
    for name in ("standing.png", "kneeling.png", "running.png"):
        (lib / name).write_bytes(b"fake-png")
    manifest = [
        {"label": "standing_neutral", "photo": "standing.png",
         "keywords": ["standing", "upright", "still"]},
        {"label": "kneeling_one_knee", "photo": "kneeling.png",
         "keywords": ["kneel", "kneeling", "one knee"]},
        {"label": "running_side", "photo": "running.png",
         "keywords": ["run", "running", "sprint", "jog"]},
    ]
    (lib / "manifest.json").write_text(json.dumps(manifest))

    from app.config import settings as cfg
    monkeypatch.setattr(cfg, "storage_root", tmp_path)
    pose_library.reload()


@pytest.mark.asyncio
async def test_llm_match_resolves_label_to_entry(tmp_path, monkeypatch):
    _seed_library(tmp_path, monkeypatch)
    llm = _OKLLM({"label": "kneeling_one_knee"})
    entry = await pose_library.match_with_llm("she kneels and pours soil", llm)
    assert entry is not None
    assert entry.label == "kneeling_one_knee"
    assert "soil" in llm.last_user


@pytest.mark.asyncio
async def test_llm_match_returns_none_for_unknown_label(tmp_path, monkeypatch):
    _seed_library(tmp_path, monkeypatch)
    llm = _OKLLM({"label": "made_up_pose_name"})
    assert await pose_library.match_with_llm("any action", llm) is None


@pytest.mark.asyncio
async def test_llm_match_returns_none_when_llm_raises(tmp_path, monkeypatch):
    _seed_library(tmp_path, monkeypatch)
    assert await pose_library.match_with_llm("any action", _BoomLLM()) is None


@pytest.mark.asyncio
async def test_llm_match_returns_none_for_empty_action(tmp_path, monkeypatch):
    _seed_library(tmp_path, monkeypatch)
    llm = _OKLLM({"label": "standing_neutral"})
    assert await pose_library.match_with_llm("", llm) is None
    assert await pose_library.match_with_llm("   ", llm) is None
