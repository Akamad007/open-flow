# Deployment

OpenFlow was built as a single-operator tool. Treat any networked deployment as
security-sensitive — read [SECURITY.md](../SECURITY.md) first.

## Topology

- **API** (FastAPI/uvicorn) — stateless; scale horizontally behind a proxy.
- **Celery workers** — do the GPU work. Run **one worker per GPU**
  (`--concurrency=1`) and route projects to GPU queues. Workers are the only
  components that need the model weights and CUDA.
- **PostgreSQL** + **Redis** — state and broker/result backend.
- **Frontend** — static build served by any web server / CDN.

## Containers

`docker compose up` brings up db, redis, backend, worker, and frontend. Defaults
to **stub** providers so it boots with no GPU. For GPU, run workers on GPU hosts
(the stock `worker` service has no CUDA runtime configured — add
`deploy.resources.reservations.devices` / `runtime: nvidia` and a CUDA base
image, or run workers outside compose on the GPU box).

## Production checklist

- [ ] Set `API_KEY` and send it as `X-API-Key`; never expose the API unauthenticated.
- [ ] Restrict `CORS_ORIGINS` to your real frontend origin(s).
- [ ] Terminate TLS at a reverse proxy (nginx/Caddy/traefik).
- [ ] Provide real `DATABASE_URL` / `REDIS_URL`; do not rely on the demo creds.
- [ ] Put secrets in your platform's secret store or the secrets-manager — not in
      a committed file. `.env` is gitignored.
- [ ] Mount model weights as a read-only volume (`MODELS_ROOT`); don't bake them
      into images.
- [ ] Protect `~/.video-app/youtube_oauth.json` (plaintext refresh token).
- [ ] Health checks: liveness `/api/health`, readiness `/api/readiness`.
- [ ] Back up Postgres and the `storage/` volume.

## Scaling notes

- Add GPU workers to add render throughput; the queue spreads scenes across them.
- The API and workers are decoupled — restart workers to pick up new model paths
  without downtime on the API.
