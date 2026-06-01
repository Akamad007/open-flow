"""
Full-Story Audio Director Agent — creates a single continuous audio plan
for the entire story, including narration, sound design, and timing map.
"""

from typing import Any

from app.agents.audio_plan_validator import validate_audio_plan
from app.agents.base import AgentResult, BaseAgent

MAX_RETRIES = 2


def _rebuild_with_corrections(base_user_prompt: str, errors: list[str]) -> str:
    """Prepend a corrective block to the user prompt for a retry attempt."""
    if not errors:
        return base_user_prompt
    block = (
        "⚠️ PRIOR ATTEMPT FAILED VALIDATION — fix these specifically and re-emit:\n"
        + "\n".join(f"  - {e}" for e in errors)
        + "\n\n"
    )
    return block + base_user_prompt


class AudioDirectorAgent(BaseAgent):
    """Creates the full-story audio plan — narration, ambience, timing."""

    async def run(self, context: dict[str, Any]) -> AgentResult:
        story_text = context.get("story_text", "")
        scenes = context.get("scenes", [])
        characters = context.get("characters", [])
        target_duration = context.get("target_duration_seconds", None)
        no_on_screen_text = bool(context.get("no_on_screen_text", True))

        if not story_text.strip():
            return AgentResult(success=False, errors=["No story text provided"])
        if not scenes:
            return AgentResult(success=False, errors=["No scenes provided"])

        scene_durations = [float(s.get("duration_seconds", 4.0)) for s in scenes]
        total_visual_duration = sum(scene_durations)
        # Use the user's target duration if provided, otherwise fall back to visual sum
        final_target = target_duration if target_duration else total_visual_duration

        self.logger.info(
            "Planning audio for %d scenes (%.1fs visual, %.1fs target)",
            len(scenes), total_visual_duration, final_target,
        )

        system_prompt = self._load_prompt_template("audio_director.txt")

        scene_summaries = []
        for s in scenes:
            summary = (
                f"  Scene {s.get('order_index', '?')} "
                f"({s.get('duration_seconds', 4.0)}s): "
                f"{s.get('visual_summary', 'N/A')}"
            )
            # Include the video prompt so the narration matches what's on screen
            video_prompt = s.get("video_prompt")
            if video_prompt:
                summary += f"\n    VIDEO PROMPT: {video_prompt}"
            scene_summaries.append(summary)

        # Build explicit per-scene timing table
        timing_breakdown = []
        cursor = 0.0
        for s in scenes:
            dur = s.get("duration_seconds", 4.0)
            timing_breakdown.append(
                f"  Scene {s.get('order_index', '?')}: "
                f"{cursor:.1f}s → {cursor + dur:.1f}s "
                f"({dur:.1f}s of narration needed)"
            )
            cursor += dur

        prior_errors_block = ""
        if context.get("__validator_errors"):
            prior_errors_block = (
                "\n\n⚠️ PRIOR ATTEMPT FAILED VALIDATION — fix these specifically and re-emit:\n"
                + "\n".join(f"  - {e}" for e in context["__validator_errors"]) + "\n"
            )

        user_prompt = f"""Create a single continuous audio narration for the full story.{prior_errors_block}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
INPUT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STORY TEXT:
{story_text}

SCENE BREAKDOWN ({len(scenes)} scenes, {total_visual_duration}s total visual):
{chr(10).join(scene_summaries)}

SCENE-BY-SCENE TIMING:
{chr(10).join(timing_breakdown)}

CHARACTERS:
{self._format_characters(characters)}

TARGET TOTAL DURATION: {final_target}s
Each scene has a fixed duration. Narration for each scene MUST fit its slot.
At natural pace (~120 wpm) every second of narration ≈ 2 words. The full
narration MUST be ~{int(final_target * 2)} words (±20%) — overshoot causes
desync at the stitch.

⚠️ VISUAL CONSTRAINTS (MUST RESPECT — the visual stage forbids these):
- The video has NO on-screen text, NO logos, NO subtitles, NO title cards.
- DO NOT write narration or transition_notes that depend on something being
  visibly displayed (e.g. "Save Soil logo appears", "title card reads", "URL
  shown on screen"). The audio carries those lines via the voiceover.
- Visual transitions can be described in transition_note as audio cues only
  (ambience shifts, music changes, breath pauses) — never as on-screen text.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

OUTPUT — Return ONLY valid JSON:
{{
  "full_story_narration_text": "<complete narration paced for {final_target}s>",
  "full_story_dialogue_plan": "<any dialogue or voice approach notes>",
  "full_story_audio_prompt": "<TTS voice description: tone, pace, gender, accent>",
  "ambience_progression_notes": "<how ambient sound evolves across scenes>",
  "sound_transition_notes": "<how audio bridges between scenes>",
  "total_estimated_audio_duration": {final_target},
  "timing_map": [
    {{
      "scene_index": 0,
      "audio_segment_start": 0.0,
      "audio_segment_end": 4.0,
      "narration_excerpt": "<narration text for this exact segment — fits the time slot>",
      "transition_note": "<how audio transitions to next scene>"
    }}
  ]
}}
"""

        last_result: dict | None = None
        validator_errors: list[str] = []
        for attempt in range(MAX_RETRIES + 1):
            # Re-render the user prompt each attempt so corrective hints are
            # injected on retries.
            context["__validator_errors"] = validator_errors
            current_prompt = (
                user_prompt if attempt == 0
                else _rebuild_with_corrections(user_prompt, validator_errors)
            )
            try:
                last_result = await self.llm.complete_json(
                    system_prompt=system_prompt,
                    user_prompt=current_prompt,
                    temperature=0.6,
                    max_tokens=8192,
                )
            except Exception as e:
                self.logger.exception("Audio planning LLM call failed")
                return AgentResult(success=False, errors=[str(e)])

            report = validate_audio_plan(
                last_result,
                target_duration_s=float(final_target),
                scene_durations=scene_durations,
                no_on_screen_text=no_on_screen_text,
            )
            if report.ok:
                est_duration = last_result.get("total_estimated_audio_duration", 0)
                self.logger.info(
                    "Audio plan ok (attempt %d): %.1fs estimated, %d timing entries",
                    attempt + 1, est_duration, len(last_result.get("timing_map", [])),
                )
                last_result["validator_errors"] = []
                return AgentResult(success=True, data=last_result)

            validator_errors = report.errors
            self.logger.warning(
                "Audio plan failed validation (attempt %d): %s",
                attempt + 1, "; ".join(validator_errors),
            )

        # Out of retries — return last attempt with errors so the caller can
        # decide. We mark success=True so the plan is still persisted; the
        # validator_errors field surfaces the issue for review.
        if last_result is not None:
            last_result["validator_errors"] = validator_errors
            return AgentResult(success=True, data=last_result, warnings=validator_errors)
        return AgentResult(success=False, errors=validator_errors or ["LLM produced no result"])

    @staticmethod
    def _format_characters(characters: list[dict]) -> str:
        if not characters:
            return "  (no characters)"
        lines = []
        for c in characters:
            voice = c.get("voice_notes", "N/A")
            lines.append(f"  - {c.get('canonical_name', 'Unknown')}: voice={voice}")
        return "\n".join(lines)
