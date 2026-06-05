# Privacy & Data Handling

OpenFlow is self-hosted software, not a hosted service — **you** run it and
control all data. This document describes what data the software stores so you
can meet your own obligations.

## What OpenFlow stores

| Data | Where | Notes |
|---|---|---|
| Projects, scenes, prompts, metadata | PostgreSQL (`DATABASE_URL`) | The story text and generated plans |
| Generated/ uploaded media (images, video, audio) | `STORAGE_ROOT` on disk | Includes any reference/portrait images you upload |
| Reference images for identity synthesis | `storage/` | A real person's likeness if you supply one — see [ETHICAL_USE.md](ETHICAL_USE.md) |
| YouTube OAuth refresh token | `~/.video-app/youtube_oauth.json` | Plaintext credential; protect it (see [SECURITY.md](SECURITY.md)) |
| LLM prompts | sent to your configured `LLM_API_BASE` | If you use a cloud LLM, your story text leaves your machine |

OpenFlow has **no telemetry or analytics** — it does not phone home.

## External data flows

- The configured LLM endpoint receives story text and prompts.
- If enabled, generated video is uploaded to your YouTube channel.
- Model weights are downloaded from Hugging Face on setup.

Use stub/local providers (`LLM_PROVIDER=stub` or a local Ollama/vLLM) to keep all
data on-premises.

## Retention & deletion

There is no automatic retention policy. To remove a project's data, delete its
DB rows and the corresponding files under `STORAGE_ROOT`. If you operate OpenFlow
for others, define and publish your own retention/export/delete policy and honour
applicable laws (GDPR/CCPA, biometric and publicity-rights statutes).

## Operator responsibilities

If you process other people's data with OpenFlow, you are the data controller.
Obtain consent for any real likeness, secure the database and storage volume,
and provide a way for individuals to request deletion.
