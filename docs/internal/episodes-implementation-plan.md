# Episodes inside Projects — Implementation Plan

**Goal:** A project becomes a series. Each episode is a self-contained video
(its own story text, scenes, audio plan, stitched final). Episode 2+ continues
visually from the last frame of the previous episode's last scene.

The characters/locations/products live at the **project** level — they are the
shared cast/world the series reuses. Stories, scenes, audio, and final renders
live at the **episode** level.

---

## 1. Data model changes

### New table: `episodes`

```
id                            uuid pk
project_id                    uuid fk → projects(id) on delete cascade
order_index                   int   not null  (0-based within the project)
title                         varchar(500)   "Episode 1"
status                        episodestatus  (mirrors current ProjectStatus enum)
theme_hint                    text   null   (1-line theme prompt — e.g. "Tom traps Jerry with a giant cheese fan")
original_story_text           text   not null default ''   (full story, either user-supplied OR LLM-expanded from theme_hint)
target_duration_seconds       float  null
final_audio_duration_seconds  float  null
continue_from_previous        bool   not null default true  (whether to chain last-frame from prev episode)

story_summary                 text
beat_list_json                text
pacing_notes                  text
style_lock                    text
final_evaluation_json         text

final_video_path              varchar(1000)   null   (stitched output for this episode)
created_at / updated_at       timestamptz
unique (project_id, order_index)
```

`episodestatus` is the existing `ProjectStatus` enum reused — same lifecycle.

### Tables that move from project-scoped → episode-scoped

Add a non-null `episode_id` column (FK → episodes.id, ON DELETE CASCADE).
Keep `project_id` for query convenience.

- `scenes`                          (currently `project_id`)
- `audio_plan`                      (currently 1-to-1 with project → becomes 1-to-1 with episode)
- `assets` where `scene_id IS NULL` but logically per-episode (scene_video for stitched output, narration audio): add `episode_id NULLABLE` so existing scene-scoped assets stay scene-scoped, episode-scoped assets get `episode_id`.

### Tables that stay project-scoped

- `characters`, `locations`, `products`, `scene_characters`, `scene_products`
- `render_jobs` (could become episode-scoped if we want per-episode render history; recommend project-scoped to keep simple)

### Tables that depend on scene_id

`scene_prompts` stays under `scene_id` — no change.

### Migration (single alembic revision)

```python
def upgrade():
    # 1. create episodes table
    # 2. add episode_id nullable to scenes, audio_plan, assets
    # 3. backfill:
    #    for each project:
    #       insert episodes (project_id, order_index=0, title='Episode 1',
    #                        status=project.status,
    #                        original_story_text=project.original_story_text,
    #                        target_duration_seconds=project.total_target_duration_seconds,
    #                        final_audio_duration_seconds=project.final_audio_duration_seconds,
    #                        story_summary, beat_list_json, pacing_notes, style_lock,
    #                        final_evaluation_json)
    #       UPDATE scenes SET episode_id=<new id> WHERE project_id=<p.id>
    #       UPDATE audio_plan SET episode_id=<new id> WHERE project_id=<p.id>
    #       UPDATE assets SET episode_id=<new id>
    #              WHERE project_id=<p.id> AND scene_id IS NULL
    #                AND asset_type IN ('final_video','narration_audio','stitched_video')
    # 4. alter scenes.episode_id NOT NULL
    # 5. alter audio_plan.episode_id NOT NULL + drop project_id uniqueness, add unique(episode_id)
    # 6. retain projects.story_summary etc. as nullable for now — drop in a later revision after we confirm nothing reads them
```

The project-level story_text/beats columns become a soft-deprecated mirror of
episode 0. Don't drop them in the same revision — that's a separate cleanup
after the orchestrator no longer writes to them.

### ORM relationships

```
Project.episodes  = relationship(order_by=Episode.order_index, cascade=all, delete-orphan)
Episode.scenes    = relationship(order_by=Scene.order_index, cascade=all, delete-orphan)
Episode.audio_plan = relationship(uselist=False, cascade=all, delete-orphan)
Episode.assets    = relationship  (filter on episode_id)
Episode.previous  = property → query Episode.query.filter_by(project_id=..., order_index=self.order_index-1).first()
Project.characters / .locations / .products  unchanged
```

---

## 2. Orchestration / pipeline

### Stages become episode-scoped

Every stage that takes `project_id` today must accept `episode_id` instead.
The stages affected:

- `story_analysis`         (reads episode.original_story_text → writes episode.{summary,beats,pacing,style_lock})
- `scene_planning`         (writes scenes under episode_id)
- `prompt_generation`      (per-scene; already scene_id-driven, no change to inner logic — only the loop changes)
- `audio_planning`         (writes audio_plan row under episode_id)
- `audio_generation`       (produces narration assets tagged with episode_id)
- `image_pregen`            (canonical portraits remain project-scoped — they're per-character; scene action stills are per-scene, already fine)
- `canonical_portrait`     (project-scoped, runs once for the project not per episode)
- `consistency_review`     (episode-scoped — reviews scenes of this episode only)
- `scene_video`            (episode-scoped — see continuity below)
- `stitching`              (episode-scoped — writes episode.final_video_path)

`Pipeline` facade gets new entry points:
```
run_episode(episode_id)  → orchestrates story → ... → stitching for one episode
run_story_analysis(episode_id)
run_scene_planning(episode_id)
... (mirror existing methods, swap arg)
```

Keep the old `run_*(project_id)` signatures as thin wrappers that resolve the
project's first/only episode for one revision, so we don't break any callers
during the transition.

### Cross-episode continuity (the new bit)

`_resolve_last_frame` in `stages/scene_video.py` currently chooses a prior
scene's last_frame.png **within the same project**. Update it:

```
def _resolve_last_frame(db, episode, scene):
    # 1. if scene.order_index > 0: existing behaviour (prior scene in this episode)
    # 2. if scene.order_index == 0 AND episode.order_index > 0:
    #       prev_ep = episode_with(project_id=episode.project_id,
    #                              order_index=episode.order_index-1)
    #       prev_last_scene = last scene of prev_ep whose video asset is complete
    #       return prev_last_scene's last_frame.png  (already extracted at gen time)
    # 3. otherwise: None  (first scene of episode 0 = true cold start)
```

`_extract_last_frame_for_next` already runs after every scene video and writes
`scene_{N:03d}_last_frame.png`. Episode-aware frame storage: put the file
under `storage/projects/<project>/episodes/<episode_order>/last_frames/...`
so cross-episode lookup is unambiguous.

`profile.pin_last_frame_chain` still gates this. The `drop_last_frame_on_tail`
condition (`scene_order_index >= 3`) needs revisiting per-episode — we want
the chain ACTIVE for episode N's scene 0 even if its order_index is 0; the
existing condition already handles that since order_index resets each episode.

### Stitching

`stages/stitching.py` writes the concatenated mp4 to:
```
storage/projects/<project>/episodes/<episode_order>/final.mp4
```
and sets `episode.final_video_path`. The project no longer has a single
`final_video_path` (it had multiple via render_jobs anyway). The UI lists all
episode finals.

### Queue scanner

`scripts/queue_scanner.py` currently scans projects in `draft` and picks them
up. Change it to scan **episodes** in `draft`, FIFO by `created_at`, oldest
first. Project-level draft → no-op (an episode-less project has nothing to
generate). The orphan-resume watchdog also moves to the episode level.

When the user creates a new episode via the API, the API writes the episode
row in `draft`; the scanner picks it up.

---

## 3. API changes

### New endpoints

```
POST   /projects/{project_id}/episodes
       body: {
         title?,                              // auto "Episode N" if omitted
         theme_hint?,                         // 1-line idea — e.g. "Jerry steals the cheese wheel from the fridge"
         original_story_text?,                // full story; OPTIONAL when theme_hint is provided
         target_duration_seconds,             // default 30s
         continue_from_previous?              // default true
       }
       Validation: exactly one of {theme_hint, original_story_text} must be non-empty.
         - If only theme_hint: status=draft, the story_analysis stage runs in
           "expand-from-theme" mode (see §5) and writes original_story_text
           before producing beats.
         - If original_story_text: status=draft, story_analysis runs normally.
       Returns 201 with the episode row. Scanner picks it up immediately.

POST   /projects/{project_id}/episodes/from-theme
       Convenience wrapper around POST /episodes with theme_hint only —
       body: { theme_hint, target_duration_seconds?, title?, continue_from_previous? }
       Same effect as the above with only theme_hint set; provided as a
       cleaner FE call.

GET    /projects/{project_id}/episodes
       list episodes with summary status + final_video_path

GET    /episodes/{episode_id}
       full episode detail (scenes, audio_plan, story_summary, beats)

PATCH  /episodes/{episode_id}
       edit story_text, theme_hint, target_duration, title, continue_from_previous
       (only when status=draft|failed)

DELETE /episodes/{episode_id}
       cascade kills scenes/assets for that episode only
```

### Episode-scoped stage triggers

Mirror the existing `/projects/{id}/run/*` endpoints under `/episodes/{id}/run/*`:
- `POST /episodes/{id}/run/story-analysis`
- `POST /episodes/{id}/run/scene-planning`
- `POST /episodes/{id}/run/prompt-generation`
- ...etc

### Backward-compat shim

`POST /projects/{id}/run/...` resolves to the project's first episode for one
release so existing scripts (seed_*) keep working. Mark deprecated in OpenAPI.

### Project endpoint changes

- `GET /projects/{id}` adds `episodes: [{id, order_index, title, status, final_video_path}]` summary.
- `POST /projects` no longer creates a scene/story — it just creates the shell. Story text moves to the first episode POST.
- Existing seed scripts (`seed_cartoon_ads.py`, `seed_tom_jerry_mini.py`) update: each call creates project → creates episode 1 with the story text.

---

## 4. Frontend changes

### Project page (`/projects/:id`)

Top of page: project-level tabs unchanged for cast (characters, locations,
products). New "Episodes" section above the existing per-scene tabs:

```
Episodes
─────────
[Ep 1 — Cheese Caper        | complete   | 30s | ▶ play]   ← selected
[Ep 2 — Vacuum Showdown     | generating | 30s |       ]
[Ep 3 — Pie Duel            | draft      | 30s | edit  ]
[+ New episode]
```

Clicking an episode swaps the underlying scenes/prompts/audio/final-video
tabs to that episode's data. URL becomes `/projects/:id/episodes/:epId?tab=scenes`.

### "+ New episode" CTA + modal

On the project page, prominent **`+ New episode`** button sits at the top of
the episodes list. The default flow is **theme-only** — one input, one click,
done. Power-user fields are tucked behind a "Show more" expander.

**Default (collapsed) modal:**
```
┌──── New episode ────────────────────────────────────────┐
│                                                          │
│  Theme                                                   │
│  ┌────────────────────────────────────────────────────┐  │
│  │ e.g. Tom corners Jerry under the kitchen sink with │  │
│  │ a vacuum and a soap-bottle ramp                    │  │
│  └────────────────────────────────────────────────────┘  │
│  One-line idea. We'll expand it into a full story.       │
│                                                          │
│  Length:  [ 30s ▾ ]   (10 / 15 / 20 / 30 / 45 / 60)      │
│                                                          │
│  ▸ Show more                                             │
│                                                          │
│              [ Cancel ]   [ Create episode ▶ ]           │
└──────────────────────────────────────────────────────────┘
```

**Show-more (expanded) fields:**
```
  Title              [ Episode 3 ]   (auto-filled, editable)
  Continue from previous  [✓]  (forced off + disabled for episode 0)
  Full story text (optional)        [ textarea ]
       — if filled, theme is ignored and this story is used verbatim.
```

**Submit behaviour:**
1. FE calls `POST /projects/{id}/episodes/from-theme` with
   `{ theme_hint, target_duration_seconds, continue_from_previous, title }`
   (or the full `POST /episodes` shape if the user typed full story text).
2. Server returns the created episode (`status=draft`). FE optimistically
   appends it to the episodes list with a `queued ⏳` chip.
3. The queue scanner picks it up within ~30s — UI polls and the chip flips
   to `analyzing → planning → ... → complete`. No further user action
   required.
4. While `status in (draft, analyzing)` the user can still edit the theme
   via the episode-detail page (PATCH). Once it advances past planning,
   the form is read-only.

### Cast-aware theme expansion

The theme box autosuggests the project's character names as `@mentions` so
the user can write "Tom chases @Jerry around the fridge" and we render the
canonical character cards in the story_analyst prompt for those tags. Pure
plain-English themes still work — the analyst will pull whichever characters
match.

### Final video viewer

The existing "final video" tab becomes a list — one player per episode in
order. Optional "play all" button stitches a `concat:` ffmpeg playlist for a
binge-watch view (does not write a new file).

---

## 5. Story analyst: theme expansion + prior episode awareness

### Two input modes

`story_analysis` stage now accepts two episode shapes:

**A. Story-text mode (existing path):** `episode.original_story_text` is a
full paragraph/story. Run the analyst exactly as today — extract beats,
summary, pacing.

**B. Theme mode (new):** `episode.theme_hint` is non-empty but
`original_story_text` is empty. Run a new sub-step `expand_theme_to_story`
before the existing beat extraction:

```
INPUT TO expand_theme_to_story:
  theme        = episode.theme_hint
  duration_s   = episode.target_duration_seconds
  characters   = [ Character.canonical_name + physical_description
                   for c in project.characters ]
  locations    = [ Location.name + description for l in project.locations ]
  prior_eps    = [ {title, summary, beats} for prev episodes, in order ]

OUTPUT:
  original_story_text = a 4-8 sentence story that uses the named cast,
                        plausibly fills the duration, and (if prior_eps)
                        picks up naturally from the previous episode's end.
```

The output is persisted back into `episode.original_story_text` (so the user
can see and edit the expansion in the FE). Then the regular beat-extraction
step continues on that text — no other downstream code knows the difference.

### Prior-episode context block

When `episode.order_index > 0` AND `continue_from_previous=true`, BOTH the
theme-expansion call AND the beat-extraction call get a "PRIOR EPISODE
CONTEXT" section in the user prompt:

```
This is Episode <N> in a series. The prior episode's beats were:
  <prev_ep.beat_list_json>
The prior episode ended with: <prev_ep.beats[-1].description>
The characters and locations are already established — do NOT re-introduce
them. Continue the world. The first beat of this episode should feel like a
natural continuation of the last beat of the previous episode.
```

When `continue_from_previous=false`, omit the "ended with / natural
continuation" lines — fresh cold open is fine, but the cast/locations
context still helps the analyst not invent strangers.

Same prior-episode-context idea propagates to `scene_planner` — if the first
beat is a direct continuation, its scene 0 should reuse the same
`location_name` as the prior episode's last scene; if it's a time jump or
scene change, it picks a different known location.

---

## 6. Lifecycle, status, and concurrency

- `episode.status` tracks the active stage exactly like `project.status` does today.
- `project.status` becomes derived: "active" if any episode is in a non-terminal state, else "complete" if all episodes complete, else "draft". Computed in a read-only view or on-the-fly in the API. Don't store it — the source of truth is now the episode rows.
- Episode locks (`orchestration/locks.py`) become `episode_id`-keyed instead of `project_id`-keyed. Two episodes of the same project may not generate concurrently in MVP (single GPU); single-flight is on the episode key.
- Scanner respects this — sorts draft episodes globally by `created_at`, dispatches one at a time.

---

## 7. Implementation phases

**Phase 0 — Migration + ORM (1 PR)**
- alembic revision: episodes table, episode_id columns, backfill, NOT NULL flip.
- ORM updates + relationships.
- Smoke-test: existing projects load, scenes still resolve, final_video_path of each backfilled Episode 1 matches the previously-stitched output.

**Phase 1 — Pipeline + API (1 PR)**
- All stages take `episode_id`.
- New episode CRUD + stage-trigger endpoints + `from-theme` wrapper.
- `story_analysis` gains theme-expansion sub-step.
- Scanner switches to episode-level draft scan.
- Cross-episode last-frame chain in `scene_video._resolve_last_frame`.
- Story analyst prior-episode prompt block.
- Backward-compat shim on `/projects/{id}/run/*`.

**Phase 2 — Frontend (1 PR)**
- Episode tab UI + `+ New episode` modal (theme-first, story-text behind expander).
- Project-character `@mention` autocomplete in theme input.
- Polled status chips on episode list.
- Routing under `/projects/:id/episodes/:epId`.
- Final video gallery view.
- Seed scripts updated.

**Phase 3 — Cleanup (1 PR, after a soak)**
- Drop project-level story_summary / beat_list_json / pacing_notes / style_lock / total_target_duration_seconds / final_audio_duration_seconds (now redundant — episode 0 holds them).
- Drop `/projects/{id}/run/*` shim.

---

## 8. Open decisions (flag for the user)

1. **Tom & Jerry mini-series**: today seeded as 5 separate projects. After
   Phase 2 ships, should those be auto-collapsed into one project with 5
   episodes? Or leave existing data alone and only future seeds use the
   new shape? Recommend: leave existing alone, update `seed_tom_jerry_mini.py`
   to emit one project + 5 episodes going forward.

2. **Can two episodes of the same project generate in parallel?** Default in
   plan above: NO (single GPU, sequential). If we get GPU 2 back online later
   we can drop the project-level lock — it's a one-line change.

3. **Audio across episodes**: currently audio_plan is one continuous track per
   project. Episodes will each have their own track. If we ever want a single
   narrator voice with one continuous backing music across the series, that's
   a future "series mixdown" stage — out of scope for v1.

4. **Cross-episode time gap**: if Ep 1 ends Tom mid-jump and Ep 2 starts a day
   later, should we still pin the last frame? Recommend a per-episode toggle
   `continue_from_previous: bool` (default true) on the episode row; when
   false, episode N scene 0 is a cold start with no last-frame chain.
