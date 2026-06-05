# Contributing to OpenFlow

Thanks for your interest in contributing! This document explains how to get a
development environment running and how to submit changes.

By contributing, you agree that your contributions will be licensed under the
project's [MIT License](LICENSE), and you confirm you have the right to submit
the work. Please also read the [Code of Conduct](CODE_OF_CONDUCT.md) and, if you
touch the identity/image-generation pipeline, [ETHICAL_USE.md](ETHICAL_USE.md).

## Project layout

- `backend/app/` — FastAPI app: `agents/`, `api/`, `providers/`,
  `orchestration/`, `models/`, `schemas/`, `utils/`.
- `frontend/src/` — React/Vite/TypeScript UI.
- `backend/tests/` — pytest suite (runs offline with stub providers).
- `docs/` — guides and design notes.

## Running without a GPU (fast path)

You do not need a GPU or model weights to develop most of the app. Use the
**stub providers**:

```bash
cp .env.example .env          # then set the four providers to "stub"
# LLM_PROVIDER=stub VIDEO_PROVIDER=stub AUDIO_PROVIDER=stub IMAGE_PROVIDER=stub

cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
alembic upgrade head
python seed_data.py
uvicorn app.main:app --reload --port 8002
```

Frontend:

```bash
cd frontend && npm install && npm run dev
```

See [docs/INSTALL.md](docs/INSTALL.md) for the full GPU setup and model weights.

## Tests, linting, and types

Run these before opening a PR (CI runs the same):

```bash
# backend
cd backend
pytest -m "not slow"          # offline; no network/subprocess (see tests/)
ruff check app
mypy app

# frontend
cd frontend
npm run lint
npm run type-check
npm test
```

Tests **must not** hit the network, spawn real subprocesses, or call real
providers — use the stubs and fixtures in `backend/tests/`.

## Code style

- Python: `ruff` + `black` (line length 100), type hints required on new code.
- Keep functions small (≤ ~50 lines) and files focused (≤ ~300 lines); split
  rather than grow god-files.
- TypeScript: `eslint` + `prettier`.
- Install the git hooks: `pre-commit install`.

## Conventions

- **Database migrations:** create with `alembic revision --autogenerate -m
  "short description"`; give the file a descriptive slug. Review the generated
  SQL before committing. Never edit an already-released migration.
- **Internationalization:** the UI and prompts are English-only today. Strings
  are not yet externalized; i18n contributions are welcome — start by extracting
  user-facing strings into constants.
- **Accessibility:** the frontend is a known gap (tabs are not yet semantic
  `tablist`/`tab` with keyboard navigation). a11y improvements are very welcome;
  run `axe`/Pa11y against changed pages.

## Submitting changes

1. Fork and branch from `main` (`feat/...`, `fix/...`, `docs/...`).
2. Make focused commits; write a clear PR description and link any issue.
3. Ensure CI is green (lint, types, tests, secret-scan).
4. Run `gitleaks detect --no-banner` — never commit secrets or `.env`.
5. A maintainer (see [CODEOWNERS](.github/CODEOWNERS)) will review.

## Reporting bugs / requesting features

Use the GitHub issue templates. For security issues, follow
[SECURITY.md](SECURITY.md) instead of filing a public issue.

> Note: the public git history was reset to a clean baseline before
> open-sourcing, so it does not reflect the full development history.
