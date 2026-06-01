# Event log — design doc

## Problem

There's no project-scoped history. When something fails or behaves oddly,
the only trail is:

- `backend/celery.log` / `celery-cpu.log` — line noise across ALL projects;
  grepping by project_id works but is awkward.
- `render_jobs` table — only captures heavyweight stage jobs, not per-action
  events (user-triggered regens, LLM call failures, asset creation, vision
  critic verdicts).
- Asset `metadata_json` — verdicts stashed here, but you have to know which
  asset to look at.

You want a **single chronological feed per project** (and per episode) so
you can answer: *"what happened to this project today?"* without grepping
log files.

## Goals (P0)

1. One `project_events` table — append-only, indexed by `(project_id, ts desc)`.
2. Every pipeline stage emits start / end / fail events.
3. User-initiated actions (regen, upload, status changes) emit events.
4. Asset-level milestones (scene video generated, audio done, render stitched)
   emit events.
5. REST endpoint to fetch a project's events with filtering.
6. UI tab on the project page showing the feed.

## Non-goals (P1, deferred)

- Live tail via WebSocket / SSE. Phase 1 is REST poll.
- Wrap every LLM call individually. Phase 1 emits one event per LLM **batch**,
  not per request.
- Retention policy / pruning. Acceptable to keep all events for now —
  rough math: ~500 events × 30 projects × 1KB = ~15 MB. Decide later.
- Cross-project search / filtering UI. Per-project is enough for P0.

## Schema

```python
class EventLevel(str, enum.Enum):
    debug = "debug"
    info  = "info"
    warn  = "warn"
    error = "error"


class ProjectEvent(Base):
    __tablename__ = "project_events"

    id          = UUID, pk
    project_id  = UUID FK projects(id), CASCADE, INDEXED
    episode_id  = UUID FK episodes(id), CASCADE, nullable, INDEXED
    scene_id    = UUID FK scenes(id),   CASCADE, nullable
    asset_id    = UUID FK assets(id),   SET NULL, nullable

    event_type  = String(60)        # e.g. "stage.start", "scene.generated"
    level       = Enum(EventLevel)
    stage       = String(40), nullable      # "prompt_generation" / "scene_video" / ...
    actor       = String(40)        # "celery:gpu", "api:user", "system"

    summary     = String(500)       # one-line human readable
    payload_json= Text, nullable    # extra structured data — truncated to ~4KB
    duration_ms = Integer, nullable
    error       = Text, nullable    # exception text on failures

    created_at  = DateTime(tz=true), default now(), INDEXED (DESC composite with project_id)
```

Indexes:
- `(project_id, created_at desc)` — primary feed query
- `(episode_id)` partial where not null — episode-scoped feed
- `(event_type)` — type filter

## Event type catalog (canonical strings)

Naming: dotted `noun.verb`. Past tense for completed actions.

| event_type                       | when                                 |
|----------------------------------|--------------------------------------|
| `pipeline.started`               | full_pipeline task picks up project  |
| `pipeline.completed`             | full_pipeline ends with no error     |
| `pipeline.failed`                | full_pipeline ends in exception      |
| `stage.started`                  | individual stage run() entry         |
| `stage.completed`                | individual stage run() success       |
| `stage.failed`                   | individual stage caught an exception |
| `scene.generated`                | scene_video produced asset           |
| `scene.regen_requested`          | user clicked "regenerate"            |
| `scene.critic_verdict`           | video critic finished                |
| `asset.created`                  | any new asset row                    |
| `prompt.assigned_lora`           | LoRA director persisted plans        |
| `episode.stitched`               | final_render produced                |
| `youtube.upload.started`         | upload-to-youtube task picked up     |
| `youtube.upload.completed`       | upload OK                            |
| `youtube.upload.failed`          | upload failed                        |
| `user.action`                    | generic user-initiated event         |

Adding new types is just a new string — no migration.

## Emit helper

```python
# app/utils/events.py
async def emit_event(
    *,
    project_id: UUID,
    event_type: str,
    summary: str,
    level: EventLevel = EventLevel.info,
    stage: str | None = None,
    episode_id: UUID | None = None,
    scene_id: UUID | None = None,
    asset_id: UUID | None = None,
    payload: dict | None = None,
    duration_ms: int | None = None,
    error: str | None = None,
    actor: str = "celery",
    db: AsyncSession | None = None,
) -> None:
    """Write a ProjectEvent. If `db` is given, uses that session; otherwise
    opens a fresh one. Fresh-session mode is preferred for failure paths so
    the event survives a rollback of the caller's transaction."""
```

Two modes intentional:
- **Same-session (pass `db`)** — happy path. Event commits with stage data.
  Cheap, atomic. Risk: rolled back on failure.
- **Fresh-session (no `db`)** — failure path. Event is durable independent
  of caller's transaction state.

## Where it gets called (P0 wiring)

| location                                            | events emitted                                 |
|-----------------------------------------------------|------------------------------------------------|
| `orchestration/tasks/pipeline.py:full_pipeline`     | pipeline.started / .completed / .failed       |
| each `orchestration/stages/*.run()`                 | stage.started / .completed / .failed          |
| `orchestration/stages/scene_video.py:_generate_one` | scene.generated, scene.critic_verdict         |
| `orchestration/stages/prompt_generation.py:_assign_loras` | prompt.assigned_lora                    |
| `orchestration/stages/stitching.py`                 | episode.stitched                              |
| `orchestration/tasks/youtube_upload.py`             | youtube.upload.started / .completed / .failed |
| `api/scenes.py` regen endpoints                     | scene.regen_requested                         |
| `api/projects.py` status mutations                  | user.action                                   |

## API

```
GET /api/projects/{project_id}/events
  ?episode_id=...           # filter by episode
  &since=ISO8601            # only events after this timestamp
  &until=ISO8601            # only events before this timestamp
  &level=info|warn|error    # comma-separated allowed levels
  &event_type=stage.failed  # exact match (one type for now)
  &stage=scene_video        # filter by stage
  &limit=100                # default 100, max 500
  &order=desc               # desc (newest first) | asc
```

Response: `{items: [Event, ...], next_cursor: <timestamp or null>}`

## UI (frontend)

New tab on project page: **"Events"**.
- Reverse-chronological list.
- Each row: `timestamp · level icon · event_type · stage · summary`
- Click row → expand to show payload_json + error.
- Top bar: filter chips (level: warn+error / all), search by stage.
- Auto-refresh: poll every 5 s when project status is `prompting / generating / stitching`.

## --- SELF-CRITIQUE ---

### 1. Redundancy vs. celery logs

The celery logs already capture stage starts/ends + tracebacks. Why double-write?

**Answer:** the celery logs are time-ordered across **all** projects. Filtering
by project_id with grep works for a power-user but not for the UI. The DB
table is a **higher-signal subset**, scoped to one project, queryable from the
frontend without shelling in. Volume is small (~500 events / project) so storage
cost is negligible.

### 2. Schema bloat from payload_json

Stashing full LLM prompts or stack traces in `payload_json` will balloon the
table.

**Mitigation:** cap `payload_json` at 4 KB (truncate at emit time with a
"`...[truncated]`" marker). Stack traces go in `error` field, capped at
8 KB. Full LLM payloads live in their canonical homes (ScenePrompt for
prompts, asset.metadata_json for critic verdicts) — `payload_json` only
holds **references** (asset_id, job_id) plus tiny structured summaries.

### 3. Hot-path latency

Adding an INSERT per stage start + end is cheap. But if we naively wrap every
LLM call inside `visual_director.run_batch`, that's 50+ INSERTs per batch of
50 scenes (or more with retries).

**P0 stance:** emit **only at batch boundaries**, not per LLM call. One event
"prompt.assigned_lora — 89 scenes in 2 batches" is more useful than 50 noisy
individual call events.

### 4. Fresh-session vs same-session for emit

If a stage's transaction rolls back, its `stage.started` event rolls back
too — we end up with a `stage.failed` but no matching `started`.

**P0 decision:** use **fresh session** for emit_event by default. Slightly
more DB connection churn but the events are then independent and complete.
For very hot loops we may opt into the shared-session mode later.

### 5. Cardinality on `event_type`

Free-form string allows fast iteration but no schema-level guarantee that
event types are stable. Typos slip through.

**Mitigation:** define canonical strings as constants in `app/utils/events.py`:
```python
class EventType:
    PIPELINE_STARTED = "pipeline.started"
    STAGE_STARTED = "stage.started"
    ...
```
Callers reference the constant; lint catches typos.

### 6. Duration measurement

Where do we time stages? Decorating each `run()` with a context manager is
ideal but invasive.

**P0:** time inline in each stage:
```python
import time
t0 = time.monotonic()
await emit_event(... event_type="stage.started")
try:
    ...do work...
    await emit_event(... event_type="stage.completed",
                     duration_ms=int((time.monotonic()-t0)*1000))
except Exception as e:
    await emit_event(... event_type="stage.failed",
                     duration_ms=int((time.monotonic()-t0)*1000),
                     error=str(e))
    raise
```
Adds ~6 lines per stage. We have 7 stages. Total: 1 small refactor, no new
abstractions.

### 7. Migration risk

Adding a new table with FKs to busy tables (projects, episodes, scenes, assets)
takes an AccessExclusiveLock on those during FK creation. We just saw the
last ALTER block on a stuck idle-in-transaction.

**Mitigation:** the migration only adds **one new table** with FK constraints.
No ALTER on existing tables. FK constraint creation on the new table doesn't
lock the parent tables for writes — it just takes a brief ShareLock.

### 8. P0 cuttable scope

If shipping today only — cut UI, ship API + emit hooks. You get a queryable
history via curl while the UI lands later. Open question: do you want the
UI in this iteration or just the backend?

## Open questions for you

1. **UI in this iteration?** Or backend-only + curl, ship UI next pass?
2. **Retention:** keep forever (default) or auto-prune events older than 30 days?
3. **What level of detail per LLM call?** Batch-summary is my recommendation.
   Per-call would be ~50× more rows for marginal value.
4. **Should the `events` API endpoint be paginated by cursor (timestamp) or
   offset/limit?** Cursor is more correct for append-only data but a bit
   more code. P0 default: offset/limit, swap to cursor if pagination edge
   cases bite.

## Phasing plan

- **P0 (this PR):** schema + migration + emit helper + wired into the 7 stages
  + asset milestones + REST endpoint. ~6 files touched, no UI.
- **P1:** UI tab + auto-refresh poll + filter chips.
- **P2:** WebSocket live stream + LLM-call-level events (opt-in flag).
