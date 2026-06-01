"""Pipeline profile registry — named recipes that bundle which video model,
which stages run, and how conditioning is passed.

A project carries a `pipeline_profile` name; the orchestrator/providers branch
on the profile fields instead of global feature flags. This lets two projects
with different models coexist (subject to GPU serialisation).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class PipelineProfile:
    name: str
    description: str
    # --- Provider plugins ---
    video_provider: str          # "ltx" | "wan_phantom" | "stub"
    audio_provider: str          # "chatterbox" | "stub"
    image_provider: str          # "sd35" | "stub"
    # --- Stage gates ---
    canonical_portrait_enabled: bool
    image_pregen_enabled: bool          # backgrounds + action stills
    face_restoration_enabled: bool      # post-LTX face-restore (Phase 2, planned)
    # --- Conditioning rules (passed to the video provider) ---
    pin_portrait_at_frame_zero: bool    # LTX: never; Phantom: portrait is a ref-image, not a pin
    pin_action_stills: bool             # LTX: never; Phantom: extra ref images
    pin_last_frame_chain: bool          # LTX: yes; Phantom: no (model-level identity)
    drop_last_frame_on_tail: bool       # LTX: yes (avoid cumulative drift)
    # --- Visual director rule toggles ---
    visual_director_far_camera: bool    # F-FAR-CAMERA HARD rule
    visual_director_identity_echo: bool # IDENTITY ECHO HARD rule
    # --- Model-specific tuning (opaque, validated by the provider) ---
    provider_settings: dict[str, Any] = field(default_factory=dict)
    # --- FE display ---
    vram_min_gb: int = 12
    recommended_for: str = ""           # short label for UI dropdown


PROFILES: dict[str, PipelineProfile] = {
    "ltx_text_only": PipelineProfile(
        name="ltx_text_only",
        description="LTX-Video FP8 distilled, text-only. Identity via "
                    "IDENTITY ECHO + last-frame chain. F-FAR-CAMERA on.",
        video_provider="ltx",
        audio_provider="chatterbox",
        image_provider="sd35",
        canonical_portrait_enabled=False,
        image_pregen_enabled=False,
        face_restoration_enabled=False,
        pin_portrait_at_frame_zero=False,
        pin_action_stills=False,
        pin_last_frame_chain=True,
        drop_last_frame_on_tail=True,
        visual_director_far_camera=True,
        visual_director_identity_echo=True,
        provider_settings={},  # falls back to settings.ltx_*
        vram_min_gb=12,
        recommended_for="Fast iteration, multi-scene ads (~25 min/project)",
    ),
    "wan22_text_only": PipelineProfile(
        name="wan22_text_only",
        description="Wan 2.2 TI2V-5B, text-only. LoRA + post-process picked "
                    "per-scene by the provider's catalog classifier "
                    "(backend/app/config/wan22_lora_catalog.yaml). "
                    "Identity via last-frame chain (max 2-clip per scene).",
        video_provider="wan22",
        audio_provider="chatterbox",
        image_provider="sd35",
        canonical_portrait_enabled=False,
        image_pregen_enabled=False,
        face_restoration_enabled=False,   # provider does its own (CodeFormer+ESRGAN on wide shots only)
        pin_portrait_at_frame_zero=False,
        pin_action_stills=False,
        # No portrait or background images — scene 0 is pure T2V. But every
        # scene N>0 conditions on scene (N-1)'s last_frame so the chain
        # carries continuity across the whole project.
        pin_last_frame_chain=True,
        drop_last_frame_on_tail=False,
        visual_director_far_camera=False, # Wan22 handles framing well; no FAR-CAMERA prefix
        visual_director_identity_echo=True,
        # Empirically validated Wan22 baseline. Must be explicit — otherwise
        # AssetOrchestrator._video_settings() falls back to settings.ltx_*
        # (1280×768, 73f, 80 steps) which is OOM-prone and 3× slower on Wan22.
        provider_settings={
            "width": 832,
            "height": 480,
            "num_frames": 121,
            "fps": 24,
            "steps": 40,
            "guidance_text": 5.0,
        },
        vram_min_gb=12,
        recommended_for="Multi-scene ads with style variation via LoRA catalog (~30 min/30s project)",
    ),
    "wan22_image_seeded": PipelineProfile(
        name="wan22_image_seeded",
        description="Wan 2.2 TI2V-5B, image-seeded. Scene 0 conditions on the "
                    "uploaded/canonical character portrait; scenes N>0 chain "
                    "via Wan22 I2V from scene N-1's last frame. NO per-scene "
                    "SD3.5/InstantID action stills.",
        video_provider="wan22",
        audio_provider="chatterbox",
        image_provider="sd35",
        canonical_portrait_enabled=True,
        image_pregen_enabled=True,        # generate character + bg only (no action stills)
        face_restoration_enabled=False,
        pin_portrait_at_frame_zero=False,
        pin_action_stills=False,          # NO action stills — scene 0 conditions on character portrait
        pin_last_frame_chain=True,
        drop_last_frame_on_tail=False,
        visual_director_far_camera=False,
        visual_director_identity_echo=True,
        provider_settings={
            "width": 832,
            "height": 480,
            "num_frames": 73,   # 3.04s @ 24fps — short scenes minimise Wan22 identity drift on motion
            "fps": 24,
            "steps": 100,       # bumped from 60 for sharper faces; motion scenes bump to 140
            "guidance_text": 5.0,
        },
        vram_min_gb=14,
        recommended_for="Identity- or product-locked ads (uploaded character / brand product)",
    ),
    "wan_phantom_text": PipelineProfile(
        name="wan_phantom_text",
        description="Phantom-Wan 14B with FP8 layerwise + CPU offload, "
                    "subject reference image via canonical portrait. Identity "
                    "locked at the model level (no frame pinning).",
        video_provider="wan_phantom",
        audio_provider="chatterbox",
        image_provider="sd35",
        canonical_portrait_enabled=True,    # portrait is the subject reference
        image_pregen_enabled=False,         # no action stills
        face_restoration_enabled=False,
        pin_portrait_at_frame_zero=False,   # Phantom uses ref image, not frame pin
        pin_action_stills=False,
        pin_last_frame_chain=True,          # prev-scene last frame fed as extra Phantom ref (not a frame pin)
        drop_last_frame_on_tail=True,       # stop after scene 3 to limit cumulative subject drift
        visual_director_far_camera=True,
        visual_director_identity_echo=False, # Phantom locks identity itself
        provider_settings={
            "task": "s2v-14B",
            "width": 832,
            "height": 480,
            "num_frames": 65,
            "fps": 16,
            "steps": 30,
            "guidance_text": 7.5,
            "guidance_img": 5.0,
        },
        vram_min_gb=16,
        recommended_for="Identity-critical ads (faces, brand mascots)",
    ),
    "wan_phantom_actions": PipelineProfile(
        name="wan_phantom_actions",
        description="Phantom-Wan 14B with portrait + per-second action ref "
                    "images (up to 4 total).",
        video_provider="wan_phantom",
        audio_provider="chatterbox",
        image_provider="sd35",
        canonical_portrait_enabled=True,
        image_pregen_enabled=True,           # action stills generated
        face_restoration_enabled=False,
        pin_portrait_at_frame_zero=False,
        pin_action_stills=True,              # passed as additional ref images
        pin_last_frame_chain=False,
        drop_last_frame_on_tail=False,
        visual_director_far_camera=True,
        visual_director_identity_echo=False,
        provider_settings={
            "task": "s2v-14B",
            "width": 832,
            "height": 480,
            "num_frames": 81,
            "fps": 16,
            "steps": 30,
            "guidance_text": 7.5,
            "guidance_img": 5.0,
        },
        vram_min_gb=16,
        recommended_for="Brand mascots with specific poses / product placements",
    ),
}

DEFAULT_PROFILE = "wan22_text_only"


def get_profile(name: str | None) -> PipelineProfile:
    """Look up a profile by name. Falls back to DEFAULT_PROFILE if name is None
    or empty. Raises if name is unknown — callers should validate before save."""
    if not name:
        return PROFILES[DEFAULT_PROFILE]
    if name not in PROFILES:
        raise ValueError(
            f"Unknown pipeline profile: {name!r}. "
            f"Choices: {sorted(PROFILES)}"
        )
    return PROFILES[name]


def list_profiles() -> list[dict[str, Any]]:
    """For GET /api/pipelines — returns minimal metadata for the FE dropdown."""
    return [
        {
            "name": p.name,
            "description": p.description,
            "video_provider": p.video_provider,
            "vram_min_gb": p.vram_min_gb,
            "recommended_for": p.recommended_for,
        }
        for p in PROFILES.values()
    ]
