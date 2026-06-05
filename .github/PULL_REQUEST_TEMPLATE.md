# Pull Request

## What & why
<!-- What does this change and why? Link any related issue (#123). -->

## How was it tested?
- [ ] `pytest -m "not slow"` (backend) passes
- [ ] `ruff check app` / `mypy app` clean
- [ ] Frontend: `npm run lint` / `npm run type-check` / `npm test`
- [ ] Manually verified in stub mode (no GPU) where applicable

## Checklist
- [ ] No secrets committed; `gitleaks detect` clean; `.env` untouched
- [ ] Docs / `CHANGELOG.md` updated if behavior or config changed
- [ ] If this touches identity/image generation, I read [ETHICAL_USE.md](../ETHICAL_USE.md)
- [ ] I agree to license my contribution under the project's [MIT License](../LICENSE)
