"""Stub LLM provider — returns canned responses for testing without a real LLM."""

import json
import logging
import uuid
from typing import Any, Optional, Type

from pydantic import BaseModel

from app.providers.llm.base import LLMProvider

logger = logging.getLogger(__name__)


class StubLLMProvider(LLMProvider):
    """Returns realistic mock data for each agent call. Useful for UI development and testing."""

    async def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        response_format: Optional[Type[BaseModel]] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> str:
        logger.info("StubLLM: complete() called, returning mock response")
        result = self._generate_mock(system_prompt, user_prompt)
        return json.dumps(result) if isinstance(result, dict) else result

    async def complete_json(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> dict[str, Any]:
        logger.info("StubLLM: complete_json() called")
        result = self._generate_mock(system_prompt, user_prompt)
        if isinstance(result, str):
            return {"text": result}
        return result

    def _generate_mock(self, system_prompt: str, user_prompt: str) -> dict[str, Any] | str:
        """Route to the right mock based on the system prompt keywords."""
        sp = system_prompt.lower()

        if "story analyst" in sp or "analyze the story" in sp:
            return self._mock_analysis()
        elif "scene planner" in sp or "plan scenes" in sp:
            return self._mock_scene_plan()
        elif "visual director" in sp or "cinematic prompt" in sp:
            return self._mock_visual_prompt()
        elif "consistency critic" in sp or "quality assurance reviewer" in sp:
            return self._mock_critique()
        elif "audio director" in sp or "audio storytelling" in sp:
            return self._mock_audio_plan()
        else:
            return {"message": "Stub LLM response", "data": {}}

    def _mock_analysis(self) -> dict[str, Any]:
        return {
            "story_summary": "A lone wanderer traverses a vast desert landscape, discovering an ancient oasis that holds the memory of a lost civilization.",
            "beats": [
                {"beat_index": 0, "description": "The wanderer walks through endless dunes at sunset", "emotion": "solitude"},
                {"beat_index": 1, "description": "A glimmer of green appears on the horizon", "emotion": "hope"},
                {"beat_index": 2, "description": "The wanderer reaches the oasis and discovers ancient ruins", "emotion": "wonder"},
                {"beat_index": 3, "description": "Water reflects the stars as night falls over the oasis", "emotion": "peace"},
            ],
            "characters": [
                {
                    "canonical_name": "The Wanderer",
                    "physical_description": "Tall, lean figure with sun-weathered skin, dark eyes, and short black hair streaked with grey",
                    "clothing_description": "Worn sand-colored cloak over layered desert clothing, leather boots, a wide-brimmed hat",
                    "personality_notes": "Quiet, contemplative, determined",
                    "voice_notes": "Low, measured tone with a slight rasp",
                }
            ],
            "locations": [
                {"name": "The Great Desert", "description": "Endless rolling sand dunes under a vast sky, golden and amber tones at sunset"},
                {"name": "The Ancient Oasis", "description": "A hidden grove of date palms surrounding a crystal-clear pool, with crumbling stone pillars half-buried in sand"},
            ],
            "pacing_notes": "Slow, contemplative pacing throughout. Build wonder gradually.",
            "style_lock": "cinematic desert documentary, golden-hour sidelight, warm amber tones, 35mm film grain, contemplative mood",
        }

    def _mock_scene_plan(self) -> dict[str, Any]:
        scenes = []
        for i in range(4):
            scenes.append({
                "order_index": i,
                "source_excerpt": f"Story excerpt for scene {i+1}...",
                "duration_seconds": 4.0,
                "scene_purpose": f"Establish {'desert landscape' if i == 0 else 'oasis discovery' if i == 2 else 'journey progression'}",
                "visual_summary": f"Visual summary for scene {i+1}",
                "audio_alignment_notes": f"Narration segment {i+1}",
                "continuity_from_previous": "N/A" if i == 0 else f"Continues from scene {i}",
                "continuity_to_next": f"Leads to scene {i+2}" if i < 3 else "Final scene",
                "character_names": ["The Wanderer"],
                "location_name": "The Great Desert" if i < 2 else "The Ancient Oasis",
            })
        return {"scenes": scenes, "total_duration": 16.0}

    def _mock_visual_prompt(self) -> dict[str, Any]:
        return {
            "video_prompt": (
                "Cinematic wide shot of a lone wanderer walking across vast golden sand dunes at sunset. "
                "The figure is tall and lean, wearing a sand-colored cloak that billows gently in the wind. "
                "Camera slowly tracks from left to right, following the wanderer's steady pace. "
                "Warm amber and gold lighting from the low sun, long dramatic shadows stretching across "
                "the rippled sand. Anamorphic lens with subtle lens flare. Shallow depth of field keeping "
                "the wanderer sharp against a softly blurred distant horizon. Photorealistic, cinematic "
                "film grain, 8K quality. The atmosphere is serene and contemplative."
            ),
            "negative_prompt": (
                "cartoon, anime, illustration, blurry, low quality, text, watermark, "
                "multiple people, modern objects, vehicles"
            ),
            "style_notes": "Photorealistic, cinematic, warm desert palette",
            "camera_plan": "Wide shot, slow horizontal track left-to-right, anamorphic lens",
            "subject_description": "Lone wanderer in desert clothing with billowing cloak",
            "environment_description": "Vast golden sand dunes at sunset, warm amber tones",
            "action_description": "Walking steadily across dunes, cloak catching wind",
            "continuity_guardrails": "Maintain consistent cloak color (sand/beige), desert environment",
        }

    def _mock_audio_plan(self) -> dict[str, Any]:
        return {
            "full_story_narration_text": (
                "The desert stretched endlessly before him, each dune a wave frozen in time. "
                "He had walked for days, perhaps weeks — time lost its meaning under the relentless sun. "
                "Then, on the horizon, a shimmer of green. Hope, fragile as a mirage. "
                "The oasis was real. Ancient pillars stood like sentinels around a pool that reflected the cosmos."
            ),
            "full_story_dialogue_plan": "No dialogue. Pure narration with ambient sound design.",
            "full_story_audio_prompt": (
                "Atmospheric, contemplative narration over ambient desert sounds. "
                "Wind, sand, distant silence. Transition to gentle water sounds at the oasis."
            ),
            "ambience_progression_notes": "Desert wind → quiet anticipation → water/oasis ambience → night insects",
            "sound_transition_notes": "Smooth crossfade from desert to oasis ambience",
            "total_estimated_audio_duration": 16.0,
            "timing_map": [
                {"scene_index": 0, "audio_segment_start": 0.0, "audio_segment_end": 4.0, "narration_excerpt": "The desert stretched endlessly..."},
                {"scene_index": 1, "audio_segment_start": 4.0, "audio_segment_end": 8.0, "narration_excerpt": "He had walked for days..."},
                {"scene_index": 2, "audio_segment_start": 8.0, "audio_segment_end": 12.0, "narration_excerpt": "Then, on the horizon..."},
                {"scene_index": 3, "audio_segment_start": 12.0, "audio_segment_end": 16.0, "narration_excerpt": "The oasis was real..."},
            ],
        }

    def _mock_critique(self) -> dict[str, Any]:
        return {
            "overall_quality": "good",
            "issues": [],
            "suggestions": [
                "Consider adding more specific facial expression detail in scene 3",
            ],
            "approved": True,
        }
