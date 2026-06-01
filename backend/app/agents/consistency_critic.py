"""
Consistency Critic Agent — reviews all scenes, prompts, and the audio plan
for identity drift, continuity errors, timing mismatches, and quality issues.
"""

from typing import Any

from app.agents.base import AgentResult, BaseAgent


class ConsistencyCriticAgent(BaseAgent):
    """Reviews the full project bundle for consistency and quality issues."""

    async def run(self, context: dict[str, Any]) -> AgentResult:
        scenes = context.get("scenes", [])
        characters = context.get("characters", [])
        audio_plan = context.get("audio_plan", {})

        if not scenes:
            return AgentResult(success=False, errors=["No scenes to review"])

        self.logger.info("Reviewing %d scenes for consistency", len(scenes))

        system_prompt = self._load_prompt_template("consistency_critic.txt")

        # Build a compact project summary for review
        scene_summaries = []
        for s in scenes:
            prompt_text = ""
            if isinstance(s.get("prompt"), dict):
                prompt_text = s["prompt"].get("video_prompt", "N/A")
            elif isinstance(s.get("video_prompt"), str):
                prompt_text = s["video_prompt"]

            scene_summaries.append({
                "order_index": s.get("order_index", 0),
                "duration": s.get("duration_seconds", 4.0),
                "visual_summary": s.get("visual_summary", ""),
                # Send the FULL prompt — the critic checks per-second timestamps
                # (0–1s, 1–2s, …) and a 200-char truncation cut them off,
                # producing false "missing per-second structure" verdicts.
                "video_prompt_preview": prompt_text or "N/A",
                "character_names": s.get("character_names", []),
                "location": s.get("location_name", ""),
                "continuity_from_previous": s.get("continuity_from_previous", ""),
            })

        total_visual = sum(s["duration"] for s in scene_summaries)
        audio_duration = audio_plan.get("total_estimated_audio_duration", 0)

        user_prompt = f"""Review this project for consistency and quality issues across all scenes.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
INPUT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SCENES ({len(scene_summaries)} total, {total_visual}s visual):
{self._format_scenes(scene_summaries)}

CHARACTERS:
{self._format_characters(characters)}

AUDIO PLAN:
- Estimated duration : {audio_duration}s
- Visual duration    : {total_visual}s
- Duration match     : {'YES ✅' if abs(audio_duration - total_visual) < 1.0 else '⚠️ MISMATCH — NEEDS ADJUSTMENT'}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

CHECKLIST — Check for ALL of the following:
1. Character identity drift (same character described differently across scenes)
2. Location continuity errors (wrong location referenced in wrong scene)
3. Time-of-day inconsistencies (lighting/mood doesn't match time)
4. Repeated or weak video prompts (generic, vague, or duplicate scenes)
5. Visual pacing vs audio pacing mismatch (scenes too fast/slow for narration)
6. Overstuffed scenes (too much action for their duration)
7. Missing continuity between adjacent scenes (abrupt cuts with no connection)
8. Duration alignment (visual total vs audio total)
9. Prompt quality — are characters described by APPEARANCE not abstract labels?
10. Multi-character scenes — are both characters clearly distinguished?
11. PER-SECOND STRUCTURE — Does each video_prompt contain explicit per-second timestamps?
    Every prompt MUST have beats like "0–1s: ..., 1–2s: ..., 2–3s: ..." covering the full duration.
    Flag as HIGH severity if any scene is missing this structure.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

OUTPUT — Return ONLY valid JSON:
{{
  "overall_quality": "<good | acceptable | needs_revision>",
  "issues": [
    {{
      "scene_index": 0,
      "issue_type": "<drift | continuity | pacing | weak_prompt | duration | identity>",
      "description": "<specific, actionable description of the problem>",
      "severity": "<low | medium | high>"
    }}
  ],
  "suggestions": [
    "<specific actionable improvement for the overall project>"
  ],
  "approved": true
}}
"""


        try:
            result = await self.llm.complete_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=0.3,
                max_tokens=4096,
            )

            issues = result.get("issues", [])
            approved = result.get("approved", False)

            self.logger.info(
                "Critique complete: quality=%s, %d issues, approved=%s",
                result.get("overall_quality", "?"),
                len(issues),
                approved,
            )

            return AgentResult(
                success=True,
                data=result,
                warnings=[
                    f"Scene {i.get('scene_index', '?')}: {i.get('description', '')}"
                    for i in issues
                    if i.get("severity") in ("medium", "high")
                ],
            )

        except Exception as e:
            self.logger.exception("Consistency review failed")
            return AgentResult(success=False, errors=[str(e)])

    @staticmethod
    def _format_scenes(scenes: list[dict]) -> str:
        # Render the FULL video_prompt for each scene — that's the actual
        # generation prompt the critic must judge. Without this the critic
        # only saw the planner's short visual_summary and reported false
        # "missing per-second timestamps" verdicts on prompts that were
        # actually well-formed.
        blocks = []
        for s in scenes:
            blocks.append(
                f"--- Scene [{s['order_index']}] ({s['duration']}s) ---\n"
                f"  Summary  : {s.get('visual_summary', 'N/A')}\n"
                f"  Chars    : {', '.join(s.get('character_names', []))}\n"
                f"  Location : {s.get('location', 'N/A')}\n"
                f"  From     : {s.get('continuity_from_previous', 'N/A')}\n"
                f"  VIDEO_PROMPT (the actual generation prompt — judge THIS):\n"
                f"    {s.get('video_prompt_preview', 'N/A')}"
            )
        return "\n".join(blocks)

    @staticmethod
    def _format_characters(characters: list[dict]) -> str:
        if not characters:
            return "  (none)"
        lines = []
        for c in characters:
            lines.append(
                f"  - {c.get('canonical_name', '?')}: {c.get('physical_description', 'N/A')[:100]}"
            )
        return "\n".join(lines)
