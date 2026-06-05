# examples/

Operator, seeding, and research/eval scripts that are **not part of the OpenFlow
application**. They were used during development to seed projects, batch-run ads,
and evaluate model/render quality. They are kept here as references — the app
itself does not import or depend on any of them (it is fully API-driven; see the
[API reference](../docs/API_REFERENCE.md)).

> ⚠️ Many of these scripts carry developer-specific paths and assumptions and may
> reference models, projects, or content that are not in this repo. Read a script
> before running it; treat them as examples, not supported tools.

## Layout

- **`seeds/`** — project seeding / ad-batch drivers (`run_ad_batch.py`,
  `eval_run.py`, `seed_background_videos.py`). The canonical, generic sample-data
  seeder lives at [`backend/seed_data.py`](../backend/seed_data.py); prefer that
  plus the API for normal setup.
- **`scripts/`** — Wan 2.2 evaluation, continuity, comparison, and iteration
  research scripts (`wan22_eval*`, `wan22_continuity*`, `wan22_compare_*`,
  `wan22_make_*grids`, `improvement_loop.py`, etc.) and a few manual GPU checks.

Production/operator tooling that the app or launchers DO rely on stays under
[`scripts/`](../scripts/) (queue scanner, catalog face-restore post-processors,
YouTube OAuth, video evaluator).
