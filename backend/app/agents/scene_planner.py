"""
Scene Planner Agent — breaks the story into ~5-second cinematic scenes.

Preserves continuity, manages timing, and aligns with the global audio plan.

For long videos (>60 scenes), planning is chunked across multiple LLM calls
to stay under the model's output-token cap. Each chunk is ~24 scenes.
"""

import math
from typing import Any

from app.agents.base import AgentResult, BaseAgent


# Above this scene count, single-shot planning truncates the LLM response
# (max_tokens ~16k, ~300-400 tokens per scene). Switch to chunked mode.
CHUNK_THRESHOLD = 60
SCENES_PER_CHUNK = 24


class ScenePlannerAgent(BaseAgent):
    """Converts story beats into discrete ~5-second scenes with timing metadata."""

    async def run(self, context: dict[str, Any]) -> AgentResult:
        story_text = context.get("story_text", "")
        beats = context.get("beats", [])
        target_scene_duration = context.get("target_scene_duration", 5.0)
        target_total_duration = context.get("target_total_duration", None)

        if not story_text.strip():
            return AgentResult(success=False, errors=["No story text provided"])

        required_scenes = (
            round(target_total_duration / target_scene_duration)
            if target_total_duration else None
        )

        self.logger.info(
            "Planning scenes from %d beats (target: %s scenes @ %.0fs each = %ss total)",
            len(beats), required_scenes or "auto",
            target_scene_duration, target_total_duration or "auto",
        )

        if required_scenes and required_scenes > CHUNK_THRESHOLD:
            return await self._run_chunked(context, required_scenes)
        return await self._run_single(context, required_scenes)

    async def _run_chunked(
        self, context: dict[str, Any], required_scenes: int,
    ) -> AgentResult:
        beats = context.get("beats", [])
        n_chunks = math.ceil(required_scenes / SCENES_PER_CHUNK)
        beats_per_chunk = max(1, math.ceil(len(beats) / n_chunks)) if beats else 0

        self.logger.info(
            "Chunked planning: %d chunks of ~%d scenes (%d beats / %d per chunk)",
            n_chunks, SCENES_PER_CHUNK, len(beats), beats_per_chunk,
        )

        all_scenes: list[dict] = []
        prev_continuity = ""
        scenes_remaining = required_scenes
        for i in range(n_chunks):
            beat_slice = (
                beats[i * beats_per_chunk:(i + 1) * beats_per_chunk]
                if beats_per_chunk else []
            )
            chunk_target = min(SCENES_PER_CHUNK, scenes_remaining)
            if chunk_target <= 0:
                break
            chunk_ctx = {**context, "beats": beat_slice}
            res = await self._plan_chunk(
                chunk_ctx, chunk_target, len(all_scenes), prev_continuity,
                chunk_index=i, total_chunks=n_chunks,
            )
            if not res.success:
                return res
            chunk_scenes = res.data.get("scenes", []) or []
            for s in chunk_scenes:
                s["order_index"] = len(all_scenes)
                all_scenes.append(s)
            scenes_remaining = required_scenes - len(all_scenes)
            if chunk_scenes:
                prev_continuity = chunk_scenes[-1].get("continuity_to_next", "")
            self.logger.info(
                "Chunk %d/%d: produced %d scenes (cumulative %d/%d)",
                i + 1, n_chunks, len(chunk_scenes), len(all_scenes), required_scenes,
            )

        return self._finalize(all_scenes, required_scenes)

    async def _run_single(
        self, context: dict[str, Any], required_scenes: int | None,
    ) -> AgentResult:
        res = await self._plan_chunk(
            context, required_scenes, 0, "", chunk_index=0, total_chunks=1,
        )
        if not res.success:
            return res
        scenes = res.data.get("scenes", []) or []
        return self._finalize(scenes, required_scenes)

    def _finalize(
        self, scenes: list[dict], required_scenes: int | None,
    ) -> AgentResult:
        total = sum(s.get("duration_seconds", 0) for s in scenes)
        self.logger.info("Planned %d scenes, total duration: %.1fs", len(scenes), total)
        if required_scenes and len(scenes) < int(required_scenes * 0.8):
            return AgentResult(success=False, errors=[
                f"Scene planning under-produced: got {len(scenes)} scenes, "
                f"required {required_scenes}. Likely LLM output truncation — "
                f"reduce SCENES_PER_CHUNK or raise max_tokens.",
            ])
        return AgentResult(success=True, data={"scenes": scenes, "total_duration": total})

    async def _plan_chunk(
        self,
        context: dict[str, Any],
        target_scene_count: int | None,
        scene_index_offset: int,
        prev_continuity: str,
        *,
        chunk_index: int,
        total_chunks: int,
    ) -> AgentResult:
        story_text = context.get("story_text", "")
        beats = context.get("beats", [])
        characters = context.get("characters", [])
        locations = context.get("locations", [])
        products = context.get("products", []) or []
        target_scene_duration = context.get("target_scene_duration", 5.0)

        system_prompt = self._load_prompt_template("scene_planner.txt")

        scene_count_instruction = ""
        if target_scene_count:
            chunk_note = (
                f"This is chunk {chunk_index + 1} of {total_chunks}. "
                f"Plan exactly {target_scene_count} scenes for THIS chunk's beats. "
                f"Start scene order_index at {scene_index_offset}. "
                if total_chunks > 1 else ""
            )
            continuity_note = (
                f'The previous chunk ended with this continuity hand-off: "{prev_continuity}". '
                f"Make scene {scene_index_offset}'s continuity_from_previous match it."
                if prev_continuity else ""
            )
            scene_count_instruction = f"""
CRITICAL: {chunk_note}You MUST create exactly {target_scene_count} scenes.
At {target_scene_duration:.0f} seconds per scene, this chunk runs {int(target_scene_count * target_scene_duration)}s.
Stretch the assigned beats across all {target_scene_count} scenes — add establishing shots,
reaction shots, detail close-ups, and atmospheric scenes to fill the duration.
Do NOT compress the beats into fewer scenes. {continuity_note}
"""

        user_prompt = f"""Break the following story into cinematic scenes of approximately {target_scene_duration} seconds each.
{scene_count_instruction}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
INPUT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STORY TEXT:
{story_text}

STORY BEATS (this chunk):
{self._format_beats(beats)}

KNOWN CHARACTERS:
{self._format_characters(characters)}

KNOWN LOCATIONS:
{self._format_locations(locations)}

KNOWN PRODUCT (the SKU this ad is selling — at most one):
{self._format_products(products)}

RULES:
- Each scene = one small, self-contained visual shot (~{target_scene_duration}s)
- A single sentence may produce multiple scenes if the story benefits from separate shots
- Preserve narrative continuity — always fill continuity_from_previous / continuity_to_next
- Specify which characters appear and which location is used per scene
- Estimate cumulative runtime
- Pick whatever framing / shot type each beat needs — there are no required defaults
- LOCATION REUSE — STRICT: ALWAYS pick `location_name` from the KNOWN LOCATIONS list above. NEVER invent a new location string. Multiple consecutive scenes SHOULD share the same location_name unless the story explicitly moves to a new place. A close-up and the wide shot before it = SAME location_name. Treat each background change as expensive — minimize them.
- CHARACTER NAMES — `character_names` lists every character visible in the scene (it's fine to have multiple if the beat genuinely needs them, e.g. Tom and Jerry chasing each other). Use `[]` only for object/environment-only shots with nobody on screen.
- PRODUCT VISIBILITY — If a known product exists (KNOWN PRODUCT block above is non-empty), default `shows_product: true` for EVERY scene. Only set `false` for atmospheric/establishing shots that explicitly precede the product reveal (the planner's call). When the KNOWN PRODUCT block is empty, always emit `shows_product: false` and `product_role: "none"`.
- PRODUCT ROLE — Pick `hero` for the product close-up beat (typically the last second of the spot), `holding` when the character interacts with it, `background` when the product is on a counter / shelf / table, `none` when not on screen.
{f"- MUST produce exactly {target_scene_count} scenes in this chunk" if target_scene_count else ""}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

OUTPUT — Return ONLY valid JSON:
{{
  "scenes": [
    {{
      "order_index": {scene_index_offset},
      "source_excerpt": "<exact portion of text this scene covers>",
      "duration_seconds": {target_scene_duration},
      "scene_purpose": "<narrative purpose: establishing|action|reaction|close-up|transition>",
      "visual_summary": "<1-sentence visual description of what the camera sees>",
      "visual_style_hint": "<style tone for this scene: documentary|commercial|intimate|epic|vlog>",
      "per_second_plan": [
        {{"second": "0-1", "action": "<what physically happens>", "camera": "<shot/move>"}},
        {{"second": "1-2", "action": "<what physically happens>", "camera": "<shot/move>"}}
      ],
      "audio_alignment_notes": "<what audio/narration happens during this scene>",
      "continuity_from_previous": "<how this scene connects visually from the last>",
      "continuity_to_next": "<how this scene leads into the next>",
      "character_names": ["<name>"],
      "location_name": "<location name>",
      "shows_product": true,
      "product_role": "hero|holding|background|none"
    }}
  ],
  "total_duration": 0.0
}}
"""

        try:
            result = await self.llm.complete_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=0.5,
                max_tokens=16384,
            )
            return AgentResult(success=True, data=result)
        except Exception as e:
            self.logger.exception("Scene planning chunk %d failed", chunk_index)
            return AgentResult(success=False, errors=[str(e)])

    @staticmethod
    def _format_beats(beats: list[dict]) -> str:
        lines = []
        for b in beats:
            lines.append(
                f"  Beat {b.get('beat_index', '?')}: {b.get('description', '')} "
                f"(emotion: {b.get('emotion', '')})"
            )
        return "\n".join(lines) if lines else "  (no beats provided)"

    @staticmethod
    def _format_characters(characters: list[dict]) -> str:
        lines = []
        for c in characters:
            lines.append(
                f"  - {c.get('canonical_name', 'Unknown')}: "
                f"{c.get('physical_description', 'N/A')}"
            )
        return "\n".join(lines) if lines else "  (no characters provided)"

    @staticmethod
    def _format_locations(locations: list[dict]) -> str:
        lines = []
        for loc in locations:
            lines.append(
                f"  - {loc.get('name', 'Unknown')}: "
                f"{loc.get('description', 'N/A')}"
            )
        return "\n".join(lines) if lines else "  (no locations provided)"

    @staticmethod
    def _format_products(products: list[dict]) -> str:
        if not products:
            return "  (no product — not a branded ad; emit shows_product=false everywhere)"
        lines = []
        for p in products:
            lines.append(
                f"  - {p.get('canonical_name', 'Unknown')} "
                f"({p.get('category', 'other')}): "
                f"{p.get('physical_description', 'N/A')}"
            )
        return "\n".join(lines)
