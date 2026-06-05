# scripts/

Production / operator tooling the app or launchers rely on. These are run by
hand or by `scripts/start_all.sh`; they are **not** imported by `backend/app/`.

- `queue_scanner.py` — drains draft projects FIFO and watchdogs stuck ones
  (launched by `scripts/start_all.sh`).
- `wan22_face_restore.py`, `wan22_face_restore_codeformer.py` — post-render face
  restoration; invoked at render time per `backend/app/config/wan22_lora_catalog.yaml`.
- `wan22_fix_zackdfilms.py` — LoRA key-format remap referenced by the catalog.
- `youtube_authorize.py` — one-time YouTube OAuth (`~/.video-app/youtube_oauth.json`).
- `evaluate_video.py` — CLI wrapper around the post-stitch video evaluator.
- `download_civitai_loras.sh` — fetch optional style LoRAs (check each LoRA's license).

Research, evaluation, and one-off seeding/ad scripts have moved to
[`../examples/`](../examples/). The canonical sample-data seeder is
[`../backend/seed_data.py`](../backend/seed_data.py).
