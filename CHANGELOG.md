# Changelog

All notable changes to OpenFlow are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project aims
to follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Open-source readiness: `LICENSE` (MIT), `SECURITY.md`, `CONTRIBUTING.md`,
  `CODE_OF_CONDUCT.md`, `ETHICAL_USE.md`, `THIRD_PARTY_LICENSES.md`.
- No-GPU stub profile (`.env.stub`) and a complete `.env.example`.
- `backend/scripts/download_models.py` + `docs/MODELS_AND_WEIGHTS.md`.
- Optional API-key authentication (`API_KEY`) and an `/api/readiness` probe.
- `.dockerignore`; docs set (INSTALL, DEPLOYMENT, ENVIRONMENT_VARIABLES,
  API_REFERENCE, TROUBLESHOOTING).

### Changed
- Rebranded the application to **OpenFlow** (human-facing strings).
- Model paths are now env-driven (`MODELS_ROOT` + per-model overrides) instead
  of hardcoded; launch scripts resolve the interpreter portably.
- `docker compose up` defaults all providers to `stub` and makes the external
  secrets-manager optional.

### Removed
- Untracked ~1.6 GB of training/eval artifacts and personal content from git
  (kept on disk).

## [0.1.0] — baseline
- Initial multi-agent story-to-video pipeline (pre-open-source).
