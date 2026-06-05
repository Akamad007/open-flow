# OpenFlow — AI Story-to-Video Generation

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![Status: alpha](https://img.shields.io/badge/status-alpha-orange.svg)](#status)

OpenFlow turns a long-form story into a narrated, cinematic video through a
multi-agent pipeline: an LLM plans the scenes, diffusion/video models render the
clips, a TTS model narrates, and FFmpeg stitches the final MP4.

> **Status:** alpha. It works end-to-end but is young and GPU-heavy. Read
> [ETHICAL_USE.md](ETHICAL_USE.md) before generating any human likeness, and
> [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md) before commercial use.

## Architecture

```
Story Text → Story Analyst → Scene Planner → Visual Director → Consistency Critic
                                   ↓               ↓                    ↓
                           Audio Director    Video Generation    Quality Review
                                   ↓               ↓
                           Full-Story Audio   Scene Videos
                                   ↓               ↓
                                   └──── Stitching Agent ────→ Final MP4
```

| Agent | Responsibility |
|---|---|
| **Story Analyst** | Extract beats, characters, locations, arcs from raw text |
| **Scene Planner** | Break the story into ~5-second cinematic scenes with timing |
| **Visual Director** | Write detailed per-scene video-generation prompts |
| **Audio Director** | Plan one continuous narration track for the whole story |
| **Consistency Critic** | Catch identity drift, continuity errors, timing mismatches |
| **Asset Orchestrator** | Drive video/audio generation with retries + status tracking |
| **Stitching Agent** | Assemble clips + audio into the final synchronized MP4 |

**Design choices:** continuous audio (not per-scene), timing-synced stitching,
and pluggable providers for LLM / video / audio / image / stitching — including
**stub providers so the whole pipeline runs with no GPU, no weights, no keys.**

## Quick start — no GPU (≈1 minute)

```bash
cp .env.stub .env
docker compose up -d db redis          # Postgres + Redis only

cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
python seed_data.py                     # sample project
uvicorn app.main:app --reload --port 8002

# new terminal — Celery worker
celery -A app.orchestration.tasks:celery_app worker --loglevel=info

# new terminal — frontend
cd frontend && npm install && npm run dev
```

- Frontend: http://localhost:5173
- API + docs: http://localhost:8002/docs
- Health / readiness: `/api/health`, `/api/readiness`

Everything runs on CPU in stub mode (placeholder media). To produce real video,
switch on the GPU providers below.

## Full GPU setup

1. Hardware: NVIDIA GPU, **16 GB+ VRAM** recommended (validated on a 5070 Ti).
2. Get the weights: see **[docs/MODELS_AND_WEIGHTS.md](docs/MODELS_AND_WEIGHTS.md)**
   (`python backend/scripts/download_models.py --all`).
3. In `.env`, set providers and keys:
   ```dotenv
   LLM_PROVIDER=openai      LLM_API_KEY=sk-...      # or a local Ollama/vLLM endpoint
   VIDEO_PROVIDER=wan22     # or ltx
   AUDIO_PROVIDER=chatterbox
   IMAGE_PROVIDER=sd35      HF_TOKEN=hf_...          # SD 3.5 is gated
   MODELS_ROOT=/path/to/models
   ```
4. Full env-var reference: **[docs/ENVIRONMENT_VARIABLES.md](docs/ENVIRONMENT_VARIABLES.md)**.

See **[docs/INSTALL.md](docs/INSTALL.md)** for the detailed install and
**[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)** for production notes.

## Tech stack

- **Backend:** Python 3.11+ · FastAPI · SQLAlchemy 2.0 (async) · Alembic · Celery
- **Frontend:** TypeScript · React · Vite
- **Infra:** PostgreSQL · Redis · FFmpeg
- **AI:** OpenAI-compatible LLM · LTX-Video / Wan 2.2 · Stable Diffusion 3.5 ·
  InstantID · GFPGAN/CodeFormer · Chatterbox TTS

## Providers

Each capability is a swappable provider; `stub` needs no GPU/keys.

| Capability | Options |
|---|---|
| LLM | `openai` (OpenAI / Ollama / vLLM) · `stub` |
| Video | `wan22` · `ltx` · `stub` |
| Audio | `chatterbox` · `stub` |
| Image | `sd35` · `stub` |

Add one by implementing the base class in `backend/app/providers/<kind>/` and
registering it in the provider factory. See [CONTRIBUTING.md](CONTRIBUTING.md).

## API

Interactive docs at `/docs`. Common triggers (full list in
[docs/API_REFERENCE.md](docs/API_REFERENCE.md)):

- `POST /api/projects/{id}/analyze` — run story analysis
- `POST /api/projects/{id}/plan-scenes` — scene breakdown
- `POST /api/projects/{id}/generate-prompts` — visual prompts
- `POST /api/projects/{id}/generate-all` — run the whole pipeline
- `POST /api/projects/{id}/stitch` — stitch the final MP4

## Project structure

```
openflow/
├── backend/
│   ├── app/
│   │   ├── agents/         # pipeline agents
│   │   ├── api/            # FastAPI routers
│   │   ├── providers/      # pluggable LLM / video / audio / image / stitching
│   │   ├── orchestration/  # pipeline + Celery tasks
│   │   ├── models/         # SQLAlchemy ORM
│   │   ├── schemas/        # Pydantic schemas
│   │   └── security.py     # optional API-key auth
│   ├── scripts/            # operator tools (download_models.py, …)
│   ├── seed_data.py
│   └── tests/
├── frontend/src/           # React app (api/, components/, pages/, types/)
└── docs/
```

## Documentation

- [docs/INSTALL.md](docs/INSTALL.md) · [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)
- [docs/ENVIRONMENT_VARIABLES.md](docs/ENVIRONMENT_VARIABLES.md) · [docs/MODELS_AND_WEIGHTS.md](docs/MODELS_AND_WEIGHTS.md)
- [docs/API_REFERENCE.md](docs/API_REFERENCE.md) · [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)

## Contributing & security

- [CONTRIBUTING.md](CONTRIBUTING.md) · [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)
- Security policy & hardening: [SECURITY.md](SECURITY.md)
- Responsible use: [ETHICAL_USE.md](ETHICAL_USE.md) · [CONTENT_SAFETY.md](CONTENT_SAFETY.md)

## License

[MIT](LICENSE) for the application code. Bundled/driven models carry their own
licenses — see [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md).
