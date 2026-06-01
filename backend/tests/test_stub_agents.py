"""Verify each agent runs end-to-end with the StubLLMProvider."""

from __future__ import annotations

import pytest


@pytest.fixture
def stub_llm():
    from app.providers.llm.stub_provider import StubLLMProvider
    return StubLLMProvider()


class TestAgentResult:
    def test_agent_result_success(self):
        from app.agents.base import AgentResult
        r = AgentResult(success=True, data={"key": "value"})
        assert r.success
        assert r.data["key"] == "value"
        assert r.errors == []

    def test_agent_result_failure(self):
        from app.agents.base import AgentResult
        r = AgentResult(success=False, errors=["something broke"])
        assert not r.success
        assert "something broke" in r.errors


class TestStubAgents:
    async def test_story_analyst(self, stub_llm):
        from app.agents.story_analyst import StoryAnalystAgent
        agent = StoryAnalystAgent(stub_llm)
        result = await agent.run({"story_text": "Once upon a time..."})
        assert result.success
        assert "story_summary" in result.data
        assert "beats" in result.data
        assert "characters" in result.data
        assert len(result.data["characters"]) > 0

    async def test_scene_planner(self, stub_llm):
        from app.agents.scene_planner import ScenePlannerAgent
        agent = ScenePlannerAgent(stub_llm)
        result = await agent.run({
            "story_text": "A story",
            "beats": [{"beat_index": 0, "description": "Opening"}],
            "characters": [],
            "locations": [],
        })
        assert result.success
        assert "scenes" in result.data
        assert len(result.data["scenes"]) > 0

    async def test_visual_director(self, stub_llm):
        from app.agents.visual_director import VisualDirectorAgent
        agent = VisualDirectorAgent(stub_llm)
        result = await agent.run({
            "scene": {
                "order_index": 0, "duration_seconds": 4.0,
                "scene_purpose": "Establish setting",
                "visual_summary": "Desert at sunset",
                "source_excerpt": "The desert...",
            },
            "characters": [],
        })
        assert result.success
        assert "video_prompt" in result.data
        assert len(result.data["video_prompt"]) > 50

    async def test_audio_director(self, stub_llm):
        from app.agents.audio_director import AudioDirectorAgent
        agent = AudioDirectorAgent(stub_llm)
        result = await agent.run({
            "story_text": "A story about the desert",
            "scenes": [{"order_index": 0, "duration_seconds": 4.0}],
            "characters": [],
        })
        assert result.success
        assert "full_story_narration_text" in result.data
        assert "timing_map" in result.data

    async def test_consistency_critic(self, stub_llm):
        from app.agents.consistency_critic import ConsistencyCriticAgent
        agent = ConsistencyCriticAgent(stub_llm)
        result = await agent.run({
            "scenes": [{"order_index": 0}],
            "characters": [],
            "audio_plan": {},
        })
        assert result.success
        assert "approved" in result.data or "overall_quality" in result.data
