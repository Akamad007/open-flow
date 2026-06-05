# scripts/

Operator and research scripts. These are **not** imported by the application —
they are run by hand. Anything in `backend/app/` is the actual product.

> Note: `queue_scanner.py` is referenced by `start_all.sh` and the running
> pipeline — do not move/rename it without updating those.

## Production / operations
- `queue_scanner.py` — drains draft projects FIFO and watchdogs stuck ones.
- `youtube_authorize.py` — one-time YouTube OAuth (writes `~/.video-app/youtube_oauth.json`).
- `download_civitai_loras.sh` — fetch optional style LoRAs (check each LoRA's license).

## Evaluation & iteration (research)
- `wan22_eval*.py`, `wan22_compare_*.py`, `wan22_continuity*.py`,
  `wan22_make_*grids.py`, `evaluate_video.py`, `measure_project.py` — quality/eval
  harnesses used during development.
- `improvement_loop.py`, `iterate_pipeline.py`, `auto_grade_watcher.py` —
  automated iteration loops.
- `restore_faces.py`, `wan22_face_restore*.py` — face-restoration experiments.

## Ad-hoc / one-off
- `wan22_kick_*.sh`, `wan22_requeue_recent.py`, `render_scene.py`,
  `reprompt_*.py`, `frameino_manual.py`, `test_*.py` — single-purpose helpers.

Many of these carry assumptions about the original dev environment. A future
cleanup will split these into `tools/` (supported) vs `examples/` (demos). Until
then, read a script before running it.
