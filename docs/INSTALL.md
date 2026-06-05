# Installation

Two paths: **stub mode** (no GPU, for development) and **full GPU** (real video).

## Prerequisites

- Python **3.11+**
- Node.js **20+**
- PostgreSQL **15+** and Redis **7+** (or use the bundled `docker compose`)
- FFmpeg on `PATH`
- GPU mode only: an NVIDIA GPU (16 GB+ VRAM recommended) with a recent CUDA driver

## 1. Database & Redis

```bash
docker compose up -d db redis      # easiest
# or install Postgres/Redis natively and create the DB:
#   createdb storyvideo
```

## 2. Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt          # add -r requirements-dev.txt for tests
cp ../.env.stub ../.env                   # stub mode; or ../.env.example for GPU
alembic upgrade head
python seed_data.py                       # optional sample data
uvicorn app.main:app --reload --port 8002
```

In a second terminal, start the Celery worker:

```bash
cd backend && source .venv/bin/activate
celery -A app.orchestration.tasks:celery_app worker --loglevel=info
```

## 3. Frontend

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173
```

## 4. (GPU mode) model weights

```bash
export MODELS_ROOT=/path/to/models
huggingface-cli login                     # for gated SD 3.5
python backend/scripts/download_models.py --all
```

Then set the real providers in `.env` (see
[ENVIRONMENT_VARIABLES.md](ENVIRONMENT_VARIABLES.md) and
[MODELS_AND_WEIGHTS.md](MODELS_AND_WEIGHTS.md)).

## Verify

```bash
curl localhost:8002/api/health       # {"status":"ok"}
curl localhost:8002/api/readiness    # {"status":"ready","checks":{...}}
```

Problems? See [TROUBLESHOOTING.md](TROUBLESHOOTING.md).
