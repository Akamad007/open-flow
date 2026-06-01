"""LoRA Director — single LLM call decides which LoRAs (and shot type)
to use for up to 50 scenes at once.

The agent gets the full catalog from `wan22_lora_catalog.yaml` (LoRA ids,
descriptions, allowed weights, tags) and the scenes' video_prompt text,
and returns a per-scene plan: `{loras: [{id, weight}, ...], shot_type}`.

The plan is persisted on ScenePrompt.lora_plan_json; the Wan22 provider
reads it at video-gen time and falls back to the deterministic keyword
classifier when the field is absent.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from app.agents.base import AgentResult, BaseAgent

BATCH_SIZE = 24
MAX_RETRIES = 2
# Each selection emits ~150-200 output tokens (loras + shot + rationale).
# Budget generously per scene so a full batch never truncates mid-JSON —
# truncation drops the selection count and forces the whole batch to the
# keyword-classifier fallback, silently disabling the director.
_TOKENS_PER_SCENE = 220
_TOKENS_FLOOR = 512

_CATALOG_PATH = Path(__file__).parent.parent / "config" / "wan22_lora_catalog.yaml"
_VALID_SHOTS = {"closeup", "medium", "wide"}


@lru_cache(maxsize=1)
def _catalog() -> dict:
    return yaml.safe_load(_CATALOG_PATH.read_text())


def _build_catalog_block() -> str:
    cat = _catalog()
    lines: list[str] = []
    for lid, meta in cat["loras"].items():
        if lid == "none":
            lines.append(f"- none: leave empty (no LoRA). Use when motion clarity matters more than mood.")
            continue
        weights = meta.get("weights") or [meta.get("sweet_spot", 0.5)]
        ws = ", ".join(str(w) for w in weights)
        caveat = meta.get("weight_caveats") or {}
        cav = ""
        if caveat:
            cav = "  CAVEATS: " + "; ".join(f"@{k}: {v}" for k, v in caveat.items())
        tags = ", ".join(meta.get("tags", []))
        lines.append(
            f"- {lid} (weights: {ws}) — {meta.get('description','')}\n"
            f"  Tags: {tags}{cav}"
        )
    return "\n".join(lines)


def _build_system_prompt() -> str:
    cat = _catalog()
    fallback = cat.get("defaults", {}).get("fallback", {})
    fb_id = fallback.get("lora", "crush_it")
    fb_w = fallback.get("weight", 0.5)
    return (
        "You are a LoRA selector for Wan 2.2 TI2V-5B video generation. For each\n"
        "scene you receive, decide which LoRA(s) — 0, 1, or 2 — to stack, and\n"
        "what shot type the scene should render at. Your job is to read the\n"
        "scene's video_prompt carefully and pick the LoRA combo that will make\n"
        "the rendered video look how the prompt describes — anime if anime,\n"
        "cinematic if cinematic, rainy if rainy, divine if divine.\n\n"
        "═══════════════════════════════════════════════\n"
        "AVAILABLE LoRAs (memorize tags + weights):\n"
        "═══════════════════════════════════════════════\n"
        f"{_build_catalog_block()}\n\n"
        "═══════════════════════════════════════════════\n"
        "SHOT TYPE — read the prompt's composition cues:\n"
        "═══════════════════════════════════════════════\n"
        "  - closeup: prompt says 'closeup', 'tight on face', 'extreme closeup',\n"
        "    'face fills the frame', 'hands-on-product macro', 'tears in eyes',\n"
        "    'eyes brimming', or describes only face-and-shoulders in beats.\n"
        "  - medium:  'waist up', 'knees up', 'torso', 'sitting talking',\n"
        "    or scenes where two characters interact at conversational distance.\n"
        "  - wide:    DEFAULT for any scene with environment, landscape,\n"
        "    multiple figures, wide vista, 'panoramic', 'aerial', 'in the\n"
        "    distance', or full-body action. Wide is also default when the\n"
        "    prompt's Setting line carries 3+ environmental nouns.\n"
        "  WIDE shots trigger face-restoration post-process; CLOSEUPS never do.\n"
        "  When in doubt, pick WIDE — environment context is usually the point.\n\n"
        "═══════════════════════════════════════════════\n"
        "STACKING RULES:\n"
        "═══════════════════════════════════════════════\n"
        "  - 0 LoRAs: ONLY for plain locomotion (pure walking/running/dancing)\n"
        "    where motion clarity must beat mood. NEVER return zero for everything.\n"
        "  - 1 LoRA: COMMON for grounded scenes. Pick the LoRA whose tags best\n"
        "    match the prompt's mood, style, weather, and subject.\n"
        "  - 2 LoRAs: PREFERRED for stylized scenes — one provides style/texture\n"
        "    (flat_color, oil_painting, golden_boy_anime), the other provides\n"
        "    atmosphere/FX (beauty_of_rain, realistic_fire, shadow_smoke,\n"
        "    glowing_eyes, improved_dance). Always check descriptions are compatible.\n"
        "  - Use catalog-allowed weights only. Default to 0.5 unless the catalog's\n"
        "    sweet_spot is 1.0 for that LoRA (e.g. realistic_fire, beauty_of_rain,\n"
        "    glowing_eyes — these benefit from full strength).\n"
        f"  - Fallback when nothing else fits: {fb_id}@{fb_w}.\n\n"
        "═══════════════════════════════════════════════\n"
        "RECIPE LIBRARY — match scene to recipe FIRST:\n"
        "═══════════════════════════════════════════════\n"
        "  ANIME / GHIBLI / CEL-SHADED / HAND-PAINTED (any non-photoreal style):\n"
        "    → flat_color@1.0 (or @0.5 for softer hint of style)\n"
        "    The prompt typically opens with 'Studio Ghibli', 'Mamoru Hosoda',\n"
        "    'cel-shaded anime', 'painterly watercolor', 'hand-drawn', 'cartoon',\n"
        "    'Makoto Shinkai'. flat_color is the anime/Ghibli default. Reach for\n"
        "    it FIRST on any non-photoreal prompt.\n\n"
        "  ANIME + DIVINE / ENLIGHTENED / HALO / GLOWING AURA:\n"
        "    → flat_color@1.0 + glowing_eyes@1.0 (2-LoRA stack)\n"
        "    For Krishna, Buddha (post-enlightenment), Vivekananda mid-vision,\n"
        "    Jaggi with enlightenment halo, gods, demons, powered-up beings.\n"
        "    Triggered by prompt language: 'halo', 'aureole', 'divine glow',\n"
        "    'enlightenment', 'samadhi', 'cosmic vision', 'inner glow', 'awakened'.\n\n"
        "  ANIME + RAIN / MONSOON / WET ATMOSPHERE:\n"
        "    → flat_color@0.5 + beauty_of_rain@1.0 (2-LoRA stack)\n"
        "    For monsoon scenes, rain, storm, wet ground, water beading on hood.\n"
        "    Triggered by 'rain', 'monsoon', 'storm', 'downpour', 'wet ground',\n"
        "    'rain pours'. beauty_of_rain is the must-include for any wet weather.\n\n"
        "  ANIME + FIRE / TORCH / FLAME / PYRE:\n"
        "    → flat_color@0.5 + realistic_fire@1.0 (2-LoRA stack)\n"
        "    For fire visions, lamp flames as focal point, pyres, torches, sparks.\n\n"
        "  ANIME + DEMONIC SHADOW / SMOKE / DARK MIST:\n"
        "    → flat_color@1.0 + shadow_smoke@1.0 (2-LoRA stack)\n"
        "    For Mara, demons, dissolving forms, dark cosmic void, smoky retreat.\n\n"
        "  ANIME + EXPRESSIVE DANCE / FLUID GESTURE / CHOREOGRAPHY:\n"
        "    → flat_color@0.5 + improved_dance@1.0 (2-LoRA stack)\n"
        "    For dance, ritual sway, devotional movement, expressive body motion.\n\n"
        "  ANIME + WIDE ENVIRONMENT / LANDSCAPE / PILGRIMAGE / ESTABLISHING:\n"
        "    → flat_color@0.5 + golden_boy_anime@1.0 (2-LoRA stack)\n"
        "    For Shinkai-style wide vistas with rich environment — Rajasthan\n"
        "    desert, Tamil paddy fields, hilltop views, Kanyakumari shoreline,\n"
        "    Bombay harbor, Chicago skyline, Dakshineswar courtyards.\n\n"
        "  HISTORICAL INDIA / PERIOD DRAMA / SEPIA / 19TH-CENTURY:\n"
        "    → flat_color@0.5 + hstoric_color@0.5 (2-LoRA stack for anime period)\n"
        "    OR hstoric_color@1.0 alone for non-anime period drama.\n"
        "    For 1881-1893 Calcutta/Mysore/Madras, sixth-century BCE India,\n"
        "    1890s pilgrimage scenes. NEVER hstoric_color@1.0 on closeups.\n\n"
        "  WATER SPLASH / DRINKING / SPRAY (literal water FX):\n"
        "    → aether_splash@1.0 (alone or with flat_color@0.5 for anime).\n"
        "    Only when the prompt EXPLICITLY shows water as the visual subject —\n"
        "    not just 'rain in background' (that's beauty_of_rain instead).\n\n"
        "  PHOTOREAL CINEMATIC (no anime cues):\n"
        "    → zackdfilms@1.0 for epic/dramatic, crush_it@0.5 for ad-polish,\n"
        "    hstoric_color@0.5 for warm/period. Stack zackdfilms+hstoric_color\n"
        "    for cinematic war/historical.\n\n"
        "  EDITORIAL FASHION / PURSE / RUNWAY:\n"
        "    → oil_painting@0.5 or oil_painting@0.5 + crush_it@0.5.\n"
        "    NEVER oil_painting@1.0 on realistic action (floating-leaf artifacts).\n\n"
        "═══════════════════════════════════════════════\n"
        "RATIONALE — answer these before picking:\n"
        "═══════════════════════════════════════════════\n"
        "  1. Is this anime/Ghibli/cel-shaded? → flat_color MUST be in the stack.\n"
        "  2. Does it have rain/monsoon/wet weather? → add beauty_of_rain.\n"
        "  3. Does it have fire/flame/torch? → add realistic_fire.\n"
        "  4. Does it have a halo/divine/enlightened character? → add glowing_eyes.\n"
        "  5. Does it have demons/dark smoke/shadow figures? → add shadow_smoke.\n"
        "  6. Does it have dance/expressive gesture? → add improved_dance.\n"
        "  7. Is it a wide vista / environment-heavy shot? → consider golden_boy_anime.\n"
        "  8. Is it historical period? → consider hstoric_color (NOT on closeup@1.0).\n\n"
        "═══════════════════════════════════════════════\n"
        "FORBIDDEN:\n"
        "═══════════════════════════════════════════════\n"
        "  - Inventing LoRA ids not in the catalog.\n"
        "  - Using weights not listed for that LoRA.\n"
        "  - oil_painting@1.0 on realistic action (floating-leaf artifacts).\n"
        "  - aether_splash unless the prompt EXPLICITLY mentions water/drink/spray.\n"
        "  - hstoric_color@1.0 on closeups (causes prompt drift).\n"
        "  - beauty_of_rain on dry/sunny scenes (introduces unwanted wetness).\n"
        "  - Empty LoRA stack unless it's plain pure locomotion (rare).\n"
        "  - Skipping the anime cue: if the prompt says 'anime' or 'Ghibli',\n"
        "    flat_color MUST appear in your stack. No exceptions.\n"
        "  - Stacking two atmosphere/FX LoRAs that physically conflict — never\n"
        "    pair beauty_of_rain with realistic_fire, or beauty_of_rain with\n"
        "    shadow_smoke. One style LoRA + at most one atmosphere/FX LoRA.\n\n"
        "═══════════════════════════════════════════════\n"
        "OUTPUT — strict JSON, nothing else:\n"
        "═══════════════════════════════════════════════\n"
        "{\n"
        "  \"selections\": [\n"
        "    {\"scene_index\": <int>, \"loras\": [{\"id\": \"<lora_id>\", \"weight\": <float>}, ...],\n"
        "     \"shot_type\": \"closeup|medium|wide\",\n"
        "     \"rationale\": \"<≤8 words — name the recipe matched>\"}\n"
        "  ]\n"
        "}\n"
        "You MUST emit one entry per scene_index given, in order, with no extras."
    )


def _build_user_prompt(scenes: list[dict[str, Any]]) -> str:
    parts = [f"Pick LoRA + shot for these {len(scenes)} scene(s):\n"]
    for s in scenes:
        idx = s["scene_index"]
        prompt = (s.get("video_prompt") or "").strip()
        purpose = (s.get("scene_purpose") or "").strip()
        parts.append(f"--- scene_index={idx} ---")
        if purpose:
            parts.append(f"Purpose: {purpose}")
        parts.append(f"Prompt: {prompt[:1200]}")  # 1200 chars per scene is plenty
        parts.append("")
    return "\n".join(parts)


def _normalize_loras(sel: dict) -> None:
    """Drop `none`/empty/zero-weight entries in place — the model is told that
    'none' means an empty stack, so a literal `none` entry is an empty slot,
    not an error worth failing (and retrying) the whole batch over."""
    cleaned = []
    for e in sel.get("loras") or []:
        if not isinstance(e, dict):
            continue
        lid = e.get("id")
        if lid and lid != "none" and float(e.get("weight") or 0) > 0:
            cleaned.append(e)
    sel["loras"] = cleaned


def _validate_selection(sel: dict, expected_idx: int) -> tuple[bool, str]:
    cat = _catalog()
    valid_ids = set(cat["loras"].keys())
    if sel.get("scene_index") != expected_idx:
        return False, f"scene_index mismatch: got {sel.get('scene_index')} expected {expected_idx}"
    shot = sel.get("shot_type")
    if shot not in _VALID_SHOTS:
        return False, f"invalid shot_type: {shot!r}"
    loras = sel.get("loras") or []
    if not isinstance(loras, list) or len(loras) > 2:
        return False, f"loras must be a list of 0-2 items, got {loras!r}"
    for entry in loras:
        lid = entry.get("id")
        w = entry.get("weight")
        if lid not in valid_ids or lid == "none":
            return False, f"unknown lora id: {lid!r}"
        allowed_weights = cat["loras"][lid].get("weights") or []
        # Snap to the nearest allowed weight within 0.05 to absorb minor model
        # drift; the renderer must receive a catalog-valid weight, not 0.52.
        near = min(allowed_weights, key=lambda aw: abs(float(w) - float(aw)), default=None)
        if near is None or abs(float(w) - float(near)) > 0.05:
            return False, f"weight {w} not allowed for {lid} (allowed: {allowed_weights})"
        entry["weight"] = float(near)
    return True, ""


class LoRADirectorAgent(BaseAgent):
    """Selects LoRAs + shot_type for a batch of scenes in one LLM call."""

    async def run(self, context: dict[str, Any]) -> AgentResult:
        scenes: list[dict[str, Any]] = context.get("scenes") or []
        if not scenes:
            return AgentResult(success=True, data={"selections": []})

        system_prompt = _build_system_prompt()
        user_prompt = _build_user_prompt(scenes)

        last_err = ""
        for attempt in range(MAX_RETRIES + 1):
            try:
                raw = await self.llm.complete_json(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    temperature=0.2,
                    max_tokens=_TOKENS_FLOOR + len(scenes) * _TOKENS_PER_SCENE,
                )
            except Exception as e:
                last_err = f"LLM call failed: {e}"
                self.logger.warning("LoRA director attempt %d: %s", attempt + 1, last_err)
                continue

            selections = raw.get("selections")
            if not isinstance(selections, list) or len(selections) != len(scenes):
                last_err = f"expected {len(scenes)} selections, got {len(selections) if isinstance(selections, list) else 'non-list'}"
                self.logger.warning("LoRA director attempt %d: %s", attempt + 1, last_err)
                user_prompt = _build_user_prompt(scenes) + f"\n\nPRIOR ATTEMPT REJECTED: {last_err}"
                continue

            errs: list[str] = []
            for sel, sc in zip(selections, scenes):
                _normalize_loras(sel)
                ok, why = _validate_selection(sel, sc["scene_index"])
                if not ok:
                    errs.append(f"scene_index={sc['scene_index']}: {why}")
            if errs:
                last_err = "; ".join(errs[:5])
                self.logger.warning("LoRA director attempt %d validation failed: %s",
                                    attempt + 1, last_err)
                user_prompt = _build_user_prompt(scenes) + f"\n\nPRIOR ATTEMPT REJECTED: {last_err}"
                continue

            return AgentResult(success=True, data={"selections": selections})

        return AgentResult(success=False, errors=[last_err or "exceeded retries"])

    async def run_batched(
        self, all_scenes: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Drive multiple batches of BATCH_SIZE scenes. Returns the flat
        list of selections aligned to `all_scenes`. Missing/failed selections
        are filled with None (caller falls back to the keyword classifier)."""
        out: list[dict[str, Any] | None] = [None] * len(all_scenes)
        for start in range(0, len(all_scenes), BATCH_SIZE):
            batch = all_scenes[start:start + BATCH_SIZE]
            self.logger.info(
                "LoRA director batch %d-%d (%d scenes)",
                start, start + len(batch) - 1, len(batch),
            )
            res = await self.run({"scenes": batch})
            if not res.success:
                self.logger.warning("LoRA director batch failed: %s",
                                    "; ".join(res.errors))
                continue
            for sc, sel in zip(batch, res.data.get("selections", [])):
                out[sc["_pos"]] = sel
        return out
