# Troubleshooting

## Startup

**`/api/readiness` returns 503** — DB or Redis is unreachable. Check
`docker compose ps`, `DATABASE_URL`, `REDIS_URL`. Run `alembic upgrade head`.

**`alembic upgrade head` fails** — DB not running, or `DATABASE_URL_SYNC` wrong.
Confirm Postgres is up and the database exists.

**Backend won't start / import errors** — wrong venv or missing deps. Re-run
`pip install -r requirements.txt` inside `backend/.venv`.

## Providers / GPU

**"No API key found"** — set `LLM_API_KEY` (or `OPENAI_API_KEY` in the vault), or
switch to `LLM_PROVIDER=stub` for offline dev.

**CUDA out of memory** — lower resolution/steps (`LTX_*` / `WAN22_*` / `SD35_*`),
or use `preview.sh` settings; ensure one Celery worker per GPU
(`--concurrency=1`).

**Model path not found** — a `WAN22_*` path or `MODELS_ROOT` points nowhere. Run
`python backend/scripts/download_models.py --all` and set `MODELS_ROOT`.

**Identity stills look generic / InstantID ignored** — the external InstantID
scripts in `INSTANTID_DIR` (`~/instantid`) are missing, so it falls back to
SD 3.5. Install them or set `INSTANTID_DIR`. See
[MODELS_AND_WEIGHTS.md](MODELS_AND_WEIGHTS.md).

**SD 3.5 download 401/403** — it's gated; `huggingface-cli login` or set
`HF_TOKEN`.

## Pipeline

**Scenes never finish** — is a Celery worker running and consuming the queue?
Check worker logs; confirm `CELERY_BROKER_URL` matches the API's Redis.

**FFmpeg errors during stitch** — install FFmpeg and ensure `FFMPEG_PATH` resolves.

**Stub mode produces blank/placeholder media** — expected: stub providers emit
placeholders. Switch to real providers for actual output.

## Docker

**`docker compose up` backend exits** — with the stub defaults it should boot
without GPU/keys; check `docker compose logs backend`. Ensure db/redis are healthy.

Still stuck? Open an issue using the bug template (scrub secrets first).
