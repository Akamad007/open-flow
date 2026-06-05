# API Reference

Interactive Swagger UI is always available at `/docs` (ReDoc at `/redoc`). This
page is a quick map of the pipeline endpoints. All paths are under `/api`.

If `API_KEY` is set, send `X-API-Key: <key>` on every request (health/readiness
and `/storage` are exempt).

## Health

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Liveness — process is up |
| GET | `/api/readiness` | Readiness — checks DB + Redis (503 if degraded) |

## Projects & pipeline

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/projects` | Create a project from story text |
| GET | `/api/projects/{id}` | Project + status |
| POST | `/api/projects/{id}/analyze` | Story analysis |
| POST | `/api/projects/{id}/plan-scenes` | Scene breakdown |
| POST | `/api/projects/{id}/generate-prompts` | Per-scene visual prompts |
| POST | `/api/projects/{id}/plan-audio` | Narration plan |
| POST | `/api/projects/{id}/generate-videos` | Render scene clips |
| POST | `/api/projects/{id}/generate-audio` | Synthesize narration |
| POST | `/api/projects/{id}/stitch` | Stitch final MP4 |
| POST | `/api/projects/{id}/generate-all` | Run the whole pipeline |

## Typical flow

```bash
# 1. create
curl -X POST localhost:8002/api/projects \
  -H 'Content-Type: application/json' \
  -d '{"title":"Demo","story_text":"Once upon a time..."}'

# 2. run everything (async; work runs on Celery)
curl -X POST localhost:8002/api/projects/<id>/generate-all

# 3. poll status
curl localhost:8002/api/projects/<id>
```

Generated assets are served under `/storage/...` and referenced from the project
and scene records. Other resource routers (episodes, scenes, characters,
locations, products, assets, uploads, youtube_uploads) are documented in `/docs`.
