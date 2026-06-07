# Parallel Rendering — Root Cause Analysis

**Goal:** render the Tarot project's 78 episodes faster by using **both GPUs**
(RTX 5070 Ti 16GB = card 0, RTX 4070 Ti 12GB = card 1) instead of one episode at
a time on a single card (~26 min/episode × 78 ≈ 34 h).

This documents **why it was not running in parallel**, in layers from deepest to
most immediate.

---

## Layer 1 — The pipeline is single-episode-per-project (architectural)

The render pipeline is built around **one project → one active episode → one
status → one pipeline run**:

- Every stage resolves the episode with `resolve_active_episode(db, project_id)`
  = the *oldest non-terminal* episode. Two pipeline runs for the same project
  therefore target the **same** episode and collide.
- `acquire_pipeline_lock(project_id)` allows **only one** full-pipeline run per
  project; a second dispatch is dropped as a duplicate.
- `stage_lock(project_id, stage)` and `project.status` are **project-scoped** —
  one project cannot be "analyzing episode 5" and "generating episode 6" at once.

➡️ Consequence: a single project can never have two episodes in flight. The
parallelism that *does* exist in the system is **across projects** (the queue
scanner dispatches one project per free GPU), not across episodes of one project.

## Layer 2 — Within an episode, scenes are chained (by design)

`dispatch_video_chord` builds a **sequential `chain()`** of `generate_scene_video`
tasks (despite the docstring saying "parallel chord"). Each scene also enforces
`_assert_prev_scene_chain`: scene N refuses to render until scene N-1's video +
`last_frame.png` exist (I2V continuity — scene N starts from scene N-1's last
frame).

➡️ Consequence: even with many GPUs, **only one scene renders at a time**.

## Layer 3 — Per-project GPU routing pinned tarot to ONE card (routing)

The multi-GPU router (`app/utils/gpu_routing.py`) assigned each project to a
single card and routed all its GPU tasks to that card's **own queue**:

- worker `g0` consumed queue `gpu0` (card 0); worker `g1` consumed `gpu1` (card 1)
- tarot was assigned card 0 → `generate_scene_video → gpu0` → **only the big card
  ever got work; the small card sat idle** (nothing was ever routed to `gpu1`).

The two workers were on **separate queues**, not a shared one, so Celery could
not load-balance across them.

## Layer 4 — Operational churn: workers kept dying (immediate "frozen" state)

While iterating, **two shell sessions** were both starting/killing celery workers
(`pkill -f "celery -A celery_worker"` matches all of them), and the pipeline was
reset/dispatched several times with redis locks cleared in between. Net effect at
the time of writing:

- **No celery workers are running at all.**
- A `storyvideo.full_pipeline(tarot)` task sits **unconsumed** in the `cpu` queue.
- A `generate_scene_video` task is **unacked** (a worker grabbed it then died;
  `task_acks_late=True` keeps it for redelivery — but there is no worker to
  redeliver to).
- `project.status = analyzing`, frozen, because nothing is executing the chain.

➡️ This is why it looks "stuck": not a code bug in the hot path, but **nothing
alive to run it**, plus duplicate/racing dispatches from repeated resets.

---

## Fixes applied (code)

1. **Shared GPU queue.** `route_task` now sends *all* GPU tasks to one `gpu`
   queue that **every** GPU worker (one per card) consumes → Celery load-balances
   scene renders across both cards.
2. **Parallel scene fan-out.** Under `PARALLEL_SCENES=1`:
   - `_assert_prev_scene_chain` returns early (scenes render independently, no
     wait on the previous scene's video — they lose the I2V last-frame seed).
   - `dispatch_video_chord` dispatches a real `group()`/`chord` (all scenes at
     once) instead of a sequential `chain()`.
3. **`/reset` clears redis locks** so a re-dispatch isn't dropped as a duplicate.

These give **within-episode** parallelism (an episode's N scenes spread across
all cards). Verified hardware capacity: 94 GB RAM (70 GB free) — two simultaneous
5B renders fit.

## What still must be done to actually run it

1. **Stable workers.** Launch exactly one set: 2 GPU workers (`WAN22/IMAGE/AUDIO
   _GPU_INDEX` = 0 and 1) **both on the shared `gpu` queue** + 1 cpu worker, and
   ensure no other session is killing them. Clean redis + a **single** dispatch.
2. **Trade-off accepted for speed:** `PARALLEL_SCENES` drops within-episode I2V
   continuity (scenes become independent T2V clips). Fine for tarot cards;
   revert the flag to restore continuity.

## Proper long-term fix (not yet done)

For sustained 2× throughput **with** continuity, parallelize **episodes** (one
per card), which requires making the pipeline episode-scoped:
`pipeline_lock`/`stage_lock`/`assert_active` keyed by `(project, episode)`, and
threading an explicit `episode_id` through every stage instead of
`resolve_active_episode`. Then the driver dispatches episode N→card 0 and
episode N+1→card 1 concurrently.
