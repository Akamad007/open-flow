# Wan 2.2 TI2V-5B — empirical evaluation run

**Goal:** Generate ~30 short videos on TI2V-5B before any backend integration,
sweeping LoRA × weight, so we have ground truth on what works on this model
specifically (not what works on the 14B variants the LoRA ecosystem targets).

**Status:** In progress — 2026-05-19.

---

## Environment snapshot

- GPU: single RTX 5070 Ti, 16 GB (15.1 GB free). Dual-GPU not active this session.
- Disk: 607 GB free on `/`.
- Python: `/home/akash/.pyenv/versions/video-app/bin/python`
- diffusers 0.38.0, torch 2.11.0+cu128, `WanPipeline` + `WanImageToVideoPipeline` present.
- Model dir: `~/Wan2.2-Models/` (loras subfolder exists, empty).
- HF cache: `models--Kijai--WanVideo_comfy` exists but only refs/main — no weights.

## Architecture caveat that reshapes the matrix

The `lightx2v/Wan2.2-Lightning` repo only contains LoRAs for the **A14B** variants:
every directory is `Wan2.2-I2V-A14B-...` or `Wan2.2-T2V-A14B-...`, with paired
`high_noise_model.safetensors` + `low_noise_model.safetensors`. A14B is a
two-expert mixture-of-experts model with two separate transformers; **TI2V-5B
has one transformer**. The LoRA tensor shapes will not match. Lightning on 5B is
expected to fail at load — we'll confirm empirically but not plan around it.

Implication: the speed-distillation headline win is A14B-only. If we want
Lightning, we must use A14B (which needs FP8 + offload on a 16 GB card, like
our existing Phantom-Wan 14B path). For the 5B path, we test what 5B can
actually do unaccelerated.

## Test matrix

5 prompts × 5 seconds each (24 fps, 121 frames):

| # | Prompt theme | Why it's in the matrix |
|---|---|---|
| 1 | Static product close-up on a wooden table, soft window light | Tests product fidelity, low motion |
| 2 | Person walking across a field at sunset, full body, side view | Tests body kinematics — the SD3.5 portrait-bias failure mode |
| 3 | Hand pouring water into a glass, macro, slow motion | Tests fine motion + physics |
| 4 | City street with people walking, handheld camera | Tests crowd + camera motion |
| 5 | Animated watercolor of a forest with falling leaves | Tests stylized rendering |

LoRA × weight sweep (per prompt):

| LoRA | Source | Weights |
|---|---|---|
| (none — baseline) | — | n/a |
| Lightning A14B (T2V) | `lightx2v/Wan2.2-Lightning` | 0.5, 1.0 — expected to fail load; documents the failure |
| Kijai 5B style LoRA (if found) | `Kijai/WanVideo_comfy` | 0.5, 1.0 |

If Lightning fails to load (likely), we replace those slots with whatever 5B-compatible
LoRAs surface from a quick HF search. We will not pad the matrix with LoRAs we
know are architecturally incompatible.

**Realistic total: 5 baselines + 10–15 LoRA cells = 15–20 videos.**

## Timing budget

- Model download (`Wan-AI/Wan2.2-TI2V-5B-Diffusers`, ~16 GB): 15–30 min.
- LoRA downloads: 5 min.
- Harness script: 30 min while download runs.
- Baseline generation (5 videos × ~60–90 s, no LoRA acceleration): 5–8 min.
- LoRA generation (10–15 videos × ~60–90 s): 10–22 min.
- **Total wall clock: ~1.5–2.5 hours.**

## Outputs

- Videos: `docs/runs/wan22-eval/<prompt_id>__<lora>__w<weight>.mp4`
- Per-video JSON sidecar: prompt, lora_id, weight, seed, wall_clock_s,
  load_ok (true/false), error_if_any.
- Summary markdown: `docs/runs/wan22-eval/SUMMARY.md` — table of all
  videos with thumbnails, plus a "what worked / what didn't" section.

## What I will NOT do in this eval

- No backend integration. No changes to `providers/video/`, no Alembic migration,
  no LoRA-selection field on `ScenePrompt`. That's the next phase, gated on
  these results.
- No promises about whether 5B is the right model — that's the decision this
  eval is meant to inform.

## Decision gate after this run

1. If 5B baseline quality is at least on par with LTX → proceed to evaluate
   A14B for the LoRA ecosystem benefit, or commit to 5B with what 5B LoRAs exist.
2. If 5B baseline is meaningfully worse than LTX → stop here, don't bother with A14B.
