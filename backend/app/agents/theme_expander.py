"""Theme expander — turns a 1-line theme hint into a full story for an episode."""

from __future__ import annotations

from typing import Any

from app.agents.base import AgentResult, BaseAgent


def _format_cast(characters: list[dict]) -> str:
    if not characters:
        return "(no established cast)"
    lines = []
    for c in characters:
        lines.append(
            f"- {c.get('canonical_name', '?')} "
            f"({c.get('character_kind', 'human')}): "
            f"{c.get('physical_description', '')}"
        )
    return "\n".join(lines)


def _format_locations(locations: list[dict]) -> str:
    if not locations:
        return "(no established locations)"
    return "\n".join(f"- {l.get('name','?')}: {l.get('description','')}" for l in locations)


def _format_prior(prior_eps: list[dict]) -> str:
    if not prior_eps:
        return "(this is the first episode)"
    lines = []
    for ep in prior_eps:
        beats = ep.get("beats") or []
        last_beat = beats[-1].get("description", "") if beats else ""
        lines.append(
            f"- Ep {ep.get('order_index')}: {ep.get('title','')} — "
            f"summary: {ep.get('summary','')} — ended on: {last_beat}"
        )
    return "\n".join(lines)


class ThemeExpanderAgent(BaseAgent):
    """Expand a theme_hint into a full episode story using project cast + prior arc."""

    async def run(self, context: dict[str, Any]) -> AgentResult:
        theme = (context.get("theme") or "").strip()
        duration = context.get("duration_seconds") or 30.0
        characters = context.get("characters") or []
        locations = context.get("locations") or []
        prior_eps = context.get("prior_episodes") or []

        if not theme:
            return AgentResult(success=False, errors=["theme is empty"])

        sentences = max(4, min(10, int(round(duration / 4))))

        system_prompt = (
            "You are a story writer. Convert a one-line theme into a self-contained, "
            "shot-able short story that fits within a target duration. Reuse the project's "
            "established characters and locations whenever possible. Use present tense, "
            "concrete action verbs, and no inner monologue. No dialogue tags — just describe "
            "what happens visually. Respond with JSON only."
        )

        user_prompt = (
            f"THEME (one-line idea):\n  {theme}\n\n"
            f"TARGET DURATION: {duration:.0f} seconds (aim for {sentences} sentences).\n\n"
            f"ESTABLISHED CAST (reuse them — do NOT invent new names):\n{_format_cast(characters)}\n\n"
            f"ESTABLISHED LOCATIONS (reuse one or two — do NOT invent new places):\n{_format_locations(locations)}\n\n"
            f"PRIOR EPISODES (continue the world naturally):\n{_format_prior(prior_eps)}\n\n"
            "OUTPUT — Return ONLY valid JSON:\n"
            '{ "story_text": "<self-contained short story, present tense, visual-action only>" }'
        )

        try:
            result = await self.llm.complete_json(
                system_prompt=system_prompt, user_prompt=user_prompt,
                temperature=0.7, max_tokens=1200,
            )
        except Exception as e:
            self.logger.exception("Theme expansion LLM call failed")
            return AgentResult(success=False, errors=[str(e)])

        text = (result.get("story_text") or "").strip()
        if not text:
            return AgentResult(success=False, errors=["theme expansion returned empty story_text"])

        return AgentResult(success=True, data={"story_text": text})
