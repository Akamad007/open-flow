"""
Application configuration via environment variables.
Uses pydantic-settings for typed, validated config.
"""

import os
from pathlib import Path
from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo root (…/video-app) and the external model store, both overridable via
# env. Keeping these env-driven is what lets the app run on a machine that is
# not the original developer's. MODELS_ROOT defaults to <repo>/models; point it
# at wherever the multi-GB weights live (see docs/MODELS_AND_WEIGHTS.md).
_REPO_ROOT = Path(__file__).resolve().parents[2]
_MODELS_ROOT = Path(os.getenv("MODELS_ROOT", str(_REPO_ROOT / "models")))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # ── Database ──
    database_url: str = "postgresql+asyncpg://storyvideouser:storyvideopass@localhost:5432/storyvideo"
    database_url_sync: str = "postgresql://storyvideouser:storyvideopass@localhost:5432/storyvideo"

    # ── Redis ──
    redis_url: str = "redis://localhost:6379/0"

    # ── Storage ──
    storage_root: Path = Path(__file__).parent.parent / "storage"

    # ── Secrets Manager (runtime secret fetching) ──
    secrets_manager_url: str = "http://127.0.0.1:8010"
    secrets_manager_token: str = ""  # DRF auth token — set via SECRETS_MANAGER_TOKEN env var

    # ── LLM Provider ──
    llm_provider: str = "openai"  # openai | stub
    llm_api_base: str = "https://api.openai.com/v1"
    llm_api_key: str = ""  # Fallback only — prefer secrets-manager. Set via LLM_API_KEY env var
    llm_model: str = "gpt-5.4-nano"
    # Stronger model used by the visual_director (per-scene cinematography prompts).
    # Spending more on tokens here is net-positive because each prompt drives
    # ~$2 of GPU work downstream. Override via LLM_STRONG_MODEL env var.
    llm_strong_model: str = "gpt-5.4-nano"

    # ── Video Provider ──
    video_provider: str = "stub"  # ltx | wan22 | stub
    # Wan 2.2 TI2V-5B settings — empirically validated baseline (832×480, 121f, 40 steps, CFG 5.0).
    # Generates ~5s @ 24fps. LoRA + post-process picked per-scene by the provider's classifier
    # against backend/app/config/wan22_lora_catalog.yaml.
    wan22_model_path: str = str(_MODELS_ROOT / "wan22" / "TI2V-5B-Diffusers")
    # Motion-specialized fine-tune (UVA CV Lab). Used for motion scenes only —
    # see _is_motion_scene in wan22_provider.py. Falls back to wan22_model_path
    # if the path doesn't exist.
    wan22_motion_model_path: str = str(_MODELS_ROOT / "wan22" / "FrameINO-5B-MotionINO-v1.6")
    wan22_lora_dir: str = str(_MODELS_ROOT / "wan22" / "loras" / "5b")
    wan22_height: int = 384
    wan22_width: int = 640
    wan22_num_frames: int = 121  # 5.04s @ 24fps
    wan22_fps: int = 24
    wan22_inference_steps: int = 140   # flat 140 for all scenes (user pref 2026-05-27); motion bump is now 0
    wan22_guidance_scale: float = 5.0
    ltx_model_id: str = "Lightricks/LTX-Video"      # HF repo (all checkpoints live here)
    ltx_model_file: str = "ltxv-13b-0.9.8-dev-fp8.safetensors"  # dev fp8 — supports CFG, stronger text adherence
    ltx_device: str = "cuda"                         # single-GPU FP8 + sequential CPU offload (cuda:0)
    ltx_num_frames: int = 73                         # 8*9+1=73 ≈ 6.08s @ 12fps (LTX requires 8n+1)
    # F-V4-SWEETSPOT: 1280×768, 80 steps. Validated 2026-05-18 — face/anatomy
    # coherent at this pixel budget where 1024×576 / 30 steps produced
    # malformed faces. Wall time ~6-8 min/scene on a single 5070 Ti (FP8 +
    # sequential CPU offload), well within the celery-stage budget.
    ltx_width: int = 1280
    ltx_height: int = 768
    ltx_inference_steps: int = 80                    # dev: 60-80 — face/detail quality jumps measurably above 60
    ltx_guidance_scale: float = 3.5                  # dev CFG — 3.0-4.0 per ltx_generate.py default
    ltx_fps: int = 12                                # 12fps — 73 frames = 6.08s per clip
    ltx_face_restore: bool = True                    # run GFPGAN on the output mp4 before returning


    # ── Audio Provider ──
    audio_provider: str = "stub"  # chatterbox | stub
    chatterbox_reference_audio: Path = _REPO_ROOT / "storage" / "audio" / "narrator_reference.wav"
    chatterbox_max_chunk_chars: int = 500

    # ── Image Provider (SD 3.5 Medium) ──
    image_provider: str = "sd35"  # sd35 | stub
    sd35_model_id: str = "stabilityai/stable-diffusion-3.5-medium"
    sd35_steps: int = 95           # 95 for quality renders
    sd35_guidance: float = 7.5
    # F-LANDSCAPE-WIDE: char stills now match LTX 16:9 landscape too.
    # Stills are no longer LTX conditions (F-NO-STILL-PINS), so we don't
    # need the tall canvas to force head-to-toe — wider canvas gives more
    # environment context for the eval/preview previews.
    sd35_char_width: int = 1280
    sd35_char_height: int = 768
    sd35_bg_width: int = 1280
    sd35_bg_height: int = 720
    # Max regens when the vision-critic rejects a character portrait for
    # not being full-body / head-to-toe.
    portrait_critic_max_retries: int = 2
    # img2img strength for baking the product hero into per-second action
    # stills. Lower → SD3.5 freedom (better human anatomy/pose, weaker
    # product fidelity); higher → tighter product fidelity but pose
    # degrades. 0.65 was the calibration target in the product-placement
    # plan; tune from this default after first end-to-end run.
    product_img2img_strength: float = 0.65

    # Identity-locked action stills (InstantID-XL). When `True` and
    # ~/instantid/generate_instantid.py is installed, per-second action
    # stills route through SDXL+InstantID for face-identity preservation.
    # Falls back to SD3.5 t2i when disabled or the script is missing.
    # When pose reference is available, the dual-CN script (InstantID +
    # OpenPose SDXL) is used so body pose ALSO follows the scene action;
    # otherwise the face-only script biases the pose toward the portrait.
    identity_provider_enabled: bool = True
    # When true and the daemon script exists, InstantID dual-CN calls go
    # through a persistent per-GPU daemon (saves ~25 s/call vs cold-loading
    # the SDXL+CN stack each call). Falls back to the subprocess path on
    # any daemon error.
    instantid_daemon_enabled: bool = True
    identity_strength: float = 0.80   # tuned from smoke test (was 0.85)
    pose_strength: float = 0.65       # OpenPose ControlNet strength when dual-CN is active
    # External InstantID scripts dir (generate_instantid*.py, daemon). Not
    # bundled with this repo — install separately and point here. Override with
    # INSTANTID_DIR; defaults to ~/instantid for backward compatibility.
    instantid_dir: str = os.getenv("INSTANTID_DIR", str(Path.home() / "instantid"))
    hf_token: str = ""  # HF_TOKEN env var — required for SD 3.5


    # ── Pipeline gating ──
    # When True, an unresolved consistency-critic verdict (still
    # `approved=False` after correction passes) fails the pipeline instead
    # of advancing to image_pregen. Default True; set False for dev runs
    # where you want to observe the bad output downstream.
    consistency_gate_enabled: bool = True

    # F-TEXT-ONLY-LTX (iter6): when False, the image_pregen stage is a
    # no-op (returns immediately, sets project to next stage). LTX is now
    # pure text-to-video — character portrait, background plate, action
    # stills, and pose refs are no longer used as conditions, so spending
    # ~80% of pipeline runtime generating them is wasted GPU time. Set
    # IMAGE_PREGEN_ENABLED=true to re-enable still generation for UI
    # preview / hand-grading.
    image_pregen_enabled: bool = False

    # ── Stitching ──
    ffmpeg_path: str = "ffmpeg"

    # ── YouTube upload ──
    # Local file holding the OAuth refresh-token JSON written by
    # scripts/youtube_authorize.py. CLIENT_ID/CLIENT_SECRET still live in the
    # secrets-manager vault; only the per-channel auth state is on disk.
    youtube_oauth_path: Path = Path.home() / ".video-app" / "youtube_oauth.json"

    # ── GPU Python ── (python with torch/CUDA for LTX and Chatterbox)
    gpu_python_path: str = "python"  # Override with GPU_PYTHON_PATH env var

    # ── Server ──
    backend_host: str = "0.0.0.0"
    backend_port: int = 8000
    cors_origins: List[str] = Field(default=["http://localhost:5173"])

    # ── API security ──
    # When non-empty, every /api route requires an `X-API-Key: <value>` header.
    # Empty (default) = auth disabled — acceptable for a trusted LAN/dev box,
    # NOT for public exposure. See SECURITY.md.
    api_key: str = ""

    # ── Celery ──
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"

    def ensure_storage_dirs(self) -> None:
        """Create storage subdirectories if they don't exist."""
        for subdir in (
            "videos", "audio", "renders", "temp",
            "characters", "backgrounds", "scene_actions",
        ):
            (self.storage_root / subdir).mkdir(parents=True, exist_ok=True)


settings = Settings()
