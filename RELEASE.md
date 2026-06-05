# Release Process

OpenFlow follows [Semantic Versioning](https://semver.org/) (`MAJOR.MINOR.PATCH`)
and is currently in the `0.x` alpha series (anything may change between minors).

## Cutting a release

1. Ensure `main` is green (CI: lint, tests, secret-scan).
2. Update [CHANGELOG.md](CHANGELOG.md): move `[Unreleased]` items under the new
   version + date.
3. Bump the version in `pyproject.toml`, `frontend/package.json`, and
   `backend/app/main.py` (`FastAPI(version=...)`).
4. Commit `release: vX.Y.Z`, tag it, and push:
   ```bash
   git tag -a vX.Y.Z -m "vX.Y.Z" && git push origin vX.Y.Z
   ```
5. Create a GitHub Release from the tag with the changelog section as notes.

## Versioning policy (0.x)

- `MINOR` — new features, possibly breaking (documented in the changelog).
- `PATCH` — bug fixes and docs.
- The schema evolves via Alembic migrations; run `alembic upgrade head` after
  upgrading.

A single source of truth for the version (read by all three places above) is a
good follow-up once the project stabilizes.
