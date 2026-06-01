# StoryVideo — Multi-Agent Story-to-Video Generation System

A production-quality MVP for converting long-form stories into cinematic videos using a multi-agent AI pipeline.

## Architecture

```
Story Text → Story Analyst → Scene Planner → Visual Director → Consistency Critic
                                    ↓              ↓                    ↓
                            Audio Director    Video Generation    Quality Review
                                    ↓              ↓
                            Full-Story Audio  Scene Videos
                                    ↓              ↓
                                    └──── Stitching Agent ────→ Final MP4
```

### Agents
| Agent | Responsibility |
|---|---|
| **Story Analyst** | Extract beats, characters, locations, emotional arcs from raw text |
| **Scene Planner** | Break story into ~4-second cinematic scenes with timing |
| **Visual Director** | Generate highly detailed video generation prompts per scene |
| **Audio Director** | Create one continuous audio plan for the full story |
| **Consistency Critic** | Review for identity drift, continuity errors, timing mismatches |
| **Asset Orchestrator** | Manage video/audio generation with retries and status tracking |
| **Stitching Agent** | Assemble scene clips + audio into final synchronized MP4 |

### Key Design Decisions
- **Audio is continuous**: One uninterrupted audio track for the full story, not per-scene clips
- **Timing synchronization**: Scene durations are coordinated with the audio plan so stitching produces a naturally synced result
- **Provider abstraction**: Video, audio, LLM, and stitching all use pluggable provider interfaces
- **Stub providers included**: Run the full pipeline without GPU/LLM by using stub providers

## Tech Stack

- **Backend**: Python 3.11+ / FastAPI / SQLAlchemy 2.0 / Alembic / Celery
- **Frontend**: TypeScript / React / Vite
- **Database**: PostgreSQL
- **Queue**: Redis + Celery
- **Media**: FFmpeg
- **LLM**: OpenAI-compatible API (Ollama, vLLM, cloud)

## Quick Start with Docker

```bash
# Clone and start all services
cp .env.example .env
docker compose up --build

# In another terminal, run migrations and seed data
docker compose exec backend alembic upgrade head
docker compose exec backend python seed_data.py
```

- **Frontend**: http://localhost:5173
- **Backend API**: http://localhost:8000
- **API Docs**: http://localhost:8000/docs

## Local Development (without Docker)

### Prerequisites
- Python 3.11+
- Node.js 20+
- PostgreSQL 15+
- Redis 7+
- FFmpeg

### Backend
```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Create database
createdb storyvideo

# Copy and edit env
cp ../.env.example .env

# Run migrations
alembic upgrade head

# Seed sample data
python seed_data.py

# Start API server
uvicorn app.main:app --reload --port 8000

# Start Celery worker (separate terminal)
celery -A app.orchestration.tasks:celery_app worker --loglevel=info
```

### Frontend
```bash
cd frontend
npm install
npm run dev
```

## Configuration

All settings are configured via environment variables or `.env` file:

| Variable | Default | Description |
|---|---|---|
| `LLM_PROVIDER` | `stub` | `openai` for real LLM, `stub` for mock |
| `LLM_API_BASE` | `http://localhost:11434/v1` | OpenAI-compatible API endpoint |
| `LLM_MODEL` | `llama3.1:8b` | Model name |
| `VIDEO_PROVIDER` | `stub` | `ltx` for LTX-Video, `stub` for placeholder |
| `AUDIO_PROVIDER` | `stub` | `stub` generates silence |

## Provider Abstraction

### Adding a new video provider
1. Create a class extending `VideoProvider` in `backend/app/providers/video/`
2. Implement `generate_video()`, `get_status()`, `cancel()`
3. Register it in `pipeline.py`'s `get_video_provider()`

### Using a real LLM
Set `LLM_PROVIDER=openai` and configure `LLM_API_BASE` to point at your LLM server:
- **Ollama**: `http://localhost:11434/v1`
- **vLLM**: `http://localhost:8001/v1`
- **OpenAI**: `https://api.openai.com/v1` (set `LLM_API_KEY`)

## API Endpoints

All endpoints are documented at `http://localhost:8000/docs` (Swagger UI).

Key generation triggers:
- `POST /api/projects/{id}/analyze` — Run story analysis
- `POST /api/projects/{id}/plan-scenes` — Generate scene breakdown
- `POST /api/projects/{id}/generate-prompts` — Generate visual prompts
- `POST /api/projects/{id}/plan-audio` — Generate audio plan
- `POST /api/projects/{id}/generate-videos` — Generate video clips
- `POST /api/projects/{id}/generate-audio` — Generate full-story audio
- `POST /api/projects/{id}/stitch` — Stitch final video
- `POST /api/projects/{id}/generate-all` — Run full pipeline

## Project Structure

```
video-app/
├── backend/
│   ├── app/
│   │   ├── agents/         # 7 pipeline agents
│   │   ├── api/            # FastAPI routers
│   │   ├── models/         # SQLAlchemy ORM models
│   │   ├── orchestration/  # Pipeline + Celery tasks
│   │   ├── prompts/        # LLM prompt templates
│   │   ├── providers/      # Pluggable backends (LLM, video, audio, stitching)
│   │   └── schemas/        # Pydantic schemas
│   └── alembic/            # Database migrations
├── frontend/
│   └── src/
│       ├── api/            # API client
│       ├── components/     # React components
│       ├── pages/          # Page components
│       └── types/          # TypeScript types
└── docker-compose.yml
```

## License

MIT
