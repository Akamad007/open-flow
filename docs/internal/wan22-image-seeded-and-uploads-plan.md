# Wan22 Image-Seeded Generation + User Uploads — Implementation Plan

Status: draft 2026-05-22
Author: pair-design with Claude
Target pipeline: `wan22_text_only` profile (vanilla Wan2.2 TI2V-5B base)

**Big shortcut:** the LTX pipeline already has a working image-pregen path (`ImagePreGenAgent` produces per-scene action-stills with character + product baked in via SD3.5 + InstantID). This plan reuses that scaffold end-to-end and only wires it into Wan22 — saves about 50% of the original estimate.

## 1. Goals

Two coupled features that together let the Wan22 pipeline produce identity-locked, brand-faithful ads:

**A. Image-seeded video (SD3.5 → Wan22 I2V).**
Today Wan22 scenes are pure text-to-video except for inter-scene last-frame chaining. We add a real first-stage image gen (SD3.5) that produces a per-scene canvas with the right character + product + composition, then Wan22 animates from that canvas as I2V. This is the lever for face/anatomy/product fidelity — diffusion in latent video space cannot match what a static-image model can do in a single frame.

**B. User-uploaded character + product images.**
The user uploads a face/full-body shot of their character and a hero shot of their product through the web UI. The pipeline reads those uploads and uses them as the identity / product reference for image gen (Feature A) instead of generating a synthetic character from text. End result: the user's actual model and the user's actual product appear in the ad.

Both features must compose: a user-uploaded character image flows into SD3.5 (img2img / InstantID) → Wan22 I2V. No new model weights, no architecture rewrites.

## 2. Current state (what already exists in the repo)

**Most of the image-gen scaffold is already built for LTX.** This plan is mostly about turning it on for Wan22 + wiring uploads.

| Component | Path | Status |
|---|---|---|
| Wan22 CLI | `wan22_generate.py` | T2V + I2V via `--condition-image`. I2V works. |
| SD3.5 CLI | `~/sd35-medium/generate_sd35.py` | T2I + img2img (`--init-image`, `--strength`). Working. |
| SD3.5 provider | `backend/app/providers/image/sd35_provider.py` | Subprocess wrapper. Used today. |
| InstantID provider | `backend/app/providers/image/instantid_provider.py` | Dual-CN (face + pose). Default on (`identity_provider_enabled: True`). Production-tested. |
| **ImagePreGenAgent** | `backend/app/agents/image_pregen_agent.py` + `backend/app/agents/image_pregen/{character_portraits,backgrounds,products,action_stills,pose_refs,pose_library}.py` | Fully built and validated against LTX. Generates: character portraits (SD3.5 + InstantID), background plates, product hero refs, per-scene action stills with character + product baked in. |
| Image pregen stage | `backend/app/orchestration/stages/image_pregen.py` | Wires the agent. Gated by `profile.image_pregen_enabled` and `profile.pin_action_stills`. Both flags currently `False` on the Wan22 profile — that's the only reason it's not running. |
| Wan22 provider | `backend/app/providers/video/wan22_provider.py` | Has `condition_image_path` in `VideoSpec`. Currently only uses it for inter-scene last-frame chaining. Needs to also accept the image_pregen `scene_action_seq` asset. |
| Scene video stage | `backend/app/orchestration/stages/scene_video.py` | Picks the per-scene canvas. Needs to prefer `scene_action_seq` over last-frame when image_pregen produced one. |
| Asset model | `backend/app/models/asset.py` | `AssetType` enum already has every type we need: `character_ref`, `background_ref`, `scene_ref`, `scene_action`, `scene_action_2`, `scene_action_seq`, `product_ref`. No schema change. |
| Project upload UI | `frontend/` | No upload widget today. Project creation is text-only. **This is the only meaningful new build.** |

**Implication.** Feature A is mostly a configuration / wiring change — flip the profile flags, wire the asset path into the Wan22 condition image. Feature B is a frontend upload widget + a few-hundred-line backend endpoint that writes to the same `assets` table the image_pregen agent already reads from. No agent rewrite, no new model code.

## 3. Feature A — SD3.5 → Wan22 I2V (image-seeded video)

### 3.1 Pipeline flow (per scene, after planning + prompting stages)

```
[scene_prompt + character refs + product refs]
              ↓
   SD3.5 generates SCENE CANVAS (832×480)
   - if character_ref exists: SD3.5 img2img with character_ref as init
                              + InstantID face-identity if face crop available
   - if product_ref exists: composite product into the canvas via img2img
                            (existing `product_img2img_strength = 0.65`)
   - else: pure t2i from scene prompt
              ↓
   SCENE CANVAS image saved to storage/scenes/{project}/{scene}_canvas.png
   Asset row: asset_type=scene_ref, file_path=...
              ↓
   Wan22 I2V: --condition-image scene_canvas.png + scene video prompt
              ↓
   scene_NNN_{uuid}.mp4
              ↓
   last frame extracted → next scene's canvas seed (existing logic still applies)
```

The first scene's canvas comes from SD3.5. Subsequent scenes either chain via last-frame OR get a fresh SD3.5 render — controlled by a new setting `wan22_scene_canvas_strategy` (see 3.4).

### 3.2 Files to change (the minimal set)

The existing ImagePreGenAgent already produces a `scene_action_seq` asset per scene that contains the character + product composited into the right environment. We reuse it verbatim — we just need to (a) turn it on for the Wan22 profile and (b) feed its output to Wan22 as the I2V condition image.

1. **`backend/app/orchestration/profiles.py`** — new profile `wan22_image_seeded`:
   - Copy `wan22_text_only`.
   - Set `image_pregen_enabled = True`.
   - Set `pin_action_stills = True`.
   - Set `video_provider = "wan22"`.
   - Keep the existing `wan22_text_only` profile as-is for users who want pure T2V.

2. **`backend/app/orchestration/stages/scene_video.py`** — canvas resolution priority:
   - Order to check when building Wan22's `--condition-image` for scene N:
     1. (existing) `scene_NNN-1_last_frame.png` if N > 0 AND `canvas_strategy == "chain_last_frame"`.
     2. **(new)** `Scene.scene_action_seq_asset` if it exists AND profile has `pin_action_stills`.
     3. (existing) None → fall back to pure T2V.
   - For `canvas_strategy = "fresh_per_scene"`, prefer step 2 over step 1 always.
   - For `canvas_strategy = "hybrid"`, use step 2 only when `Scene.continuity_from_previous` is null/"cut", else step 1.

3. **`backend/app/config.py`** — one new setting:
   - `wan22_scene_canvas_strategy: str = "hybrid"` — `fresh_per_scene` | `chain_last_frame` | `hybrid`.

4. **`backend/app/providers/video/wan22_provider.py`** — verify no change needed; `condition_image_path` already in `VideoSpec`. Smoke-test that an action_still path flows through.

5. **`backend/app/orchestration/stages/image_pregen.py`** — verify no change needed; reading the profile flags should be enough. If the LTX-specific InstantID daemon shutdown in the `finally` block fires before Wan22, that's actually fine (Wan22 doesn't need InstantID at video time), but we may want to keep daemons alive for the next scene's still gen — add a `keep_alive_for_next_scene` flag.

6. **`wan22_generate.py`** — no change.

7. **`backend/app/providers/image/sd35_provider.py`** — no change. Existing flow is used.

**Net new code: maybe 60-100 lines across these files.** The rest is already there.

### 3.3 Wiring details

**Character ref → SD3.5 init image.** Use SD3.5 img2img with `--init-image <character_ref> --strength 0.55-0.70`. Lower strength preserves identity better; higher strength gives SD3.5 freedom to pose the character in the scene. Per memory `product_img2img_strength: 0.65` is the calibrated default for products; reuse 0.65 for character too as a starting point and tune.

**Product ref → SD3.5 img2img on top of character canvas.** Two-pass:
1. Generate character canvas (no product).
2. Composite product naively (PIL paste like `scripts/test_character_with_bag.py` does), then SD3.5 img2img with the composite as init at `strength=0.55` to harmonize.

This is mechanically similar to the existing product placement plan in `docs/plan-product-placement.md`.

**InstantID hook.** Already wired (`identity_provider_enabled: True`, `instantid_daemon_enabled: True`). When a character has a face-crop reference, use the InstantID dual-CN script for the canvas gen. Per `feedback_action_still_prompt_recipe.md` and `project_identity_dual_cn.md` this gives much better face identity preservation than vanilla SD3.5 img2img.

**Wan22 I2V call.** No change to provider — it already calls `wan22_generate.py --condition-image`. Just make sure scene_video.py passes the scene_canvas path.

### 3.4 Strategy: fresh-per-scene vs last-frame chain

Three modes via `wan22_scene_canvas_strategy`:

- **fresh_per_scene** (default): every scene gets its own SD3.5 canvas. Slower (~2 min/scene extra) but each scene's composition / framing / pose is explicitly controllable by SD3.5. Identity holds via InstantID + character_ref. Use for high-budget multi-shot ads.
- **chain_last_frame**: only scene 0 uses SD3.5 canvas; scenes 1..N use last frame of previous scene. Cheaper (only one SD3.5 call). Use for "single continuous take" ads. This is essentially the existing behavior with SD3.5 seeding scene 0.
- **hybrid**: scene 0 gets SD3.5 canvas; SD3.5 also kicks in when the scene_video stage detects a "scene cut" (per `Scene.continuity_from_previous` being null or "cut"). Otherwise chain. Best of both — recommended once tuned.

### 3.5 Edge cases / risks

- **OOM**: SD3.5 + Wan22 both want ~10 GB peak VRAM. They never run simultaneously (sequential via celery's `concurrency=1`), but the back-to-back load/unload churn might trigger the same GPU bus-fault we saw 2026-05-22. The `INTER_PROJECT_COOLDOWN_S = 30` from queue_scanner doesn't apply inter-scene. Consider adding a 10-15s sleep between SD3.5 → Wan22 to let CUDA settle. Wire as `WAN22_INTER_STAGE_COOLDOWN_S` env.
- **Wall time**: fresh-per-scene at 60-step SD3.5 + 100-step Wan22 = ~12-14 min/scene. A 5-scene 30s ad = ~70 min. Document this in the UI.
- **Scene canvas blank / black**: if SD3.5 fails, fall back to T2V (no `--condition-image`) and warn.
- **Identity drift across scenes when canvas is fresh-per-scene**: SD3.5 alone won't hold identity — InstantID is required. If `identity_provider_enabled: False`, fall back to chain_last_frame.

## 4. Feature B — User-uploaded character + product images

### 4.1 Upload UX

New section on the project create / edit screen (`frontend/src/pages/ProjectCreate.tsx` or similar):

```
Project name: [_________]
Story text:   [_________]
Pipeline:     [ wan22_image_seeded ▾ ]

── Optional: identity + product ──

Character (face/full-body):   [ choose file… ]
                              [▣ apply to all scenes featuring this character]
                              Identity label: [ "main protagonist" ▾ ]

Product (hero shot):          [ choose file… ]
                              Product label: [ "tan Birkin handbag" ____ ]
```

Multiple character + product uploads allowed. Each gets a free-text label that ties to the LLM-detected character/product entities for the same string match.

### 4.2 Storage

- `backend/storage/uploads/{project_id}/character_{label_slug}.png`
- `backend/storage/uploads/{project_id}/product_{label_slug}.png`

DB rows in `assets` table:
- `project_id`: project FK
- `asset_type`: `character_ref` for characters, `product_ref` for products (these enum values already exist — no migration)
- `file_path`: relative path from `storage_root.parent`
- `metadata_json`: `{"source": "user_upload", "label": "main protagonist", "filename": "alice.jpg"}`
- `generation_provider`: `"user_upload"` (to distinguish from SD3.5-generated refs)
- `status`: `complete`

### 4.3 Backend endpoint

New endpoints in `backend/app/api/uploads.py` (new file):

```
POST /api/projects/{project_id}/uploads/character
  multipart/form-data:
    file: <png/jpg/webp>
    label: <string, required>
  → 201 { asset_id, file_path, label }

POST /api/projects/{project_id}/uploads/product
  same shape, asset_type=product_ref
  → 201 { asset_id, file_path, label }

DELETE /api/projects/{project_id}/uploads/{asset_id}
  → 204
```

Validation:
- Max 10 MB per file.
- Resize+pad to 1024×1024 on the server before storage (consistent SD3.5 input shape, simpler downstream).
- EXIF rotation applied + EXIF metadata stripped.
- Reject if not a real image (PIL.Image.open + verify).

### 4.4 Pipeline integration

When the prompting stage runs the LLM that identifies characters/products in the story:
- After the LLM names a character ("Alice, 30s woman"), the stage queries `assets WHERE project_id=$ AND asset_type='character_ref' AND metadata_json->>'source'='user_upload'` and tries to fuzzy-match the LLM label against the user's label.
- On match: link `Character.character_ref_asset_id` to the user upload. Skip SD3.5 character render entirely.
- On no match: proceed with SD3.5-generated character (existing behavior).

Same logic for products via the existing `Product` entity (already in DB per `project_product_and_identity.md` memory).

The scene canvas builder in Feature A then picks the linked character_ref / product_ref asset regardless of source — uploaded or generated — so Feature A code stays the same.

### 4.5 Edge cases

- **User uploads but LLM doesn't find that character in the story**: warn in UI ("character 'Alice' uploaded but not referenced in story text"). Don't block.
- **Multiple uploaded characters in same scene**: per memory `one_char_per_scene.md` we already enforce one character per scene. Reject the scene plan if it tries to combine two uploaded characters in one scene; surface the violation to the user.
- **Face-only crop vs full body**: SD3.5 img2img with a face crop will produce a face-centric composition. For full-body scenes (running, dancing) recommend the user upload a full-body shot. Detect face-only vs full-body via MediaPipe face-detection bbox area in the upload validation; if face-only and the scene is "wide", warn or auto-prompt SD3.5 to extend the body.
- **Product variants** (3 colors of same bag): allow N product uploads with distinct labels; LLM scene planner picks the right one per scene.

## 5. Composition: how A + B work together

The clean separation: **B owns the input refs, A owns how those refs flow into video**. A doesn't know or care whether a `character_ref` asset came from SD3.5 or a user upload. B doesn't know or care how the asset is used downstream.

Default user journey:

1. User opens "New Project" in the UI.
2. Picks `wan22_image_seeded` profile.
3. Types the story.
4. Uploads a face shot of their model and a hero shot of their handbag.
5. Submits.
6. Pipeline: LLM analyzes story → matches "young woman" to uploaded face, "tan handbag" to uploaded bag → image_pregen stage uses uploads as refs → SD3.5 builds per-scene canvases (InstantID for face, img2img for product) → Wan22 I2V animates each canvas → audio + stitch → final 30s ad.

## 6. Implementation order (rollout)

Reuse-driven — most steps are wiring, not building.

1. **Add `wan22_image_seeded` profile** in `profiles.py` (copy `wan22_text_only`, flip `image_pregen_enabled=True` + `pin_action_stills=True`). (~30 min)
2. **Submit a test project with the new profile, no other code change**, and confirm the existing ImagePreGenAgent runs and produces `scene_action_seq` assets per scene. This validates the agent works for Wan22-bound projects too. (~10 min)
3. **Wire canvas resolution in `scene_video.py`** — pick `scene_action_seq` over (or alongside) `last_frame`. Add the three-mode `wan22_scene_canvas_strategy` switch. (~half day)
4. **Validate end-to-end**: submit one project, watch a scene get generated with the action-still as I2V canvas, compare to a same-prompt T2V baseline. Tune `product_img2img_strength` and SD3.5 steps if outputs disagree with the reference. (~half day)
5. **Build upload endpoint** `POST /api/projects/{id}/uploads/{character|product}` + image validation. Server-side only, test via curl. (~half day)
6. **Frontend upload widget** on project create page + label input. (~1 day)
7. **Hook upload label ↔ LLM character/product entity matching** in the prompting stage so user-uploaded refs get linked instead of generated. (~half day)
8. **End-to-end test with real uploaded character + product through `wan22_image_seeded` profile.** Final tuning. (~half day)

Total: **~3-4 working days**, down from the original estimate by reusing the LTX scaffold.

## 7. Open questions

- **Does fresh_per_scene actually help identity vs chain_last_frame + InstantID at scene 0?** A/B test once mode 3 is in.
- **Should we expose `wan22_scene_canvas_strategy` as a per-project setting or keep global?** Lean toward global default + per-project override on the create page.
- **What's the max number of uploaded refs per project we want to support?** Suggest cap at 5 character + 5 product per project to keep the LLM matcher simple.
- **Do we want a "preview my character in this scene" button** that runs only SD3.5 (no Wan22) and shows the user the canvas before the expensive video step? Probably yes — cheap and lets users iterate prompts.
- **GPU bus-fault recurrence under heavier load** (SD3.5 + Wan22 alternating per scene). Watch for it; add the inter-stage cooldown defensively.

## 8. Out of scope (not in this plan)

- LTX provider changes (this is Wan22-specific; LTX rule `NEVER pin pictures as LTX frame conditions` still applies).
- Multi-character per scene (still capped at one per scene per existing memory rule).
- Character pose library / pose-from-upload — separate plan.
- Video-level identity locking via a face-restoration post-pass — already exists (`codeformer_esrgan`) and continues to apply on motion scenes after Wan22 output.
