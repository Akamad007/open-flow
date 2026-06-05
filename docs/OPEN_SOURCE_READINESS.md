# Open-Source Readiness — Implementation Plan

> **Verification note (added by maintainer pass):** An automated auditor in the source workflow incorrectly reported `.env` as committed. This was **independently disproven** — `.env` is correctly gitignored and was **never** committed (checked via `git ls-files`, full-history `--diff-filter=A`, `git check-ignore`, and `git cat-file -e HEAD:.env`). The git history (3 commits) is **clean of secrets**: no API keys, tokens, private keys, or passwords in any tracked file or commit. The only real secret (`SECRETS_MANAGER_TOKEN`) lives solely in the untracked on-disk `.env` and is redacted from this document. Findings that assumed a committed secret are corrected inline and downgraded.

---

> **Implementation status (branch `oss-readiness`):** Phases 0–4 of the execution
> plan below have been implemented as five commits. **Done:** LICENSE + governance
> files, rebrand to **OpenFlow**, repo de-bloat (untracked, kept on disk),
> env-driven config (no `/home/akash` in runtime code), optional API-key auth +
> readiness probe, `.env.example`/`.env.stub`, model-download script + docs,
> Docker/secrets decoupling, full doc set, `.github/` CI + templates + Dependabot,
> pyproject + lint/type/test tooling (CI green: 296 passed / 2 xfailed).
> **Deferred (intentionally, noted inline):** git-history rewrite to shrink `.git`
> (would delete working-tree media; no secrets in history); renaming infra
> identifiers (`storyvideo` DB/role + Celery task names) — left until the live
> render finishes; large refactors (split `visual_director.py`/`prompts.py`,
> decompose `ProjectDetailPage.tsx`); SPDX headers; real frontend component tests;
> rotating the on-disk token. See the per-item severities below.

---
_Repo: `/home/akash/PycharmProjects/video-app` — GPU AI story-to-video generation app (Python/FastAPI/Celery backend + React/Vite frontend)._

## Executive summary

This project is a multi-agent **story-to-video generation system**: an LLM plans scenes from a story, diffusion/video models (LTX-Video, Wan 2.2, SD3.5) render stills and clips, Chatterbox synthesizes narration, FFmpeg stitches the final MP4, and an optional pipeline uploads to YouTube. The backend is FastAPI + Celery + Postgres + Redis; the frontend is React/Vite/TypeScript.

**Verdict: NOT ready for public release.** The code is functional but tightly bound to one developer's machine and carries hard legal, secrets, and portability blockers. Specifically, and **verified against the working tree**:

- **No `LICENSE` file** despite README claiming MIT.
- **`.env` is NOT committed (verified clean).** It is correctly gitignored (`.gitignore:38`) and was never added in any of the 3 commits — confirmed via `git ls-files`, full-history `--diff-filter=A`, and `git cat-file -e HEAD:.env`. The on-disk `.env` does hold a real `SECRETS_MANAGER_TOKEN`; rotating it is optional defense-in-depth since automated tooling read its value, but **nothing was ever exposed through git.**
- A hard runtime dependency on an **external `secrets-manager` Django app** that is not in the repo.
- **`/home/akash` hardcoded across 205 tracked files**, including `backend/app/config.py` model paths and all launch scripts.
- **112 MB `.git`**, with 138 tracked LoRA training artifacts and 391 tracked `docs/runs/` eval files.
- Personal/religious seed scripts (Buddha, Krishna, Sadhguru, Tarot) and an unconsented **deepfake/identity-synthesis** feature shipped on-by-default.

Once Phase 0/1 are done the project is genuinely shareable; the bulk of remaining work is documentation, governance files, and CI.

### Severity counts (deduplicated)

| Severity | Count | Themes |
|---|---:|---|
| **Blocker** | 9 | LICENSE, `.env` secret in git, external secrets-manager, hardcoded paths, missing model/external deps docs, no auth, no governance files, ethical disclaimer, history secret-scan |
| **High** | 18 | Third-party model licensing, repo bloat, personal-content strip, README accuracy, packaging, CI/tests, code-quality config, frontend tests, GPU/model docs, health checks |
| **Medium** | 25 | pyproject, .dockerignore, SBOM/Dependabot, docs reorg, config consistency, content safety, privacy, packaging polish |
| **Low** | 9 | SPDX headers, DCO/CLA, editorconfig, i18n, migration naming, docs-site, git-history note |

> Counts are after merging ~80 overlapping raw findings (e.g. "LICENSE missing" appeared 6×, "secrets-manager" 8×, "hardcoded paths" 9×) into single canonical items.

---

## Release-blockers (do these before any public push)

These are absolute gates. **Do not push the repo public until every item here is green.**

- [ ] **Add a `LICENSE` file** — README line 165 claims MIT but no `LICENSE` exists, so the code is legally all-rights-reserved and nobody can use it. _Fix:_ create root `LICENSE` with standard MIT text and `Copyright (c) 2024-2026 Akash Deshpande and StoryVideo contributors`; update README to link it. _Files:_ `LICENSE` (new), `README.md`. _Severity:_ Blocker · _Effort:_ Trivial

- [ ] **Rotate the on-disk token (precaution) — `.env` is NOT in git** — Verified: `.env` was never committed; `.gitignore:38` covers it. The on-disk file holds a real `SECRETS_MANAGER_TOKEN` (redacted from this doc). _Fix:_ optionally rotate that token since automated tooling read it; ensure `.env` stays gitignored (it is); no history rewrite is needed for secrets. _Files:_ `.env` (untracked). _Severity:_ Low (downgraded from Blocker — no exposure) · _Effort:_ Trivial

- [ ] **Secret-scan full git history before publishing** — even after removing `.env`, older commits may carry it. The `.git` is 112 MB; one "Baseline before cleanup" commit exists but history rewrites can still leave blobs. _Fix:_ run `gitleaks detect --no-banner` and `trufflehog git file://. --only-verified`; if anything is found, rewrite with `git filter-repo`; add `.github/workflows/gitleaks.yml` to gate future PRs. _Files:_ `.github/workflows/gitleaks.yml` (new), history. _Severity:_ Blocker · _Effort:_ Small

- [ ] **Decouple from the external `secrets-manager` Django app** — the app fetches `OPENAI_API_KEY`/YouTube creds at runtime from a separate Django service at `http://127.0.0.1:8010`, launched by `start_all.sh` from the hardcoded path `/home/akash/PycharmProjects/secrets-manager`. That repo is not included; outsiders cannot run anything. _Fix:_ make the vault optional — priority order: (1) `SECRETS_MANAGER_URL` if set and reachable → vault; (2) else fall back to env vars (`OPENAI_API_KEY`, `YOUTUBE_CLIENT_ID/SECRET`, already partially wired in `openai_provider.py`). Make `secrets_client.py` return `None` gracefully (it mostly does). Update `start_all.sh` to skip vault launch if the path is absent. Document both paths in README. _Files:_ `backend/app/utils/secrets_client.py`, `backend/app/providers/llm/openai_provider.py`, `backend/app/utils/youtube_uploader.py`, `backend/app/config.py:31`, `start_all.sh:19,31-40`. _Severity:_ Blocker · _Effort:_ Medium

- [ ] **Eliminate hardcoded `/home/akash` paths from runtime code** — `/home/akash` appears in **205 tracked files**. Runtime-critical: `backend/app/config.py` lines 49/53/54 (Wan2.2 model dirs), 79 (`chatterbox_reference_audio`), and `start_all.sh`/`dev.sh`/`preview.sh` (pyenv + repo paths). These crash on any other machine. _Fix:_ in `config.py`, drive paths from a `MODELS_ROOT` env var (default `Path(__file__).parents[2] / "models"`) and use `Path(__file__)`-relative for the reference audio; in shell scripts use `REPO="$(cd "$(dirname "$0")" && pwd)"` and `PY_APP="${PYTHON_PATH:-$(command -v python3)}"`. Scripts/tests under `scripts/` and `backend/lora_training/` are lower priority (see Portability section). _Files:_ `backend/app/config.py`, `start_all.sh`, `dev.sh`, `preview.sh`. _Severity:_ Blocker · _Effort:_ Large

- [ ] **Strip repo bloat from working tree and history** — `.git` is 112 MB; **138 LoRA artifacts** (`.png`/`.pt`/`.pkl`) under `backend/lora_training/` and **391 files** under `docs/runs/` are tracked despite `.gitignore` covering `*.mp4`/`*.safetensors` (these slipped in before the rules, and `*.pt`/`*.pkl`/`*.png` weren't all covered). _Fix:_ `git rm --cached` the artifact dirs; extend `.gitignore` (snippet below); rewrite history with `git filter-repo --path backend/lora_training --path docs/runs --invert-paths` (or BFG) to recover ~100 MB. Move any artifacts worth keeping to external storage / a Release. _Files:_ `backend/lora_training/`, `docs/runs/`, `.gitignore`. _Severity:_ Blocker (history) / High (working tree) · _Effort:_ Medium

- [ ] **Strip personal / non-product content** — root holds `seed_buddha_enlightenment.py`, `seed_krishna_ads.py`, `seed_sadhguru_enlightenment.py`, `seed_tarot_arcana.py`, `tarot_render_driver.py`, `apply_tarot_sfw.py`, `run_ad_batch.py`, `eval_run.py`, plus `alai_alai_meaning.md`, `buddha_captions.md`, `tarot_render.log`, and `docs/krishna-*.md`. These are customer/personal one-offs, not library code, and confuse the project's scope. _Fix:_ delete entirely, or relocate a small genuinely-generic subset to `examples/` with a README labeling them demos; delete `tarot_render.log`. _Files:_ listed above; `docs/krishna-chakra-bhishma-scene.md`, `docs/krishna-shishupala-chakra-scene.md`. _Severity:_ Blocker (release-cleanliness) · _Effort:_ Small

- [ ] **Add an ethical-use / consent disclaimer for face synthesis** — the InstantID identity-preservation feature ("render the same character … anyone tomorrow", `docs/plan-identity-preservation.md`) generates deepfakes from an uploaded portrait, on-by-default (`config.py` `identity_provider_enabled=True`), with no consent language or AI-disclosure. This is a legal/ethics blocker for public release. _Fix:_ add `ETHICAL_USE.md`; add a README warning; require explicit consent acknowledgment before identity synthesis. (Details in the AI Ethics section.) _Files:_ `ETHICAL_USE.md` (new), `README.md`, `backend/app/config.py`. _Severity:_ Blocker · _Effort:_ Small

- [ ] **Add core community/governance files** — no `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`, or `.github/`. A public repo without these signals it is not ready. _Fix:_ minimum viable set before push: `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md` (Contributor Covenant 2.1), `SECURITY.md`. (Templates/CI can land in Phase 2.) _Files:_ root + `.github/`. _Severity:_ Blocker (governance gate) · _Effort:_ Small

---

## Legal & Licensing

- [ ] **Create `THIRD_PARTY_LICENSES.md` / model-license manifest** — no consolidated license summary exists; only `backend/lora_training/train_dreambooth_lora_sdxl.py` declares a license (Apache 2.0). Models and LoRAs carry varied, partly commercial-restricted terms. _Fix:_ create `THIRD_PARTY_LICENSES.md` plus a machine-readable `backend/app/config/model_licenses.yaml` listing every model/LoRA with license + restriction + source URL; include Python and npm dep licenses. _Files:_ `THIRD_PARTY_LICENSES.md` (new), `backend/app/config/model_licenses.yaml` (new). _Severity:_ High · _Effort:_ Medium

- [ ] **Document SD3.5 commercial restriction** — `config.py:84` hardcodes `stabilityai/stable-diffusion-3.5-medium` (Stability Community License: commercial use restricted). The pipeline targets ad/paid output, so this is a compliance trap. _Fix:_ document in `THIRD_PARTY_LICENSES.md`, add a README "License & Third-Party Models" section, and add a docstring warning at `config.py:84`. _Files:_ `backend/app/config.py`, `README.md`. _Severity:_ High · _Effort:_ Small

- [ ] **Document LTX-Video, Wan 2.2, and InstantID/InsightFace licensing** — LTX-Video (`Lightricks/LTX-Video`, `config.py:61`) is proprietary/research; Wan 2.2 commercial status is unconfirmed; InstantID's InsightFace `antelopev2` encoder is non-commercial (use `buffalo_l` for commercial). Redistributing weights is generally disallowed — users must download themselves. _Fix:_ add each to `THIRD_PARTY_LICENSES.md` with the swap-for-commercial note; reference from `instantid_provider.py`. _Files:_ `THIRD_PARTY_LICENSES.md`, `backend/app/providers/image/instantid_provider.py`. _Severity:_ High · _Effort:_ Small

- [ ] **Declare planned FLUX.1-dev as non-commercial** — `docs/plan-identity-preservation.md` references FLUX.1-dev (research-only). It is not implemented, but ship a clear note so a future contributor doesn't add it commercially. _Fix:_ add a one-line note in that doc and in `THIRD_PARTY_LICENSES.md`. _Files:_ `docs/plan-identity-preservation.md`. _Severity:_ High · _Effort:_ Trivial

- [ ] **(Optional) Add SPDX per-file headers** — only one file declares a license. _Fix:_ add `# SPDX-License-Identifier: MIT` via the `reuse` tool; defer to pre-1.0. _Files:_ all source. _Severity:_ Low · _Effort:_ Medium

- [ ] **(Optional) Add DCO sign-off requirement** — no contributor IP mechanism. _Fix:_ note DCO `-s` sign-off in `CONTRIBUTING.md`; enable the DCO GitHub app. _Files:_ `CONTRIBUTING.md`. _Severity:_ Low · _Effort:_ Small

---

## Community & Governance files

- [ ] **`CONTRIBUTING.md`** — no contribution guidance. _Fix:_ cover dev setup (no hardcoded paths), running tests (`pytest backend/tests`, `npm test`), lint/format, branch/PR flow, secret-scan release checklist, and "by contributing you agree to MIT". _Files:_ `CONTRIBUTING.md` (new). _Severity:_ Blocker (gate) · _Effort:_ Small

- [ ] **`CODE_OF_CONDUCT.md`** — none exists. _Fix:_ adopt Contributor Covenant 2.1; fill in an enforcement contact. _Files:_ `CODE_OF_CONDUCT.md` (new). _Severity:_ Blocker (gate) · _Effort:_ Small

- [ ] **`SECURITY.md`** — no disclosure policy, and the API is unauthenticated (see Secrets section). _Fix:_ document supported versions, private report channel + SLA, plus deployment hardening notes (set `API_KEY`, restrict CORS, HTTPS, protect `youtube_oauth.json`). _Files:_ `SECURITY.md` (new). _Severity:_ Blocker (gate) · _Effort:_ Small

- [ ] **`.github/` templates + CODEOWNERS** — no issue/PR templates or ownership mapping. _Fix:_ add `ISSUE_TEMPLATE/{bug_report,feature_request}.md`, `PULL_REQUEST_TEMPLATE.md`, `CODEOWNERS`. _Files:_ `.github/`. _Severity:_ High · _Effort:_ Small

- [ ] **`CHANGELOG.md` + `MAINTAINERS`/`AUTHORS`** — single squashed commit, no version history or ownership. _Fix:_ start `CHANGELOG.md` (Keep a Changelog) at `0.1.0-alpha`; add `MAINTAINERS` (Akash Deshpande, areas) mirrored into `CODEOWNERS`. _Files:_ `CHANGELOG.md`, `MAINTAINERS` (new). _Severity:_ Medium · _Effort:_ Small

- [ ] **GitHub metadata & a demo image** — `.git/description` is the default placeholder; README has no badges or visuals. _Fix:_ set repo description/topics (`video-generation`, `ai`, `diffusion-models`, `fastapi`, `react`), add status badges and a screenshot/`docs/demo.gif`. _Files:_ `README.md`, repo settings. _Severity:_ Medium · _Effort:_ Trivial

---

## Secrets & Security

- [ ] **Add API authentication & tighten CORS** — every FastAPI endpoint (projects, generation, YouTube uploads) is unauthenticated; CORS uses `allow_methods=['*']`/`allow_headers=['*']`. Public exposure lets anyone trigger GPU jobs or uploads. _Fix:_ add `app/security.py` with a `get_api_key` dependency reading `API_KEY`; gate all POST/PATCH/DELETE; restrict CORS to explicit methods/headers; document in `SECURITY.md`. _Files:_ `backend/app/main.py:34-41`, `backend/app/api/*.py`, `backend/app/config.py`, `backend/app/security.py` (new). _Severity:_ Blocker · _Effort:_ Medium

- [ ] **Remove hardcoded DB credentials from defaults and scripts** — `config.py:21-22` defaults embed `storyvideouser:storyvideopass`; `scripts/auto_grade_watcher.py:32` sets `PGPASSWORD='storyvideopass'`; `eval_run.py` hardcodes the DSN. _Fix:_ make `DATABASE_URL` required-from-env (no plaintext default); scripts read `settings.database_url`/env. _Files:_ `backend/app/config.py`, `scripts/auto_grade_watcher.py`, `eval_run.py`. _Severity:_ Blocker (paired with `.env` purge) · _Effort:_ Small

- [ ] **Harden HF_TOKEN handling in subprocesses** — `sd35_provider.py:92-94` and `instantid_provider.py` inject `HF_TOKEN` into the subprocess env, visible via `ps`/crash logs. _Fix:_ prefer `huggingface-cli login` (token in `~/.cache/huggingface/token`) and document it; if env is required, ensure subprocess logging never dumps the environment. _Files:_ `backend/app/providers/image/sd35_provider.py`, `backend/app/providers/image/instantid_provider.py`. _Severity:_ High · _Effort:_ Small

- [ ] **Document YouTube OAuth token security boundary** — `scripts/youtube_authorize.py` writes `~/.video-app/youtube_oauth.json` (mode 0600, plaintext refresh token). _Fix:_ note in `SECURITY.md`/`docs/youtube-setup.md` that the file is sensitive (never back up unencrypted, revoke if host compromised); suggest a vault for production. _Files:_ `SECURITY.md`, `docs/youtube-setup.md`. _Severity:_ High · _Effort:_ Small

- [ ] **Sync `.env.example` with all settable vars** — `.env.example` (1.3 KB) omits `HF_TOKEN`, `API_KEY`, `LLM_STRONG_MODEL`, `YOUTUBE_OAUTH_PATH`, `IMAGE_PREGEN_ENABLED`, `IDENTITY_PROVIDER_ENABLED`, `INSTANTID_DAEMON_ENABLED`, model-path vars, and contains no live secrets. _Fix:_ regenerate from the `Settings` class with `[REQUIRED]`/`[OPTIONAL]` markers and a stub/GPU profile split (snippet below). _Files:_ `.env.example`. _Severity:_ Medium · _Effort:_ Small

- [ ] **Add a real health check** — `/api/health` returns a static `{"status":"ok"}` and never probes DB/Redis/vault, so liveness probes pass while dependencies are down. _Fix:_ add `db`/`redis`/`secrets_manager` checks and split `/api/readiness` vs `/api/liveness`. _Files:_ `backend/app/main.py`. _Severity:_ High · _Effort:_ Small

---

## Portability & Configuration

- [ ] **Replace hardcoded model paths with env-driven config** — `config.py:49/53/54/79`. _Fix:_ `MODELS_ROOT` env var (default repo-relative `models/`), Wan22 sub-paths derived from it; `chatterbox_reference_audio` via `Path(__file__)`. Log a clear error with the expected path + download URL when a model is missing instead of crashing late. _Files:_ `backend/app/config.py`. _Severity:_ Blocker · _Effort:_ Small _(part of the Phase 0 blocker)_

- [ ] **Make launch scripts portable** — `start_all.sh:18-21`, `dev.sh:15-18`, `preview.sh:16` hardcode the repo path and `/home/akash/.pyenv/.../bin/python`. _Fix:_ derive `REPO` from `$(dirname "$0")`; `PY_APP="${PYTHON_PATH:-$(command -v python3)}"`; prefer `backend/.venv/bin/python` if present. _Files:_ `start_all.sh`, `dev.sh`, `preview.sh`. _Severity:_ Blocker · _Effort:_ Small

- [ ] **Add OS/GPU detection and a CPU/stub fallback** — `start_all.sh:52` assumes `nvidia-smi`; scripts use Linux-only `pkill`/`setsid`/`nohup`. Non-NVIDIA/macOS/Windows hosts fail silently. _Fix:_ detect OS, warn when GPU detection fails, document `VIDEO_PROVIDER=stub`/`AUDIO_PROVIDER=stub` for CPU hosts, recommend Docker on macOS/Windows. _Files:_ `start_all.sh`, `dev.sh`, README. _Severity:_ High · _Effort:_ Medium

- [ ] **Document & path-override external scripts (InstantID, Chatterbox)** — `instantid_provider.py:40-41` and `orchestration/_common.py:108-116` shell out to `~/instantid/generate_instantid*.py` (not in repo); fallback to SD3.5 is silent. _Fix:_ add `INSTANTID_DIR` config (default `~/instantid`), log when InstantID is unavailable ("using SD3.5 fallback"), and document setup. _Files:_ `backend/app/providers/image/instantid_provider.py`, `backend/app/orchestration/_common.py`, `backend/app/config.py`, README. _Severity:_ Blocker → resolves with secrets/portability work · _Effort:_ Medium

- [ ] **Fix port inconsistency** — README says `:8000`; `start_all.sh:47` runs uvicorn on `:8002`; `docker-compose.yml:38` + `.env:57 BACKEND_PORT=8000` use `:8000`. _Fix:_ standardize (recommend `:8002` for `start_all.sh`, `:8000` for Docker) and state both clearly in README. _Files:_ `README.md`, `start_all.sh`, `docker-compose.yml`. _Severity:_ High · _Effort:_ Trivial

- [ ] **Reconcile provider defaults across config / .env.example / docker-compose / README** — `config.py` defaults `llm_provider=openai`, `video_provider=stub`, `image_provider=sd35`; `docker-compose.yml` sets `VIDEO_PROVIDER=ltx`; README table lists `stub`/Ollama. _Fix:_ pick one canonical default set, document overrides, explain LTX/Wan22/stub tradeoffs. _Files:_ `backend/app/config.py`, `.env.example`, `docker-compose.yml`, `README.md`. _Severity:_ Medium · _Effort:_ Small

- [ ] **De-hardcode helper scripts (lower priority)** — `scripts/wan22_*.py`, `backend/lora_training/*.sh`, `backend/test_*.py` carry `/home/akash` paths (part of the 205-file count). _Fix:_ a shared `scripts/_paths.py` reading env vars with sensible defaults, or at minimum a header documenting required vars. _Files:_ `scripts/`, `backend/lora_training/`. _Severity:_ Medium · _Effort:_ Small

- [ ] **Untrack `.claude/settings.local.json` and `tarot_render.log`** — both are tracked; `settings.local.json` has 10+ `/home/akash` refs. _Fix:_ `git rm --cached` both; add to `.gitignore`; optionally add a path-agnostic `.claude/settings.json`. _Files:_ `.claude/settings.local.json`, `tarot_render.log`, `.gitignore`. _Severity:_ Low · _Effort:_ Trivial

---

## Build / Install / Dependencies

- [ ] **Add `pyproject.toml` (packaging + tool config)** — no `pyproject.toml`/`setup.py`; can't `pip install -e .` and Python ≥3.11 isn't enforced. _Fix:_ create `pyproject.toml` with `[project]` metadata (name, `requires-python=">=3.11"`, MIT), `[project.optional-dependencies]` `gpu`/`test`/`dev`, `[build-system]`, and `[tool.ruff]`/`[tool.black]`/`[tool.mypy]`/`[tool.pytest.ini_options]`. _Files:_ `pyproject.toml` (new), `backend/requirements.txt`. _Severity:_ Medium-High · _Effort:_ Medium

- [ ] **Pin ML deps and split CPU/GPU requirements** — `backend/requirements.txt:33-40` uses unpinned ranges (`torch>=2.2.0`, `diffusers>=0.30.0`, `transformers>=4.40.0`); no CUDA index URL (it's only in `test.sh`). Breaks reproducibility and risks license drift. _Fix:_ pin exact versions; provide `requirements-cpu.txt` / `requirements-gpu.txt` (torch CUDA index) / `requirements-dev.txt`. _Files:_ `backend/requirements.txt`. _Severity:_ High · _Effort:_ Small

- [ ] **Declare test dependencies** — `backend/tests/conftest.py:29` imports `testcontainers.postgres`, but `testcontainers`/`pytest-asyncio` aren't in any requirements file; `pytest` fails fresh. _Fix:_ add `requirements-dev.txt` (`pytest`, `pytest-asyncio`, `testcontainers[postgres]`, `coverage`) or `[project.optional-dependencies].test`. _Files:_ `backend/requirements-dev.txt` (new) or `pyproject.toml`. _Severity:_ Blocker for CI · _Effort:_ Small

- [ ] **Provide a model-weights acquisition workflow** — no scripted way to fetch LTX/Wan2.2/SD3.5/InstantID/Chatterbox/GFPGAN/CodeFormer weights (multi-GB, some gated). `config.py` just points at `/home/akash/Wan2.2-Models`. _Fix:_ add `backend/scripts/download_models.py` (flags `--ltx/--wan22/--sd35/--all`, `huggingface_hub.snapshot_download`, idempotent), document gated models needing `HF_TOKEN`, and a `docs/MODELS_AND_WEIGHTS.md` checklist. _Files:_ `backend/scripts/download_models.py` (new), `docs/MODELS_AND_WEIGHTS.md` (new). _Severity:_ High · _Effort:_ Medium

- [ ] **Fix Docker for standalone use** — `docker-compose.yml:48-49,80-81` references the absent secrets-manager at `host.docker.internal:8010`, so `docker compose up` crashes at runtime; `Dockerfile.backend` installs torch with no CUDA index (silent CPU on GPU hosts). _Fix:_ make secrets-manager optional/env-fallback; add `ARG TORCH_INDEX_URL`; provide a `docker-compose.override.yml` for stub dev. _Files:_ `docker-compose.yml`, `Dockerfile.backend`. _Severity:_ High · _Effort:_ Medium

- [ ] **Add `.dockerignore`** — none exists; `COPY` pulls `.git`, `.venv`, `node_modules`, `storage/`, `.env`, seed scripts into images (bloat + secret risk). _Fix:_ add root and `frontend/` `.dockerignore`. _Files:_ `.dockerignore` (new), `frontend/.dockerignore` (new). _Severity:_ Medium · _Effort:_ Trivial

- [ ] **Add a `Makefile` task runner** — three inconsistent scripts (`dev.sh`, `start_all.sh`, `test.sh`) with no `make install/test/lint/dev`. _Fix:_ add a `Makefile` (or `pyproject` scripts) with parameterizable CPU/GPU targets. _Files:_ `Makefile` (new). _Severity:_ Medium · _Effort:_ Small

- [ ] **Frontend dep hygiene** — `frontend/package.json` has no `engines`, no eslint/prettier; `Dockerfile.frontend` uses unpinned `node:20-slim`. _Fix:_ add `engines` (`node>=20`), pin the base image by digest, add `lint`/`format`/`type-check` scripts + devDeps. _Files:_ `frontend/package.json`, `Dockerfile.frontend`. _Severity:_ Medium · _Effort:_ Small

- [ ] **Add `.editorconfig` + `.gitattributes`** — none; line-ending/indent drift across Python/TS/shell. _Fix:_ add `.editorconfig` (4-space Python, 2-space TS/JSON, LF) and `.gitattributes` (`* text=auto`, `*.sh/*.py text eol=lf`). _Files:_ new. _Severity:_ Low · _Effort:_ Trivial

- [ ] **Add SBOM + dependency scanning** — no SBOM, Dependabot, or `pip-audit`. _Fix:_ add `.github/dependabot.yml` (pip + npm, weekly); generate `sbom.json` (cyclonedx/syft) in CI; run `pip-audit`. _Files:_ `.github/dependabot.yml` (new), CI. _Severity:_ Medium · _Effort:_ Small

- [ ] **Document a release/versioning process** — version `0.1.0` is duplicated in `backend/app/main.py` and `frontend/package.json` with no bump tooling or semver policy. _Fix:_ `RELEASE.md` + `scripts/bump-version.sh`; tag-triggered release build in CI. _Files:_ `RELEASE.md` (new). _Severity:_ Medium · _Effort:_ Small

---

## Documentation

- [ ] **Fix README inaccuracies** — wrong backend port (8000 vs 8002), "production-quality MVP" overstatement, missing Wan22 provider option, no license/compliance/secrets-manager sections. Per critic: the `seed_data.py` Docker path (`docker compose exec backend python seed_data.py`) is actually correct inside the container; the local-dev usage just needs a `cd backend` note. _Fix:_ correct ports, soften "production-quality" → "alpha MVP", clarify `seed_data.py` is at `backend/seed_data.py` (run from `backend/`), document `VIDEO_PROVIDER=ltx|wan22|stub`, add License/External-Services sections. _Files:_ `README.md`. _Severity:_ Medium · _Effort:_ Small

- [ ] **Add a no-GPU stub-mode quickstart** — README mentions stubs but never shows how to enable them; `config.py` defaults assume GPU+keys. `test_stub_providers.py` proves stubs work. _Fix:_ ship `.env.stub`; add a README "Run without GPU (1 min)" section setting `LLM_PROVIDER=stub VIDEO_PROVIDER=stub AUDIO_PROVIDER=stub IMAGE_PROVIDER=stub`. _Files:_ `README.md`, `.env.stub` (new). _Severity:_ High · _Effort:_ Small

- [ ] **Write `INSTALL.md` + `docs/DEPLOYMENT.md`** — README setup is ~57 lines for a 7-service GPU system; no GPU/CUDA, secrets, model-download, or production guidance. _Fix:_ `INSTALL.md` (system reqs, GPU/CUDA, venv, deps, DB init, troubleshooting); `docs/DEPLOYMENT.md` (Docker prod, worker scaling, secrets, model volumes). _Files:_ `INSTALL.md`, `docs/DEPLOYMENT.md` (new). _Severity:_ High · _Effort:_ Medium-Large

- [ ] **Document GPU/VRAM requirements** — only a stray `config.py:65-68` comment ("~6-8 min/scene on a 5070 Ti") mentions hardware. _Fix:_ `docs/GPU_REQUIREMENTS.md` with per-model VRAM, tested GPUs, expected latency, multi-GPU notes; add a hardware line to README. _Files:_ `docs/GPU_REQUIREMENTS.md` (new), `README.md`. _Severity:_ High · _Effort:_ Small

- [ ] **Write `docs/ENVIRONMENT_VARIABLES.md`** — `config.py` has ~40 options; README documents 5. _Fix:_ full reference grouped by category (DB, LLM, Video, Audio, Image, GPU), ideally generated from the `Settings` class. _Files:_ `docs/ENVIRONMENT_VARIABLES.md` (new). _Severity:_ High · _Effort:_ Medium

- [ ] **Add API reference, troubleshooting, and DB-setup docs** — no curl/workflow examples, no troubleshooting (VRAM OOM, vault down, FFmpeg missing), no clear migration/seed steps. _Fix:_ `docs/API_REFERENCE.md` (create→analyze→generate→poll), `docs/TROUBLESHOOTING.md`, `scripts/init_db.sh` (`alembic upgrade head && python seed_data.py`). _Files:_ new under `docs/` and `scripts/`. _Severity:_ Medium · _Effort:_ Medium

- [ ] **Reorganize `docs/`** — ~30 files mix user guides with internal journals (`iteration-status.md`, `FIXES_LOG.md`, `plan-*.md`, eval reports). _Fix:_ add `docs/README.md` index; move internal notes to `docs/internal/`; keep user-facing guides at `docs/` root. _Files:_ `docs/`. _Severity:_ Medium · _Effort:_ Small

---

## Repo Hygiene & Restructure

- [ ] **Reorganize root-level entry scripts** — root holds generic generators (`ltx_generate.py`, `wan_generate.py`, `wan22_generate.py`, `chatterbox_generate.py`, `seed_background_videos.py`) mixed with the 43-script `scripts/` dir; unclear which are production. `queue_scanner.py` is production (used by `start_all.sh`). _Fix:_ create `scripts/core/` (production: `queue_scanner.py`), `tools/` (user utilities: `youtube_authorize.py`), `examples/` (demos/generators); add `scripts/README.md`; update `start_all.sh` references. _Files:_ root `*.py`, `scripts/`. _Severity:_ High · _Effort:_ Medium

- [ ] **Move/document vendored libs and LoRA training** — `CodeFormer/`, `gfpgan/`, `model_comparison/` are vendored/`.gitignore`d but present on disk; `backend/lora_training/` (1.3 GB) is domain-specific. _Fix:_ keep them gitignored (already are); document fetching CodeFormer/GFPGAN weights at runtime; move `lora_training/` source to `tools/lora_training/` with a README; do **not** track checkpoints. _Files:_ `backend/lora_training/`, README. _Severity:_ Low-Medium · _Effort:_ Small

- [ ] **Resolve the 12 untracked working-tree files** — `git status` shows new utilities (`backend/app/utils/subtitle_burn.py`, `gpu.py` changes, a Scene-caption alembic migration, `backend/tests/test_caption_timeline.py`, `backend/scripts/backfill_captions.py`) alongside untracked personal content. _Fix:_ commit the production-ready backend utilities/migration/tests; delete or relocate the tarot/krishna/buddha files per the blocker above. _Files:_ see `git status`. _Severity:_ Low · _Effort:_ Small

---

## Testing & CI

- [ ] **Add CI (`.github/workflows/ci.yml`)** — no CI; 82 backend test files never run; no lint/type gates. _Fix:_ jobs for backend lint (`ruff`), type-check (`mypy backend/app`), `pytest backend/tests` (stub providers + dockerized Postgres, skip GPU/`slow`), frontend `eslint`/`tsc`/`vitest`; run lint first (fail-fast). _Files:_ `.github/workflows/ci.yml` (new). _Severity:_ Blocker for quality / High · _Effort:_ Medium-Large

- [ ] **Add lint/format config (ruff, black, eslint, prettier) + pre-commit** — none present. _Fix:_ `[tool.ruff]`/`[tool.black]` in `pyproject.toml` (line-length 100, py311), `frontend/.eslintrc` + `.prettierrc`, `.pre-commit-config.yaml`. Note: `feedback_code_style` mandates ≤300-line files / ≤50-line functions — consider a ruff `max-lines` rule. _Files:_ `pyproject.toml`, `frontend/`, `.pre-commit-config.yaml` (new). _Severity:_ High · _Effort:_ Small

- [ ] **Add mypy type-checking for backend** — async FastAPI/SQLAlchemy with heavy hints but no `mypy` config. _Fix:_ `[tool.mypy]` (py311, `ignore_missing_imports`, gradually stricter); wire into CI. _Files:_ `pyproject.toml`. _Severity:_ High · _Effort:_ Small

- [ ] **Add test coverage reporting** — no `coverage`/`pytest-cov`; ~25% est. coverage untracked. _Fix:_ `pytest --cov=app --cov-report=xml`, Codecov upload, `--cov-fail-under=60`. _Files:_ `pyproject.toml`, CI. _Severity:_ High · _Effort:_ Small

- [ ] **Add frontend tests** — 3.7 K LOC, zero tests. _Fix:_ add Vitest + Testing Library; smoke-test the API client and key pages; `npm test`. _Files:_ `frontend/`. _Severity:_ High · _Effort:_ Medium

- [ ] **Add an all-stub end-to-end pipeline test** — stubs are unit-tested in isolation but never exercised end-to-end (`story_analysis → … → stitching`). _Fix:_ `backend/tests/test_pipeline_e2e_stub.py` running the full chain with all stubs (no GPU), in CI. Per memory rules, keep it network/subprocess-free. _Files:_ `backend/tests/` (new). _Severity:_ Medium · _Effort:_ Small

- [ ] **Add a stitching stub provider** — `stitching/base.py` has only FFmpeg; full-stub runs can't stitch. _Fix:_ `stitching/stub_provider.py` returning a dummy MP4. _Files:_ `backend/app/providers/stitching/` (new). _Severity:_ Low · _Effort:_ Small

- [ ] **Enforce test markers in CI** — `pytest.ini` defines `slow` but nothing skips it. _Fix:_ default CI runs `-m "not slow"` for fast feedback, plus a separate slow job. _Files:_ `backend/pytest.ini`, CI. _Severity:_ Low · _Effort:_ Small

---

## Code Structure

- [ ] **Split backend god-files (>300 lines)** — violates the project's ≤300-line rule: `visual_director.py` (637), `scene_video.py` (553), `prompts.py` (553), `wan22_provider.py` (397), `ffmpeg_provider.py` (378), `ltx_provider.py` (369), `prompt_generation.py` (352). _Fix:_ extract focused modules (e.g. `prompts/{portrait,background,action}.py`, `visual_director/{batch,single,validator}.py`); enforce with a ruff line-count rule. Smoke-test imports after each split per memory rules. _Files:_ listed above. _Severity:_ Medium · _Effort:_ Medium

- [ ] **Decompose `ProjectDetailPage.tsx` (1173 lines, 12 tabs)** — single monolithic component holding ~15 `useState`s. _Fix:_ extract one component per tab + a `useProjectDetail()` hook; target ≤200 lines/component. _Files:_ `frontend/src/pages/ProjectDetailPage.tsx`. _Severity:_ High · _Effort:_ Medium

- [ ] **Move backend integration tests out of `backend/` root** — `backend/test_instantid_*.py`, `test_img2img_product.py`, `test_pipeline_isolated.py`, etc. clutter the root. _Fix:_ move to `backend/tests/integration/` with descriptive names; ensure `pytest.ini` `testpaths` covers them. _Files:_ `backend/test_*.py`. _Severity:_ Medium · _Effort:_ Small

- [ ] **(Optional) Deprecation policy & markers** — multiple provider generations (wan22/ltx/phantom; sd35/instantid) with disabled paths (`IMAGE_PREGEN_ENABLED=False`) and no lifecycle docs. _Fix:_ `DEPRECATION_POLICY.md`, `warnings.warn` on dead paths, CHANGELOG entries. _Files:_ new. _Severity:_ Low · _Effort:_ Small

---

## Reproducibility / Runnability

- [ ] **Provide a Docker-free local setup path** — local dev steps are scattered (manual Postgres/Redis/FFmpeg). _Fix:_ `scripts/setup_local.sh` (check Python 3.11+/Postgres/Redis/FFmpeg, create venv, install, migrate, seed) + `docs/LOCAL_DEV.md`. _Files:_ `scripts/setup_local.sh` (new), `docs/LOCAL_DEV.md` (new). _Severity:_ Medium · _Effort:_ Small

- [ ] **Add startup model/provider diagnostics** — silent SD3.5 fallback and missing-model crashes confuse newcomers. _Fix:_ log active image-provider mode (InstantID vs SD3.5 vs stub) and missing model paths at startup. _Files:_ `backend/app/orchestration/_common.py`, `backend/app/main.py`. _Severity:_ Medium · _Effort:_ Small

- [ ] **Enforce Python version at runtime** — `backend/.python-version` holds a pyenv venv name, not a version; nothing fails on 3.10/3.13. _Fix:_ `requires-python>=3.11` in `pyproject.toml` + a `sys.version_info` check in `main.py`. _Files:_ `pyproject.toml`, `backend/app/main.py`. _Severity:_ Low · _Effort:_ Trivial

- [ ] **Document Wan22 LoRA auto-selection** — `wan22_provider.py` auto-picks LoRAs from `config/wan22_lora_catalog.yaml` (tiers/weights) with no user docs. _Fix:_ `docs/PROVIDERS.md` explaining tag-based selection + a debug log of the chosen LoRA per scene. _Files:_ `docs/PROVIDERS.md` (new). _Severity:_ Low · _Effort:_ Trivial

---

## AI Ethics & Content Safety

- [ ] **Ship `ETHICAL_USE.md` + consent gating for identity synthesis** — _(see blocker above)_ InstantID generates deepfakes on-by-default. _Fix:_ `ETHICAL_USE.md` (consent required, AI-disclosure required, jurisdiction warning, no-liability); README warning; `REQUIRE_CONSENT_ACKNOWLEDGMENT=true` flag forcing acknowledgment before synthesis; audit-log every synthesis op (portrait path + timestamp); optional `ADD_AI_WATERMARK`. _Files:_ `ETHICAL_USE.md` (new), `README.md`, `backend/app/config.py`, `backend/app/orchestration/scene_video.py`. _Severity:_ Blocker · _Effort:_ Small-Medium

- [ ] **Define content-safety posture** — `apply_tarot_sfw.py` ("SFW-strengthen" text) implies content risk, but there's no moderation framework. _Fix:_ `CONTENT_SAFETY.md` stating the posture (research/alpha, moderation NOT implemented); for commercial use, plan an input-prompt moderation hook. _Files:_ `CONTENT_SAFETY.md` (new). _Severity:_ High · _Effort:_ Medium (Large if implementing moderation)

- [ ] **Add a data-privacy policy** — projects, portraits, generated videos, and YouTube creds are stored with no retention/export/delete policy. _Fix:_ `PRIVACY.md` (retention, no auto-backup, GDPR contact); add project export/cascade-delete endpoints. _Files:_ `PRIVACY.md` (new), `backend/app/api/projects.py`. _Severity:_ Medium · _Effort:_ Medium

---

## Nice-to-have / Polish

- [ ] **Accessibility (a11y) in the frontend** — div-based tabs, no ARIA roles, no keyboard nav (WCAG AA gap). _Fix:_ semantic `tablist/tab/tabpanel`, ARIA labels, keyboard handlers, `axe`/`Pa11y` check; document as in-progress for now. _Files:_ `frontend/src/`. _Severity:_ High (long-term) · _Effort:_ Medium
- [ ] **Internationalization** — UI/prompts hardcoded English. _Fix:_ note "English-only, i18n contributions welcome"; structure strings as constants. _Severity:_ Low · _Effort:_ Large
- [ ] **Migration naming convention** — mixed numeric/UUID alembic IDs; add a `YYYY_MM_DD_description` convention + `docs/SCHEMA.md`. _Severity:_ Low · _Effort:_ Small
- [ ] **Docs site** — flat `docs/`; consider MkDocs later. _Severity:_ Low · _Effort:_ Small
- [ ] **Git-history note** — single squashed commit; note in `CONTRIBUTING.md` that history was reset (acceptable for OSS). _Severity:_ Low · _Effort:_ Trivial

---

## Proposed final repo structure

### Before (selected, verified)

```
video-app/
├── README.md                       # claims MIT, wrong ports
├── .env.example                    # incomplete (1.3 KB)
├── .gitignore                      # .env correctly ignored; bloat dirs slipped in before rules
├── (no LICENSE / CONTRIBUTING / SECURITY / .github/)
├── tarot_render.log                # stray log, tracked
├── seed_buddha_enlightenment.py    # personal/religious  ⚠️
├── seed_krishna_ads.py             #   "
├── seed_sadhguru_enlightenment.py  #   "
├── seed_tarot_arcana.py            #   "
├── apply_tarot_sfw.py              #   "
├── tarot_render_driver.py          #   "
├── run_ad_batch.py                 # customer one-off
├── eval_run.py                     # hardcoded DB creds
├── seed_background_videos.py
├── ltx_generate.py / wan_generate.py / wan22_generate.py / chatterbox_generate.py
├── alai_alai_meaning.md / buddha_captions.md          # personal docs  ⚠️
├── start_all.sh / dev.sh / preview.sh / test.sh       # hardcoded /home/akash
├── CodeFormer/ , gfpgan/ , model_comparison/          # vendored (gitignored, on disk)
├── backend/
│   ├── app/config.py               # /home/akash model paths (49/53/54/79)
│   ├── seed_data.py
│   ├── test_*.py                   # integration tests at backend root
│   ├── requirements.txt            # unpinned ML deps
│   └── lora_training/              # 1.3 GB, 138 tracked artifacts  ⚠️
├── docs/
│   ├── (user guides + internal journals mixed)
│   ├── krishna-*.md                # personal  ⚠️
│   └── runs/                       # 391 tracked eval files  ⚠️
└── frontend/
    ├── tsconfig.tsbuildinfo        # tracked build cache  ⚠️
    └── src/pages/ProjectDetailPage.tsx   # 1173 lines
```

### After

```
video-app/
├── LICENSE                         # + MIT
├── THIRD_PARTY_LICENSES.md         # + model/dep licenses
├── README.md                       # fixed ports, license/ethics/setup sections
├── CONTRIBUTING.md  CODE_OF_CONDUCT.md  SECURITY.md  CHANGELOG.md  MAINTAINERS
├── ETHICAL_USE.md  CONTENT_SAFETY.md  PRIVACY.md  RELEASE.md
├── .env.example                    # complete; [REQUIRED]/[OPTIONAL], no secrets
├── .env.stub                       # all-stub CPU profile
├── .gitignore                      # extended (see snippet)
├── .dockerignore  .editorconfig  .gitattributes
├── .pre-commit-config.yaml
├── pyproject.toml                  # packaging + ruff/black/mypy/pytest
├── Makefile
├── .github/
│   ├── workflows/{ci.yml, gitleaks.yml}
│   ├── dependabot.yml
│   ├── ISSUE_TEMPLATE/{bug_report.md, feature_request.md}
│   ├── PULL_REQUEST_TEMPLATE.md
│   └── CODEOWNERS
├── start_all.sh / dev.sh / preview.sh    # path-agnostic
├── examples/                       # demos ONLY if kept; else deleted
│   └── README.md
├── tools/
│   ├── lora_training/              # moved; checkpoints gitignored
│   └── youtube_authorize.py
├── scripts/
│   ├── core/queue_scanner.py       # production
│   ├── download_models.py  setup_local.sh  init_db.sh
│   └── README.md
├── backend/
│   ├── app/config.py               # MODELS_ROOT/env-driven
│   ├── app/security.py             # + API-key auth
│   ├── requirements.txt + requirements-{cpu,gpu,dev}.txt   # pinned
│   ├── seed_data.py
│   └── tests/
│       ├── integration/            # moved test_*.py
│       └── test_pipeline_e2e_stub.py
├── docs/
│   ├── README.md (index)
│   ├── INSTALL.md DEPLOYMENT.md GPU_REQUIREMENTS.md ENVIRONMENT_VARIABLES.md
│   ├── MODELS_AND_WEIGHTS.md API_REFERENCE.md TROUBLESHOOTING.md PROVIDERS.md
│   └── internal/                   # journals, eval reports
└── frontend/
    └── src/pages/ProjectDetail/    # split into per-tab components + hook
```

**Untracked (kept on disk per request):** `tarot_render.log`, `docs/runs/**`, `backend/lora_training/**` artifacts (`*.pt/*.pkl/*.png`), tracked `.claude/settings.local.json`, `frontend/tsconfig.tsbuildinfo`. **Deleted or moved to `examples/`:** all `seed_*.py` (except generic `backend/seed_data.py`), `apply_tarot_sfw.py`, `tarot_render_driver.py`, `run_ad_batch.py`, `eval_run.py`, `docs/krishna-*.md`, `alai_alai_meaning.md`, `buddha_captions.md`.

---

## Suggested `.gitignore` additions

The current `.gitignore` already lists `storage/`, `.env`, `*.mp4`, `*.safetensors`, etc., but those files were tracked before the rules. Add explicit patterns, then `git rm --cached` the already-tracked ones.

```gitignore
# --- additions for OSS release ---

# Secrets / local env (already listed, but ensure removal from index)
.env
.env.local

# IDE / agent local config
.claude/settings.local.json

# Frontend build cache
frontend/tsconfig.tsbuildinfo

# Training checkpoints & datasets (slipped past *.safetensors/*.pth)
*.pt
*.pkl
backend/lora_training/**/checkpoint-*/
backend/lora_training/**/*.png

# Eval / run artifacts (kept in external storage or Releases)
docs/runs/

# Stray logs at root
/*.log

# Python build / packaging
build/
*.egg-info/

# SBOM / scan output
sbom.json
```

Removal commands (do NOT touch local copies — `--cached` only):

```bash
git rm --cached tarot_render.log frontend/tsconfig.tsbuildinfo .claude/settings.local.json
git rm -r --cached docs/runs
git rm --cached $(git ls-files 'backend/lora_training/**' | grep -E '\.(pt|pkl|png)$')
```

---

## Suggested `.env.example` / config decoupling

**`.env.example`** (complete, no live secrets, profile-aware):

```dotenv
# ---- Core services (REQUIRED) ----
DATABASE_URL=postgresql+asyncpg://CHANGE_ME:CHANGE_ME@localhost:5432/storyvideo
DATABASE_URL_SYNC=postgresql://CHANGE_ME:CHANGE_ME@localhost:5432/storyvideo
REDIS_URL=redis://localhost:6379/0
BACKEND_PORT=8002                 # start_all.sh uses 8002; docker compose uses 8000

# ---- API auth (REQUIRED for any non-local deployment) ----
API_KEY=dev-key-change-in-production

# ---- Providers: pick a profile ----
# Stub (no GPU/keys):  LLM=stub VIDEO=stub AUDIO=stub IMAGE=stub
# GPU-full:            LLM=openai VIDEO=ltx AUDIO=chatterbox IMAGE=sd35
LLM_PROVIDER=stub
VIDEO_PROVIDER=stub
AUDIO_PROVIDER=stub
IMAGE_PROVIDER=stub

# ---- Secrets source (OPTIONAL) ----
# Leave SECRETS_MANAGER_URL empty to read keys directly from env below.
SECRETS_MANAGER_URL=
SECRETS_MANAGER_TOKEN=
OPENAI_API_KEY=                   # used when SECRETS_MANAGER_URL is empty
HF_TOKEN=                         # required for gated models (SD3.5); or use `huggingface-cli login`
YOUTUBE_CLIENT_ID=
YOUTUBE_CLIENT_SECRET=

# ---- Model paths (OPTIONAL; default to $MODELS_ROOT) ----
MODELS_ROOT=./models
WAN22_MODEL_PATH=                 # default: $MODELS_ROOT/wan22/TI2V-5B-Diffusers
WAN22_MOTION_MODEL_PATH=
WAN22_LORA_DIR=
CHATTERBOX_REFERENCE_AUDIO=       # default: backend/storage/audio/narrator_reference.wav
INSTANTID_DIR=~/instantid

# ---- Ethics ----
IDENTITY_PROVIDER_ENABLED=true
REQUIRE_CONSENT_ACKNOWLEDGMENT=true
```

**`backend/app/config.py`** decoupling pattern (replaces the hardcoded `/home/akash` paths at lines 49/53/54/79):

```python
from pathlib import Path
import os

MODELS_ROOT = Path(os.getenv("MODELS_ROOT", str(Path(__file__).parents[2] / "models")))

class Settings(BaseSettings):
    wan22_model_path: str = os.getenv(
        "WAN22_MODEL_PATH", str(MODELS_ROOT / "wan22" / "TI2V-5B-Diffusers"))
    wan22_motion_model_path: str = os.getenv(
        "WAN22_MOTION_MODEL_PATH", str(MODELS_ROOT / "wan22" / "FrameINO-5B-MotionINO-v1.6"))
    wan22_lora_dir: str = os.getenv(
        "WAN22_LORA_DIR", str(MODELS_ROOT / "wan22" / "loras" / "5b"))
    chatterbox_reference_audio: Path = Path(os.getenv(
        "CHATTERBOX_REFERENCE_AUDIO",
        str(Path(__file__).parent.parent / "storage" / "audio" / "narrator_reference.wav")))
    # Secrets: vault first, else env fallback
    secrets_manager_url: str = os.getenv("SECRETS_MANAGER_URL", "")  # empty => env-var mode
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
```

---

## Recommended execution order

| Phase | Goal | Items | Rough effort |
|---|---|---|---|
| **0 — Legal & Secrets (GATE)** | Make it legal & safe to publish | LICENSE; `git rm --cached .env` + **rotate token**; gitleaks/trufflehog history scan + `filter-repo` cleanup of `.env`/`docs/runs`/`lora_training` (112 MB → ~10 MB); strip personal/religious content; `ETHICAL_USE.md`; CONTRIBUTING/COC/SECURITY | ~2–3 days |
| **1 — Portability & Runnability** | Anyone can clone & run | De-hardcode `config.py` + shell scripts; decouple secrets-manager (vault-or-env); InstantID path config + fallback logging; `download_models.py` + `MODELS_AND_WEIGHTS.md`; fix Docker/`.dockerignore`; `.env.example`/`.env.stub`; fix ports; add API auth + real health check | ~3–5 days |
| **2 — Docs & Community** | Onboard contributors & users | README rewrite (ports/license/ethics/stub-quickstart); INSTALL/DEPLOYMENT/GPU/ENV_VARS/API/TROUBLESHOOTING; reorganize `docs/`; restructure scripts into `core/`/`tools/`/`examples/`; `.github/` templates + CODEOWNERS; CHANGELOG/MAINTAINERS; THIRD_PARTY_LICENSES | ~3–4 days |
| **3 — CI & Quality** | Keep it healthy | `pyproject.toml` + pinned deps + `requirements-dev`; ruff/black/mypy/eslint/prettier + pre-commit; CI (lint/type/test/coverage); frontend Vitest; all-stub E2E test; move backend integration tests; split god-files + `ProjectDetailPage.tsx`; Dependabot/SBOM | ~4–6 days |
| **4 — Polish** | Maturity & ethics depth | a11y; content-moderation hook; PRIVACY + export/delete; SPDX headers; DCO; migration naming/SCHEMA; docs site; i18n note | ~2–4 days (ongoing) |

**Critical path to "publishable": Phase 0 + Phase 1.** Everything in Phase 0 is a hard gate; Phase 1 makes the repo actually runnable by an outsider. Phases 2–4 raise it from "runnable" to "healthy, contributor-ready OSS."