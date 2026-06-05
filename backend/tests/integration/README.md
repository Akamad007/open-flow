# Manual GPU smoke scripts

These `smoke_*.py` files are **not pytest tests** — they are standalone scripts
(`python smoke_*.py`) for hand-checking the GPU pipeline (InstantID identity,
img2img product placement, full-body portraits, isolated pipeline runs). They
require a real GPU, model weights, and (for InstantID) the external scripts in
`INSTANTID_DIR`, so they cannot run in the offline pytest suite.

They are named `smoke_*` (not `test_*`) so pytest does not try to collect them.
Run one directly, e.g.:

```bash
cd backend && PYTHONPATH=. python tests/integration/smoke_instantid_identity.py
```

> Note: some still contain developer-specific paths; review before running.
