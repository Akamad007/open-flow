# Security Policy

## Supported versions

OpenFlow is in **alpha** (`0.1.x`). Security fixes are applied to the latest
`main` only. There is no long-term-support branch yet.

## Reporting a vulnerability

**Do not open a public issue for security problems.**

Email **akashdeshpande2000@gmail.com** with:

- a description of the issue and its impact,
- steps to reproduce (or a proof of concept),
- affected version / commit.

You will get an acknowledgement within **5 business days**. Please allow up to
**90 days** for a fix before any public disclosure.

## Deployment hardening (read before exposing this app)

OpenFlow was built as a single-operator tool on a trusted LAN. The default
configuration is **not safe to expose to the public internet**. Before
deploying:

- **Authentication.** The API ships with optional API-key auth (`API_KEY` env
  var). Set it; without it, all generation/upload endpoints are unauthenticated
  and anyone who can reach the port can trigger GPU jobs or YouTube uploads.
- **CORS.** Restrict `CORS_ORIGINS` to the exact frontend origin(s). Do not use
  `*` in production.
- **TLS.** Terminate HTTPS at a reverse proxy; never send the API key in clear.
- **Secrets.** Keep real keys out of `.env` in production — prefer the
  secrets-manager integration or your platform's secret store. `.env` is
  gitignored; never commit it.
- **YouTube OAuth.** `~/.video-app/youtube_oauth.json` holds a plaintext refresh
  token (mode `0600`). Treat it as a credential: never back it up unencrypted,
  and revoke the grant if the host is compromised.
- **Hugging Face / model tokens.** Prefer `huggingface-cli login` over putting
  `HF_TOKEN` in the environment of long-lived subprocesses.
- **Network egress.** The pipeline calls out to your configured LLM endpoint and
  (optionally) YouTube. Lock down egress if that matters for your threat model.

## Secret-scanning

CI runs `gitleaks` on every PR. Run it locally before pushing:

```bash
gitleaks detect --no-banner
```
