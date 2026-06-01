# Plan: Identity-Preserving Character Variations

Render the same character (Sadhguru today, anyone tomorrow) across many poses, expressions, and outfits with the SAME confidence we'd get from a celebrity LoRA — without training one per project.

## Executive Summary

- **Ship in week 1: PuLID-FLUX side-pipeline** for action stills, while keeping SD3.5 for portraits/backgrounds. Identity-quality gap vs SD3.5+IP-Adapter (which doesn't really exist for SD3.5) is large enough to justify a second model.
- **Backup: InstantID on SDXL** if FLUX VRAM doesn't fit our 16 GB headroom alongside the rest of the pipeline. Quality is close, integration is more proven, and SDXL ControlNets (OpenPose, Depth) are mature for Phase 4.
- New `identity_provider` abstraction in `backend/app/providers/image/`, with the canonical portrait pre-encoded once into a face-embedding cache (`storage/characters/<project_uuid>/<safe_name>.idemb.pt`) keyed off the portrait file mtime — so we never re-extract on every still.
- `action_stills.py` gets one new branch: if `primary_char.reference_image_path` exists AND `image_provider.supports_identity` is true, we call `image_provider.generate_with_identity(...)` instead of `generate_image(...)`. Pure t2i path is preserved for non-human characters.
- Phase out the `init_image_path`/`strength` SD3.5 img2img path entirely — that's the "drags toward portrait crop" failure we already caught. Identity comes from face embeddings, not pixel re-noising.

## 1. Technique Survey

| Technique | Base model | Identity quality | Pose flex | Outfit flex | VRAM (5070 Ti, 16 GB) | Latency / image | Integration cost | License |
|---|---|---|---|---|---|---|---|---|
| **IP-Adapter Face / FaceID-Plus-v2** | SD1.5, SDXL only — **no SD3.5 release** | Medium-high (SDXL); Medium (SD1.5) | High | High | SDXL ~10 GB w/ offload | 4–8 s | Low; diffusers built-in | Apache-2 (h94/IP-Adapter); InsightFace face encoder is non-commercial |
| **InstantID / InstantID-XL** | SDXL only | High | High | High | ~12 GB w/ ControlNet stack + offload | 8–12 s | Medium; needs IdentityNet + ControlNet | Apache-2 model; InsightFace antelopev2 weights = **non-commercial** |
| **PuLID** (SDXL) | SDXL | Very high | High | High | ~11 GB | 6–10 s | Medium | MIT model code; uses InsightFace (non-commercial) |
| **PuLID-FLUX** | FLUX.1-dev | **State of the art (2025)** | Very high | Very high | ~14–15 GB w/ FP8 + offload — **tight** on 16 GB | 12–20 s @ 20 steps | Medium-high; new pipeline class | FLUX.1-dev is **non-commercial research license** — blocking for any product launch; PuLID-FLUX itself MIT |
| **FaceID-Plus / FaceID-Portrait** | SD1.5/SDXL | High | Med-high | High | ~8–10 GB | 4–6 s | Low | Apache-2 + InsightFace |
| **Reference-only ControlNet** | SD1.5 | Low-medium (style transfer, not true identity) | Low (constrains pose too) | Low | ~6 GB | 3–5 s | Low | OpenRAIL |
| **DreamBooth / per-char LoRA** | SDXL or FLUX | **Highest** (with 10–20 portraits) | Very high | Very high | Training: ~14 GB at SDXL 1024; **5–10 min unrealistic** — realistic is 20–40 min for SDXL with kohya, longer for FLUX | Inference adds ~2 s vs base | High; need training infra, dataset gen, eval | Per-base-model license |
| **FLUX.1 Redux** | FLUX.1-dev | Image-prompt variation, not face-identity. Style/comp transfer | Low-med | Low-med | ~13 GB | 12–18 s | Medium | Same FLUX-dev non-commercial |
| **OmniGen / OmniGen-V2** | Custom 3.8 B unified | Med-high; multi-ref native; no face encoder needed | High | Very high | ~11–12 GB FP16 | 15–25 s | Medium; replaces SD3.5 entirely for stills | MIT |
| **SD3.5 face/identity ControlNets** | SD3.5 | **None shipped as of 2026-05** — only Canny / Depth / Blur from Stability. No IP-Adapter-SD3 with face support. | — | — | — | — | — | — |

**Key observation:** SD3.5 has no usable identity-conditioning ecosystem. Anything we pick is either a model swap (FLUX, SDXL, OmniGen) or a per-character LoRA on top of SD3.5 (slow, training infra cost). The cheapest *quality* path is to swap models for the action-stills path only.

## 2. Recommendation

**Primary: PuLID-FLUX** for action stills. Identity preservation is closest to "celebrity LoRA without training" — it embeds the face into FLUX's joint attention via a contrastive face encoder, separating ID from pose/outfit/expression. We get all 12 stills locked to one face. **Caveat — license:** FLUX.1-dev is non-commercial. If this app ships commercially, fall back to InstantID-XL.

**Backup: InstantID-XL.** Mature, well-documented, runs comfortably in 12 GB, stacks with ControlNet-OpenPose for Phase 4. We accept a small identity-quality drop and the InsightFace antelopev2 non-commercial weight issue (replaceable with `buffalo_l` for commercial).

Why not LoRA: 5–10 min per character is optimistic; we'd also need 10–20 portrait variants per character to train on (we have 1). Defer to Phase 6 if PuLID-FLUX still drifts on edge cases.

## 3. Architecture Changes

**New file:** `backend/app/providers/image/pulid_flux_provider.py` (or `instantid_provider.py`). Same `ImageProvider` interface but adds:

```python
class ImageProvider(ABC):
    supports_identity: bool = False
    async def generate_with_identity(
        self, prompt: str, negative_prompt: str, output_path: Path,
        identity_ref: IdentityRef, settings: ImageSettings,
    ) -> ImageResult: ...
```

**New dataclass:** `IdentityRef(portrait_path: str, embedding_cache_path: str)` — the embedding cache is a `.pt` file written next to the portrait the first time we encode it.

**New helper:** `backend/app/agents/image_pregen/_identity.py` — `get_or_create_identity_ref(char) -> IdentityRef`. Mirrors the `_assets.py` pattern. Cached by portrait file mtime + face-encoder version.

**`action_stills.py` change** (one branch added in `_generate_one_still`, ~10 lines): if `getattr(image_provider, "supports_identity", False)` and `primary_char.reference_image_path` exists, route to `generate_with_identity`. Drop the `init_image_path` / `strength` fields from the call site for this path; they remain for the non-identity provider.

**`ImageSettings` change:** add `identity_strength: float = 0.85` and `identity_ref_paths: list[str] = []` (multi-ref support is in PuLID and helps a lot when 2 portraits exist).

**`prompts.py` change:** when an identity provider is used, **drop** the verbose physical description from the SD prompt — let the embedding carry identity, let the prompt carry pose/outfit/expression. Keeps prompts under FLUX's 256-token T5 budget. The `WHO` block in `_scene_action_user_message` shrinks to name + clothing only.

**`character_portraits.py`:** unchanged — still SD3.5. After portrait generation, additionally call `_identity.precompute_embedding(char)` so subsequent stills are warm.

**`ltx_provider.py`:** no changes. Stills feed in identically.

**`config.py`:** add `image_identity_provider: str = "pulid_flux"`, `pulid_id_strength: float = 0.85`, `pulid_steps: int = 20`. Reuse `gpu_python_path`.

**Subprocess script:** `~/pulid-flux/generate_pulid.py` (or hosted in repo under `scripts/`), mirroring `~/sd35-medium/generate_sd35.py`'s contract. Same subprocess-isolation rationale: full VRAM release after each call. Pre-extracted face embedding passed as `--id-embed path.pt` so we don't reload InsightFace per still.

## 4. Implementation Phases

**Phase 1 (1 day) — MVP identity lock on Sadhguru.** Stand up `~/pulid-flux/generate_pulid.py` outside the app; verify on a project's existing portrait → 6 pose/outfit variations; eyeball identity. Decision gate: ship or fall back to InstantID-XL.

**Phase 2 (1 day) — provider integration.** Add `pulid_flux_provider.py`, `_identity.py`, the `supports_identity` branch in `action_stills.py`, embedding cache. Re-run a test project end-to-end. Compare cea11591 reference run side-by-side.

**Phase 3 (0.5 day) — outfit slot.** Add `Character.outfit_variants: list[str]` (DB migration) and a `scene.outfit_override` field; prompt builder threads this in instead of fixed `clothing_description`. Embedding stays shared.

**Phase 4 (1 day) — pose ControlNet stacking.** If on InstantID-XL, add OpenPose ControlNet driven by an LLM-generated stick-figure pose hint (we already have [controlnet-openpose-implementation-plan.md](controlnet-openpose-implementation-plan.md)). PuLID-FLUX path skips this — pose comes from prompt cleanly enough.

**Phase 5 (0.5 day) — identity-drift regression suite.** Extend [still_critic.py](../backend/app/agents/still_critic.py) with a new check: vision-LLM compares each still to the canonical portrait (`reference_image_path`) and outputs `identity_match: 0.0–1.0` plus per-feature notes (nose / jaw / eye shape). Threshold rejection at <0.7 triggers regen with seed bump. Run nightly across a fixed 3-character test set.

## 5. Risks & Open Questions

- **VRAM headroom.** PuLID-FLUX FP8 is 14–15 GB. Subprocess isolation (already our pattern) means no co-resident SD3.5/LTX. Risk: with FLUX text encoders + face encoder we OOM at higher resolution. Mitigation: cap stills at 768×1024, use FP8 weights, fall back to InstantID-XL at 11 GB.
- **License.** FLUX.1-dev = non-commercial. Surface this in the recommendation now; if "ship commercially" is the goal, InstantID-XL is the actual primary. Also: replace InsightFace antelopev2 with `buffalo_l` for commercial use (small ID-quality drop).
- **Non-human characters.** PuLID/InstantID assume human face landmarks. For mascots/animals/animated characters, fall through to current SD3.5 t2i path — `supports_identity` becomes a per-character signal driven by `character.is_human`. Phase 6 candidate: per-mascot LoRA.
- **Phase 5 still drifting.** Fallback ladder: (a) increase `identity_strength` to 0.95; (b) two-portrait reference (front + 3/4); (c) train per-character SDXL LoRA on 10 synthesized PuLID variants of the portrait — closes the remaining gap.
