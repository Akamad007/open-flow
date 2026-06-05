# Environment Variables

All configuration is read by `backend/app/config.py` (pydantic-settings) from the
environment and/or a `.env` file. Variable names are case-insensitive. Start from
[`.env.example`](../.env.example) (full GPU) or [`.env.stub`](../.env.stub) (no GPU).

## Core

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://…/storyvideo` | Async DB DSN |
| `DATABASE_URL_SYNC` | `postgresql://…/storyvideo` | Sync DSN (Alembic) |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis |
| `CELERY_BROKER_URL` / `CELERY_RESULT_BACKEND` | redis db 0 / 1 | Celery |
| `STORAGE_ROOT` | `<backend>/storage` | Generated assets root |
| `BACKEND_HOST` / `BACKEND_PORT` | `0.0.0.0` / `8000` | Uvicorn bind (`start_all.sh` uses 8002) |
| `CORS_ORIGINS` | `["http://localhost:5173"]` | Allowed origins (JSON list) |

## Security

| Variable | Default | Description |
|---|---|---|
| `API_KEY` | `""` | When set, all `/api` routes require `X-API-Key`. Empty = disabled. |
| `SECRETS_MANAGER_URL` | `""` | Optional vault; empty = read keys from env |
| `SECRETS_MANAGER_TOKEN` | `""` | DRF token for the vault |

## Providers

| Variable | Default | Options |
|---|---|---|
| `LLM_PROVIDER` | `openai` | `openai`, `stub` |
| `VIDEO_PROVIDER` | `stub` | `wan22`, `ltx`, `stub` |
| `AUDIO_PROVIDER` | `stub` | `chatterbox`, `stub` |
| `IMAGE_PROVIDER` | `sd35` | `sd35`, `stub` |

## LLM

| Variable | Default | Description |
|---|---|---|
| `LLM_API_BASE` | `https://api.openai.com/v1` | OpenAI-compatible endpoint (Ollama/vLLM too) |
| `LLM_MODEL` / `LLM_STRONG_MODEL` | `gpt-4o-mini` | Models (strong used by visual director) |
| `LLM_API_KEY` | `""` | Fallback when the vault is not configured |

## Models & weights

| Variable | Default | Description |
|---|---|---|
| `MODELS_ROOT` | `<repo>/models` | Parent dir for downloaded weights |
| `WAN22_MODEL_PATH` / `WAN22_MOTION_MODEL_PATH` / `WAN22_LORA_DIR` | under `MODELS_ROOT/wan22` | Override per path |
| `HF_TOKEN` | `""` | Required for gated SD 3.5 |
| `CHATTERBOX_REFERENCE_AUDIO` | `<repo>/storage/audio/narrator_reference.wav` | TTS voice reference |
| `INSTANTID_DIR` | `~/instantid` | External InstantID scripts dir |

## Tuning & gating

| Variable | Default | Description |
|---|---|---|
| `LTX_*` / `WAN22_*` / `SD35_*` | see `config.py` | Resolution, frames, steps, guidance |
| `IDENTITY_PROVIDER_ENABLED` | `true` | Use InstantID for identity stills |
| `INSTANTID_DAEMON_ENABLED` | `true` | Persistent per-GPU daemon |
| `IMAGE_PREGEN_ENABLED` | `false` | Pre-generate stills (off: pure text-to-video) |
| `CONSISTENCY_GATE_ENABLED` | `true` | Fail pipeline on unresolved consistency verdict |
| `FFMPEG_PATH` | `ffmpeg` | FFmpeg binary |

The source of truth is always `backend/app/config.py`.
