# Plan: Product Entity for the Ad Pipeline

## Executive Summary

- **One product per project, optional.** Add a first-class `Product` model (parallel to `Character`/`Location`) — not an `Asset` subtype — so it gets its own SD3.5 reference image, its own M2M scene linkage, and its own UI tab. Cap at 1 in v1; schema allows N.
- **Story analyst extracts it; scene planner tags scenes that show it.** Add a `products` array to story-analyst output and per-scene `shows_product: bool` + `product_role` to the scene-planner output. Default-on so every scene displays the product unless the planner explicitly says otherwise.
- **Bake the product into the action still (option a).** A separate transparent "product layer" is a layout nightmare across 12 stills + LTX motion. Bake it via SD3.5 img2img conditioned on the product reference image (`init_image_path` + low strength) so identity/colors transfer. LTX gets the same character+product action stills it already gets — no new conditioning channel.
- **No LTX CLI changes required.** `ltx_generate.py` `LTXConditionPipeline` already accepts character + bg + N action stills. The product is invisible to LTX — it travels inside the action stills.
- **Visual director gets a `PRODUCT` block.** It composes "frosted glass cola bottle with red label" into `dim_content`/`video_prompt`, never the brand name (negative prompt still bans `logo`/`text`).

---

## 1. Story Analyst Changes
Files: [backend/app/agents/story_analyst.py](../backend/app/agents/story_analyst.py), [backend/app/prompts/story_analyst.txt](../backend/app/prompts/story_analyst.txt)

A "product" is a manufactured/branded SKU the ad is selling (bottle, phone, sneaker, cereal box). A "prop" is anything else the character interacts with. LLM heuristic: *"Is this thing the ad is asking the viewer to buy?"* If yes → product.

Add a `products` field to the JSON contract:

```json
"products": [
  {
    "canonical_name": "RedFizz Cola 12oz Bottle",
    "category": "beverage|electronics|apparel|food|personal_care|other",
    "physical_description": "frosted clear-glass bottle, 12oz, narrow neck, red wraparound label",
    "brand_marks": "red label band with white wordmark, embossed bottle base",
    "color_palette": "deep red label, amber-tinted glass, silver crown cap",
    "hero_angle": "three-quarter front, slight low angle, label fully visible"
  }
]
```

Cap **at most 1 product** in v1 (`MAX_PRODUCTS = 1`, validate alongside `_validate_style_lock`). Multi-product is a v2 problem (split-screen ads, bundles).

Update `story_analyst.txt` after section 4 LOCATIONS with section "5. PRODUCTS" explaining the prop-vs-product distinction. Bump `max_tokens` 4096 → 5120.

## 2. Scene Planner Changes
Files: [backend/app/agents/scene_planner.py](../backend/app/agents/scene_planner.py), [backend/app/prompts/scene_planner.txt](../backend/app/prompts/scene_planner.txt)

Add to per-scene JSON:
```json
"shows_product": true,
"product_role": "hero|holding|background|none"
```

Rules:
- For 1-product ads, default `shows_product=true` for every scene. Only `false` for atmospheric shots that explicitly precede the product reveal.
- Pass `products` list into context (mirror `_format_locations`) and surface in user prompt.
- `product_role="hero"` for the product close-up beat; `holding` for character-with-product; `background` for product-on-counter; `none` skips entirely.

## 3. DB Model — New `Product`

**Reuse `Asset`? No.** Asset is for generated outputs. Product is a first-class entity like `Character`/`Location` with descriptive metadata, a generated reference image path, and an M2M scene linkage.

New `backend/app/models/product.py` (mirror `character.py`):
```python
class Product(Base):
    __tablename__ = "products"
    id: UUID PK
    project_id: UUID FK → projects.id (CASCADE)
    canonical_name: String(300)
    category: String(50)
    physical_description: Text
    brand_marks: Text
    color_palette: Text
    hero_angle: Text
    user_uploaded_path: String(1000)   # OPTIONAL — user-supplied brand asset
    reference_image_path: String(1000) # generated SD3.5 hero shot
```

Add to `backend/app/models/scene.py` (mirror `scene_characters`):
```python
scene_products = Table(
    "scene_products", Base.metadata,
    Column("scene_id", UUID, ForeignKey("scenes.id", ondelete="CASCADE"), primary_key=True),
    Column("product_id", UUID, ForeignKey("products.id", ondelete="CASCADE"), primary_key=True),
    Column("product_role", String(20), nullable=False, default="holding"),
    Column("shows_product", Boolean, nullable=False, default=True),
)
```

Putting `product_role` and `shows_product` on the join lets one scene reference different products in v2 without schema changes.

Add `products` relationship on `Scene`, on `Project`, and back-ref on `Product`. Add new `AssetType.product_ref = "product_ref"` enum value.

## 4. Product Reference Image
**v1: SD3.5 t2i hero shot, no upload UX.** v2: optional brand-asset upload via API. SD3.5 generic hero shots are good enough for category fidelity ("a frosted cola bottle"); the upload UX is a sizable scope item. Document that `user_uploaded_path` overrides `reference_image_path` once supplied.

New `backend/app/agents/image_pregen/products.py` (~80 lines, mirrors `backgrounds.py`):
- `generate_all(db, project_uuid, image_provider, llm, story_summary, errors)` enumerates linked products and calls `_generate_one`.
- Storage path: `settings.storage_root / "products" / str(project_uuid) / f"{safe_name(product.canonical_name)}.png"`.
- Calls new `build_product_prompt(llm, prod, story_summary)` in `prompts.py` (mirrors `build_character_prompt`).

New `backend/app/prompts/product_hero.txt` (mirrors `character_portrait.txt`):
- Forces clean studio-product-shot framing using `hero_angle`.
- Negative prompt retains `logo, text, watermark` ban — the brand marks travel via `physical_description`/`brand_marks` ("red wraparound label" not "Coca-Cola wordmark").
- Background-removed via `remove_background()` like `character_portraits.py` so it can be re-composited into action stills.

The product reference is **not** added to LTX's conditioning stack — it's only used as the SD3.5 init image for action stills (next section).

## 5. Action-Still Integration — Bake the Product (Option A)

**Recommended: option (a), SD3.5 img2img with product reference as init_image.**

Why not (b) (separate product layer composited at LTX time): requires per-second product-position metadata — where on the frame, what scale, occlusion by hand, perspective. Generating that consistently across 12 stills is a layout-planning problem to solve from scratch. LTX won't enforce 2D layout coherence either.

Implementation in [action_stills.py](../backend/app/agents/image_pregen/action_stills.py) `_generate_one_still`:
1. After `_resolve_primary_char`, also resolve linked product via `scene.products` M2M.
2. If `shows_product=true` and `product.reference_image_path` exists, set `ImageSettings.init_image_path = product.reference_image_path` and `strength=0.55–0.7` (currently `strength=0.0` for pure t2i — the field already exists, we just stop passing 0).
3. Append a "PRODUCT" block to the user message in `_scene_action_user_message` describing the product *visually but not by brand*. `physical_description` + `brand_marks` injected verbatim. `product_role` controls phrasing: `holding` → "the character grips the [description] in the right hand"; `hero` → "extreme close-up on the [description], character's hand entering frame".
4. Add brand-name blocklist (gathered from `Product.canonical_name`) to `_strip_other_chars`-style sanitation so the action description doesn't accidentally name the brand.

Brand fidelity escape hatches (document, don't implement v1):
- **IP-Adapter for SD3.5** would let the product image act as a "subject reference" with much higher fidelity than img2img init. v2 task — right answer for "real Coca-Cola label fidelity".
- **ControlNet (canny/depth)** locks product silhouette but not label — useful when shape is the differentiator (sneaker, phone).
- v1 with img2img + low strength: expect "looks like a generic frosted cola" not "looks like Coca-Cola". Acceptable because the negative prompt bans text/logos anyway.

The "product still per second" layout problem is sidestepped because the SAME init image feeds all 12 stills with the same seed offset — the bottle's appearance stays coherent. Position varies by per-second action description.

Still-critic update: add `product_visible` boolean check so a missing product triggers regeneration (parallel to existing `subject_visible`).

## 6. LTX Conditioning — No CLI Changes

Traced [ltx_generate.py](../ltx_generate.py) multi-image conditioning path and `ltx_provider.py`. LTX 0.9.8 via `LTXConditionPipeline` accepts an arbitrary number of `LTXVideoCondition` objects pinned at frame indices. Could add `--product-image` pinned at frame `n//4` with strength 0.6 — but costs:
- Another conditioning channel competing with character/bg for LTX attention budget. We're already near saturation (character strength=0.75, bg strength=0.7).
- A separate transparent product still per second (option b's failure mode).

**Decision: don't add a new LTX channel.** Product travels inside action stills. LTX motion-interpolates between stills; if every action still has the bottle in roughly the right place, LTX produces coherent in-hand motion.

If brand fidelity is later required, the right place is SD3.5 IP-Adapter (§5), not a new LTX channel.

**Concrete CLI/pipeline changes: zero.** Action stills already contain the product baked in.

## 7. Visual Director Prompt Update
Files: [backend/app/agents/visual_director.py](../backend/app/agents/visual_director.py), [backend/app/prompts/visual_director.txt](../backend/app/prompts/visual_director.txt)

In `_build_user_prompt`, pass linked product into user message under a new "PRODUCT IN SCENE" block (mirror existing CHARACTERS block):
```
PRODUCT IN SCENE (use @ProductImage in dim_input):
  - <canonical_name>:
    Visual: <physical_description>
    Marks : <brand_marks>
    Role  : holding | hero | background
    NOTE: depict by visual description ONLY — never write the brand name, "logo",
          "label text", "wordmark" or any of the negative-prompt-banned terms.
```

Visual director already follows "describe by appearance not name" for characters — same rule for products. `dim_content` becomes `"… kneels on the parched soil, gripping a frosted clear-glass bottle with a deep red wraparound label …"`. Existing negative `logo, text, words, watermark` is intentional and correct.

`scene_prompt_validator.py`: no v1 change. v2: check that if `shows_product=true`, `dim_content` mentions a noun matching the product's category vocabulary (bottle/phone/box).

## 8. Stitching / UI

- **`frontend/src/types/index.ts`**: add `'product_ref'` to `AssetType` union.
- **`ProjectDetailPage.tsx`**: add `'products'` tab (mirror `'locations'`). Tab pulls from a new `/api/projects/{id}/products` endpoint.
- **`backend/app/api/products.py`** (new, mirrors `locations.py`): list/get/update product metadata; future endpoint accepts user upload.
- **`backend/app/api/images.py`** (`ProjectImagesResponse`): add `products: List[ProductImageItem]` parallel to characters/locations.
- **`test_pipeline_partial.py`** (`_print_summary`): add product info next to LOCATION/CHARACTER prints.
- **`pipeline_triggers.py`**: add `AssetType.product_ref` to the asset-types tuple so `images` stage replays cleanly.
- **Stitching**: no changes. Stitching is invisible to product.

## 9. Concrete File-Edit List (Implementation Order)

1. `backend/app/models/product.py` — NEW. ~35 lines, mirrors `character.py`.
2. `backend/app/models/scene.py` — add `scene_products` Table + `products` relationship. ~12 lines.
3. `backend/app/models/project.py` — add `products = relationship(...)`. 1 line.
4. `backend/app/models/asset.py` — add `product_ref = "product_ref"`. 1 line.
5. `backend/alembic/versions/<rev>_add_products.py` — NEW migration: `products` + `scene_products` tables + `ALTER TYPE assettype ADD VALUE 'product_ref'`.
6. `backend/app/prompts/story_analyst.txt` — add PRODUCTS section. ~15 lines.
7. `backend/app/agents/story_analyst.py` — extend JSON template; add `MAX_PRODUCTS=1` validation. ~20 lines.
8. `backend/app/orchestration/stages/story_analysis.py` — add `_create_products` (mirror `_create_locations`). ~15 lines.
9. `backend/app/prompts/scene_planner.txt` — product-visibility rule. ~8 lines.
10. `backend/app/agents/scene_planner.py` — load products into context, format helper, extend output JSON with `shows_product`/`product_role`. ~25 lines.
11. `backend/app/orchestration/stages/scene_planning.py` — `_resolve_product_id` + product linkage in `_build_scene`. ~20 lines.
12. `backend/app/prompts/product_hero.txt` — NEW. ~25 lines.
13. `backend/app/agents/image_pregen/prompts.py` — `build_product_prompt` + product-block injection in `_scene_action_user_message`. ~40 lines.
14. `backend/app/agents/image_pregen/products.py` — NEW. ~80 lines.
15. `backend/app/agents/image_pregen/action_stills.py` — resolve product, set `init_image_path`/`strength` when `shows_product=true`. ~15 lines.
16. `backend/app/agents/image_pregen_agent.py` — call `products.generate_all` between `backgrounds` and `action_stills`. 3 lines.
17. `backend/app/agents/visual_director.py` — extend `_build_user_prompt` with PRODUCT IN SCENE block. ~20 lines.
18. `backend/app/agents/still_critic.py` — add `product_visible` to verdict. ~15 lines.
19. `backend/app/api/products.py` — NEW, list/get endpoints. ~60 lines.
20. `backend/app/api/__init__.py` — register router. 2 lines.
21. `backend/app/api/images.py` — add `products` to `ProjectImagesResponse`. ~25 lines.
22. `backend/app/api/generate/pipeline_triggers.py` — add `AssetType.product_ref`. 1 line.
23. `frontend/src/types/index.ts` — extend `AssetType` union. 1 char.
24. `frontend/src/pages/ProjectDetailPage.tsx` — add `'products'` tab. ~30 lines.
25. `test_pipeline_partial.py` — print product info in images-stage summary. ~5 lines.

Total ≈ 25 file touches, almost all small (most well under the 50-line cap).

## 10. Risks + Open Questions

- **Brand-asset upload UX:** Is v1 SD3.5-only OK, or does the demo need real Coca-Cola label fidelity? If the latter, IP-Adapter (or a manual upload that bypasses generation) is required and that is a meaningful scope expansion. **Need decision.**
- **Multi-product:** v1 caps at 1. Schema supports N. Confirm punt-to-v2.
- **Product changes across scenes** (full → empty bottle, sealed → opened): v1 assumes single product reference image. Per-scene product-state metadata is v2 unless flagged.
- **Negative-prompt collision:** Visual director negative bans `logo, text, watermark`. Real labels include text. SD3.5 will likely render some squiggle-text on the bottle. Acceptable for v1; flag for review.
- **Strength=0.55–0.7 for img2img:** guess. Will need calibration on the first end-to-end run. Lower → more SD3.5 freedom (better human anatomy, weaker product); higher → tighter product fidelity but human pose/action degrades.
- **SD3.5 init_image_path support:** [action_stills.py:93](../backend/app/agents/image_pregen/action_stills.py#L93) currently passes `None`. Verify `backend/app/providers/image/` actually plumbs that through to a real img2img call before kickoff — if not, add an `img2img` flag to `ImageSettings` first.
- **Render order:** products must generate BEFORE action_stills. Step 16 ordering (`portraits → backgrounds → products → action_stills`) handles this. Action stills referencing a missing product reference must fall back to pure t2i without crashing.
