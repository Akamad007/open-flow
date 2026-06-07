# Running OpenFlow with Docker

Two stacks ship in the repo:

| | Command | What you get | Needs |
|---|---|---|---|
| **Full GPU** | `make gpu` | Postgres + Redis, **downloads Wan2.2**, migrates, API + GPU worker + UI — real video rendering | NVIDIA GPU + toolkit |
| **CPU / stub** | `make up` | Same services, stub providers — explore the UI/API with no GPU, no downloads | Docker only |

Both are a single command. The full stack is `docker compose -f docker-compose.gpu.yml up --build` under the hood.

## Full GPU stack (one command)

```bash
make gpu          # == docker compose -f docker-compose.gpu.yml up --build
```

On first run this will, in order:
1. Start **Postgres** and **Redis** (named volumes, healthchecked).
2. `model-init` — download **Wan2.2 TI2V-5B** weights into the `models` volume (large; one-time).
3. `migrate` — `alembic upgrade head` to create the schema.
4. Start the **backend** API, the **GPU worker** (`-Q cpu,gpu0`, one GPU), and the **frontend**.

Then open:
- UI → http://localhost:5173
- API docs → http://localhost:8000/docs

Subsequent runs reuse the cached image and the downloaded weights — they start fast.

### Host prerequisites (GPU stack only)
- An NVIDIA GPU + recent driver.
- **nvidia-container-toolkit** so containers can see the GPU:
  ```bash
  # Ubuntu/Debian
  sudo apt-get install -y nvidia-container-toolkit
  sudo nvidia-ctk runtime configure --runtime=docker
  sudo systemctl restart docker
  ```
  Verify: `docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi`.
- Enough disk for the CUDA image + Wan2.2 weights, and enough VRAM for TI2V-5B.

### Optional keys (`.env.docker`)
Real Wan2.2 video works out of the box. To enable the rest, edit `.env.docker`
(the `make` targets create it from `.env.docker.example` on first run):
- `LLM_PROVIDER=openai` + `LLM_API_KEY=…` → real story analysis (else a stub planner runs).
- `IMAGE_PROVIDER=sd35` + `HF_TOKEN=…` → real character stills (SD3.5 is a gated HF repo).
- `AUDIO_PROVIDER=chatterbox` → real narration.

The Docker stacks read **only `.env.docker`** (via `--env-file`), never your local
dev `.env` — so developer secrets and `/home/akash` paths can't leak into the
containers. Run the raw command the same way if you skip `make`:
`docker compose --env-file .env.docker -f docker-compose.gpu.yml up --build`.

### Not included in Docker
- **InstantID identity** (same face across poses) needs an external repo — it's disabled
  (`IDENTITY_PROVIDER_ENABLED=false`). Wan2.2 base rendering doesn't need it.
- **Multi-GPU routing** — the container uses a single GPU (`gpu0`). The bare-metal
  `scripts/start_all.sh` path handles per-GPU workers.

## CPU / stub stack

```bash
make up           # == docker compose up --build
```

Same five services with `*_PROVIDER=stub`, so the full pipeline runs end-to-end
(analyze → plan → prompt → video → audio → stitch) producing placeholder media —
useful for trying the API/UI on a laptop. No GPU, no model download.

## Common operations
```bash
make gpu-logs                                   # tail backend + worker
docker compose -f docker-compose.gpu.yml down   # stop (keep volumes)
docker compose -f docker-compose.gpu.yml down -v # stop + delete db/models/storage
```

## Troubleshooting
- **`could not select device driver … gpu`** → nvidia-container-toolkit isn't installed/configured (see above).
- **Worker idle, project stuck on "analyzing"** → the worker must consume both `cpu` and `gpu0`; the bundled command already does (`-Q cpu,gpu0`).
- **`column … does not exist` / `relation … does not exist`** → the `migrate` service didn't run; `docker compose -f docker-compose.gpu.yml run --rm migrate`.
- **Re-download weights** → `docker compose -f docker-compose.gpu.yml down -v` wipes the `models` volume (also wipes the DB).
