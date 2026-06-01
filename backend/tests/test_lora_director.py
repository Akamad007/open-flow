"""LoRA director — pure-function guards + batch sizing (no network)."""

import pytest

from app.agents.lora_director import (
    BATCH_SIZE,
    LoRADirectorAgent,
    _TOKENS_FLOOR,
    _TOKENS_PER_SCENE,
    _normalize_loras,
    _validate_selection,
)
from app.providers.llm.base import LLMProvider


class _CaptureLLM(LLMProvider):
    """Echoes one valid selection per requested scene; records max_tokens."""

    def __init__(self):
        self.max_tokens_seen: list[int] = []

    async def complete(self, *a, **k):  # pragma: no cover - unused
        raise NotImplementedError

    async def complete_json(self, system_prompt, user_prompt, temperature=0.7, max_tokens=4096):
        self.max_tokens_seen.append(max_tokens)
        idxs = [int(line.split("scene_index=")[1].split(" ")[0])
                for line in user_prompt.splitlines() if "scene_index=" in line]
        return {"selections": [
            {"scene_index": i, "shot_type": "wide",
             "loras": [{"id": "flat_color", "weight": 0.5}], "rationale": "anime"}
            for i in idxs
        ]}


def test_normalize_drops_none_and_zero_weight():
    sel = {"loras": [{"id": "none", "weight": 0.0},
                     {"id": "flat_color", "weight": 0.5},
                     {"id": "crush_it", "weight": 0.0}]}
    _normalize_loras(sel)
    assert sel["loras"] == [{"id": "flat_color", "weight": 0.5}]


def test_validate_snaps_drifted_weight():
    sel = {"scene_index": 2, "shot_type": "medium",
           "loras": [{"id": "flat_color", "weight": 0.52}]}
    ok, why = _validate_selection(sel, 2)
    assert ok and why == ""
    assert sel["loras"][0]["weight"] == 0.5  # snapped to catalog value


def test_validate_rejects_unknown_and_overlong():
    bad_id = {"scene_index": 1, "shot_type": "wide", "loras": [{"id": "nope", "weight": 0.5}]}
    assert _validate_selection(bad_id, 1)[0] is False
    three = {"scene_index": 1, "shot_type": "wide",
             "loras": [{"id": "flat_color", "weight": 0.5}] * 3}
    assert _validate_selection(three, 1)[0] is False


def test_validate_accepts_empty_stack():
    assert _validate_selection({"scene_index": 1, "shot_type": "wide", "loras": []}, 1)[0]


@pytest.mark.asyncio
async def test_max_tokens_scales_with_batch_and_fits():
    llm = _CaptureLLM()
    scenes = [{"scene_index": i, "video_prompt": "anime monsoon scene"}
              for i in range(BATCH_SIZE)]
    res = await LoRADirectorAgent(llm).run({"scenes": scenes})
    assert res.success and len(res.data["selections"]) == BATCH_SIZE
    # Budget grows with the batch so a full batch never truncates mid-JSON.
    assert llm.max_tokens_seen[0] == _TOKENS_FLOOR + BATCH_SIZE * _TOKENS_PER_SCENE
    assert llm.max_tokens_seen[0] >= BATCH_SIZE * 150
