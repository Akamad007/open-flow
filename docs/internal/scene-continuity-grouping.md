# Scene continuity grouping — audit & fix plan

**Status:** proposed · **Date:** 2026-06-05 · **Verdict:** partial (see below)

## Goal

Let the pipeline recognise **non-adjacent continuity threads**: e.g. in an
interleaved story, scenes **2, 3, 8** belong to thread A (palace, character X)
and scenes **1, 4, 6** to thread B (forest, character X) — and have the render
chain, prompting, and consistency review treat each scene as continuing from its
**thread predecessor**, not from `order_index − 1`.

## TL;DR

Continuity today lives in **two disconnected subsystems**:

1. **Planning / prompting — strictly adjacent.** The planner emits free-text
   `continuity_from_previous` / `continuity_to_next` per scene; prompt generation,
   the visual director, and the consistency critic all reason about the literal
   `scenes[i-1]` / `scenes[i+1]` neighbours.
2. **Render-time last-frame chain — already smarter than adjacent.**
   `_pick_seed_scene_index` walks back and seeds each scene's I2V frame from the
   most-recent prior scene that **shares ≥1 character**, skipping non-overlapping
   scenes.

So we are **partial**: the renderer accidentally handles the easy case (scene 8
chains from scene 3 *iff* scenes 4–7 have different/no characters), but there is
**no thread/storyline concept anywhere** (`grep` for `thread|storyline|continuity_group|subplot`
→ zero hits). The exact case the user cares about — **interleaved storylines that
share a character** — mis-chains, because character overlap is the *only*
discriminator.

## What happens today (verified)

### Planner (adjacent prose only)
- Output schema asks per-scene for `continuity_from_previous` / `continuity_to_next`
  only — both adjacent, prose, unvalidated.
  `backend/app/agents/scene_planner.py:206-207`
- Chunked planning carries **only the last scene's** `continuity_to_next` forward
  as a single string to seed the next chunk's first scene; mid-chunk threads are
  lost at the boundary. `scene_planner.py:62,85,144-148`
- Scenes are sequenced by a monotonic `order_index`; no group key.
  `scene_planner.py:80-81`

### Persistence (no group column)
- `Scene` has `order_index`, `continuity_from_previous`, `continuity_to_next`
  (Text), `skip_last_frame_chain` (default **True** = chaining OFF unless opted
  in), `location_id`, character M2M — **no group/thread column.**
  `backend/app/models/scene.py:54-72`
- The planner JSON maps 1:1 to `Scene` rows in array order.
  `backend/app/orchestration/stages/scene_planning.py:250`

### Render-time chain (character-overlap smart seed — the load-bearing path)
- `_resolve_last_frame` selects all priors with `order_index < N` (most-recent
  first); `_pick_seed_scene_index` returns the first whose character-id set
  intersects the current scene's — else `None` (cold T2V).
  `backend/app/orchestration/stages/scene_video.py:99-125,193-204`
- Confirmed non-adjacent in tests (scene 4 seeds from scene 1, skipping 2–3).
  `backend/tests/test_scene_video_smart_seed.py`
- Overrides: scene 0 chains from the previous **episode's** last scene only when
  `Episode.continue_from_previous` (`scene_video.py:175-176,132-162`);
  `anchor_first_frame` + same chars + same location as scene 0 seeds from
  `scene_000_first_frame.png` (`scene_video.py:179-192`).
- **Latent bug:** `_assert_prev_scene_chain` hardcodes
  `Scene.order_index == scene.order_index - 1` and raises **"Chain broken"** if
  that video is missing — *regardless of which scene the smart picker chose*. So
  a legitimately non-adjacent seed can still spuriously fail.
  `scene_video.py:305-330`

### Downstream consumers (all adjacent)
- Prompt context resolves `prev_scene = scenes[i-1]` / `next_scene = scenes[i+1]`
  positionally and feeds `i-1`'s `visual_summary` + `video_prompt` in; the
  cross-batch anchor uses `scenes[i-1].prompt`.
  `backend/app/orchestration/stages/prompt_generation.py:106-107,145-149,227-235`
- `skip_last_frame_chain` is set to `not continuity_from_previous` against the
  single `i-1` neighbour. `prompt_generation.py:183-188`
- Visual director tells the LLM the 0–1 s beat must resume the **exact pose the
  previous (`i-1`) scene ended on**. `backend/app/agents/visual_director.py:252-262`
- Consistency critic checklist item 7 judges "continuity between **ADJACENT**
  scenes". `backend/app/agents/consistency_critic.py:75`

## The gap (worked example)

Scenes 2,3,8 = thread A (character X, palace); scenes 1,4,6 = thread B (character
X, forest):
- **Render:** scene 8 seeds off scene **6** (most-recent X-overlap), not scene 3
  → inherits forest pixels/lighting. Character overlap has **no location/time
  discriminator**, so same-character-different-setting is a "valid" (wrong) seed.
- **Prompting:** scene 8's prompt is told to physically resume scene **7**'s
  ending pose, and `continuity_from_previous` describes scene 7 — an unrelated
  thread.
- **Critic:** flags the legitimate A→B→A interleave as an abrupt cut defect.

Net: location/lighting/pose snaps at every thread boundary.

## Fix: an explicit `continuity_group`

Introduce a per-scene **thread label** (`continuity_group`) that the planner
assigns (and reuses for non-adjacent same-thread scenes), persisted on `Scene`,
and consulted by the render chain + prompting + critic. **`NULL` preserves
today's behaviour exactly** — no backfill, fully backward-compatible.

### Change set (ordered; each independently shippable)

| # | Area | Change | Files | Effort |
|---|------|--------|-------|--------|
| 1 | Model | Add `continuity_group: Mapped[str \| None] = mapped_column(String(64), nullable=True)` | `backend/app/models/scene.py` | trivial |
| 2 | Migration | New revision `add_scene_continuity_group`, `down_revision = "p6q7r8s9t0u1"` (current head); `op.add_column('scenes', sa.Column('continuity_group', sa.String(64), nullable=True))` | `backend/alembic/versions/` | trivial |
| 3 | Schemas | Add `continuity_group: Optional[str]` to `SceneCreate` / `SceneUpdate` / `SceneRead` | `backend/app/schemas/scene.py` | trivial |
| 4 | Story analyst | Emit a `threads` list + per-beat `thread_id` (stable, authoritative source of thread ids) | `backend/app/agents/story_analyst.py`, `prompts/story_analyst.txt` | medium |
| 5 | Planner | Add `continuity_group` to the per-scene output schema + a RULES bullet ("assign a short thread label; **reuse** it for non-adjacent scenes in the same setting/character-state/plotline"); carry `beat.thread_id` through. **Chunked fix:** replace the scalar `prev_continuity` with a `{open_thread_id → last continuity_to_next}` map and normalise labels across chunks at merge | `scene_planner.py:62,85,144-148,177-213`, `prompts/scene_planner.txt` | medium |
| 6 | Persistence | In `_build_scene`, set `continuity_group=scene_data.get("continuity_group")` | `scene_planning.py:~139-152` | small |
| 7 | **Render chain (load-bearing)** | Make `_pick_seed_scene_index` thread-aware: when `current.group` is set, require `prior.group == current.group` **before** the character-overlap check; fall back to today's character-overlap walk-back when `group is None`. Add `continuity_group` to the SELECT/`selectinload` and to `prior_tuples`. This is the single change that makes scene 8 chain from scene 3 | `scene_video.py:99-125,193-204`, `tests/test_scene_video_smart_seed.py` | medium |
| 8 | Integrity guard | `_assert_prev_scene_chain` must assert on the **seed scene the picker chose**, not `order_index − 1` (reuse `_resolve_last_frame`'s choice / thread predecessor) | `scene_video.py:305-330` | small |
| 9 | Prompt generation | Resolve `prev_scene` as the most-recent earlier same-group scene (default `scenes[i-1]` when `group is None`); follow the thread predecessor's stored prompt for the cross-batch anchor; set `skip_last_frame_chain` relative to the thread predecessor | `prompt_generation.py:106-107,145-149,183-188,227-235` | medium |
| 10 | Visual director | Relabel the neighbour block "Thread-predecessor/successor"; the "resume the exact action" + `continues_from_previous` rules target the thread predecessor | `visual_director.py:38-46,252-262,395-398`, `prompts/visual_director.txt:42-49` | small |
| 11 | Consistency critic | Pass the thread predecessor in; reword checklist item 7 + the per-scene "From" line from "ADJACENT" to "thread-consecutive" | `consistency_review.py:39-62`, `consistency_critic.py:75,145-149` | small |

Ship in two slices: **(1,2,3,7,8)** makes the renderer thread-correct (the
visible fix); **(4,5,6,9,10,11)** makes the planner produce threads and the
prompting/critic agree.

## Open design decisions

1. **Episode scoping.** `continuity_group` is scoped **within one `episode_id`**
   (the render query already filters by episode). A thread must never chain
   across episodes — keep scene 0's existing "chain only from previous episode's
   last scene, gated on `continue_from_previous`" rule. Reset/ignore thread
   labels at the episode boundary even if a label repeats. (See
   `feedback_no_cross_episode_chain`.)
2. **Location discriminator.** Even with threads, consider also requiring same
   `location_id` in `_pick_seed_scene_index` so we never inherit wrong-setting
   pixels. Must stay **last-frame chaining only** — never pin portraits/stills as
   frame conditions (`feedback_no_frame_conditioning_pictures`).
3. **Thread-first scene seeding.** The first scene of a thread has no in-episode
   predecessor. Recommend: cold-start (T2V / character portrait, like scene 0)
   unless it overlaps an earlier scene by character **and** location.
4. **Thread-id authority.** Prefer story-analyst-assigned ids (stable across the
   analyst→planner handoff and across chunk boundaries) over planner-assigned +
   post-merge normalisation. `beat.thread_id` must survive the beat-slicing in
   `_run_chunked` (`scene_planner.py:64-89`).
5. **`skip_last_frame_chain` default.** Today defaults **True** (off). Should
   same-thread scenes auto-chain (user's intent) or stay opt-in (conservative,
   guards against lighting mismatch)? Recommend: auto-chain within a thread,
   keep opt-in across threads.
6. **Reorder.** `SceneReorder` rewrites `order_index` but not `continuity_group`
   — robust for the render picker (keys on group+order), but the prose
   `continuity_from_previous/to_next` notes can be silently invalidated (they
   store no source-scene reference). Decide whether reorder clears/regenerates
   the prose hand-offs.

## Test plan

- `test_scene_video_smart_seed.py`: add pure-function cases for
  `_pick_seed_scene_index` with the `group` dimension — interleaved
  same-character threads (2,3,8 / 1,4,6) must seed 8←3 and 6←4; `group=None`
  must reproduce today's character-overlap results.
- New: `_assert_prev_scene_chain` asserts on the chosen seed, not `N-1`.
- Planner: a fixture story with two interleaved storylines yields scenes whose
  `continuity_group` reuses labels non-adjacently; chunk-boundary threads are
  preserved.
- Backward-compat: an all-`NULL` project renders/prompts identically to pre-change.
