# Clothing Consistency Across Action Stills (and into LTX)

## The leak

Today the dual-CN pipeline locks the **face** (InstantID) and the **body pose**
(OpenPose skeleton). Clothing is driven only by the SDXL **text prompt**.

That means every action still is an independent generation conditioned on
`clothing_description = "red windbreaker over black tee, dark joggers, white
trainers"`. SDXL paraphrases that text into pixels with a fresh random seed and
slightly different attention noise per still — colors shift, sleeve length
wanders, the windbreaker becomes a hoodie, the trainers gain a stripe. LTX then
inherits that drift across the 6 stills it consumes per scene.

InstantID does **not** carry clothing. Its embedding is face-only by design.

## Ideas ranked by ROI

### Tier 1 — cheap and immediate

**1.1 Outfit-string lock**

When the LLM generates `Character.clothing_description` once at story-analysis
time, every downstream prompt (portrait, action stills, LTX video) MUST use
that string **verbatim** — no LLM paraphrasing per scene. Today the
visual_director and prompt builders re-paraphrase per scene which introduces
text drift before SDXL even runs.

- File: [backend/app/agents/image_pregen/prompts.py](backend/app/agents/image_pregen/prompts.py)
- Concrete change: in the action-still prompt builder, splice
  `character.clothing_description` literally into the prompt template instead
  of letting the LLM rewrite it.
- Cost: ~1 hour. Partial fix (~40% of the drift).

**1.2 Per-scene deterministic seed**

All 6 stills of one scene use the same seed (e.g. `seed = 1000 + scene.order_index`)
rather than `seed = base + scene*N + still_idx`. Identical seed + identical
clothing string + same pose-ref family → SDXL produces visually closer
clothing across stills. Different scenes can still differ.

- File: [backend/app/agents/image_pregen/action_stills.py](backend/app/agents/image_pregen/action_stills.py)
- Cost: ~1 hour. Partial fix.

### Tier 2 — main fix, single-day implementation

**2.1 IP-Adapter clothing reference on top of InstantID-XL Pose**

Add IP-Adapter Plus (image-prompt adapter) to the InstantID daemon pipeline.
The reference image = canonical character portrait. IP-Adapter encodes the
**visual style features** (fabric texture, exact colors, garment shape) that
text alone cannot pin down.

```
Portrait ──┐
           ├─ InsightFace embedding ─→ InstantID  ─┐
           └─ CLIP-image embedding   ─→ IP-Adapter ┤
                                                   ├─→ SDXL UNet → action still
Pose ref ─→ OpenPose skeleton       ─→ OpenPose CN ┘
```

- IP-Adapter scale: 0.5 (clothing/style)
- InstantID scale: 0.8 (face — kept dominant)
- OpenPose scale: 0.65 (pose — unchanged)

InstantID-XL community pipelines already support this stack (the
`ip_adapter_image` arg on `StableDiffusionXLInstantIDPipeline`). Single weights
download (~700 MiB), no training.

- Files to touch:
  - `~/instantid/generate_instantid_pose.py` (daemon — add `ip_adapter_image`
    arg, load `ip-adapter-plus_sdxl_vit-h.safetensors`)
  - [backend/app/providers/image/instantid_provider.py](backend/app/providers/image/instantid_provider.py)
    (pass canonical portrait path through the daemon protocol)
- Cost: ~1 day. Strongest fix; expected ~85% consistency.

### Tier 3 — heavy guns, only if Tier 2 still leaks

**3.1 Reference-only ControlNet**

Diffusers' `ReferenceOnlyAttnProcessor` shares cross-attention from a
reference image into the UNet without an extra model file. Lighter than
IP-Adapter but less control over scale. Worth trying as an alternative to 2.1
if VRAM is tight.

**3.2 Per-character LoRA (DreamBooth)**

Train a small SDXL LoRA on the canonical portrait + 5-10 augmented variants
(different lighting, slight rotation). LoRA encodes the exact garment.

- Train cost: ~10 min on RTX 4070+ per character
- Inject at inference: standard `pipe.load_lora_weights(...)`
- Reusable across scenes within an ad; throwaway between ads.
- Justified only if 2.1 fails to reach the bar. Implementation: ~2 days
  including the training harness.

**3.3 Garment-swap inpaint pass (OOTDiffusion / IDM-VTON)**

Generate the action still with whatever clothing SDXL invents, then run a
virtual-try-on inpaint pass that pastes the canonical garment onto the
generated body using a separate diffusion model. Two extra models on disk,
2× inference cost per still. Highest fidelity but biggest engineering lift.

## Recommended sequence

1. **Today** — ship Tier 1.1 + 1.2 together (~2 hr). Run a yoga_mat / sf_runner
   pair and visually compare.
2. **This week** — ship Tier 2.1 (IP-Adapter clothing reference). This is the
   real fix. Tier 1 holds the line until then.
3. **Re-evaluate** after 2.1 is live. If clothing drift is still visible across
   scenes (not just within), look at LTX-side text drift first (the LTX prompt
   currently re-describes clothing per scene, which can repaint the garment
   during motion synthesis even when the input stills are consistent).
4. **Last resort** — Tier 3 (LoRA training or garment-swap).

## What NOT to do

- **Don't** add yet another LLM "clothing checker" pass. The fix has to be in
  the conditioning, not in critique.
- **Don't** lower InstantID scale to make room for clothing. That weakens face
  identity, which is the asset that's already working. Stack adapters; don't
  rebalance away from face.
- **Don't** pre-composite the canonical portrait as a sprite over the
  background. Pose variation is the whole reason we have action stills.
