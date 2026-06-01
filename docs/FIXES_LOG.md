# Pipeline Fix Log

Chronological record of deliberate changes — what broke, what was fixed, and why.
Read this before touching config, prompts, or provider code to avoid re-introducing known-bad states.

---

## F-LANDSCAPE-WIDE (iter5)
**Changed:** `ltx_width=1024`, `ltx_height=576` (16:9 landscape) in config.py + .env
**Why:** Portrait 576×1024 wasted canvas for wide/establishing shots. Landscape matches advertising convention and gives more environment context.
**Do not revert:** .env must also be updated — Pydantic Settings reads .env first and overrides config.py defaults.

---

## F-TEXT-ONLY-LTX (iter6)
**Changed:** `image_pregen_enabled=False`; LTX runs pure text-to-video with a gray placeholder condition (strength=0.05).
**Why:** Action stills pinned into LTX as frame conditions caused character bleed, stiff poses, and face distortion. Removing them dramatically improved motion quality. The gray placeholder is required because LTXConditionPipeline (the only one that works with the FP8 checkpoint) crashes with an empty conditions list.
**Do not revert image_pregen:** Turning it back on re-introduces the condition-image artifacts. The improvement loop must NEVER re-enable image_pregen_enabled.

---

## F-NO-STILL-PINS (iter6)
**Changed:** `ltx_generate.py` — background_image arg skips `conditions.append`; only used to select LTXConditionPipeline class.
**Why:** Pinning the background plate as a frame condition was forcing LTX into static camera / locked-off look. Removing the condition while keeping the pipeline class keeps motion fluid.

---

## F-SINGLE-SUBJECT (iter6)
**Changed:** Added `"lone subject only, no extras, two people, multiple people, second person, extra person, crowd, background figure, bystander, duplicate character, twin"` to LTX negative prompt.
**Why:** Wider landscape shots caused LTX to hallucinate a second figure in open environments. Negative tokens suppress this.

---

## ltx_inference_steps MUST STAY AT 8
**Changed:** Reverted from 12 → 8 steps.
**Why:** The improvement loop auto-raised steps to 12 in cycle 3; running_shoes score dropped 0.927→0.800. Distilled FP8 model is calibrated for 4–8 steps. More steps do NOT improve quality with this checkpoint; they degrade it.
**Hard rule:** Never raise ltx_inference_steps above 8 for this checkpoint.

---

## F-WIDE-FULLBODY (iter7)
**Changed:** `visual_director.txt` — added FULL BODY (HARD RULE) and wide-shot STRONG BIAS to DIMENSION 4.
**Why:** Running/walking scenes were framed waist-up. Full-body motion is the product/character — cropping it destroys ad value. M12 metric added to enforce this in eval.
**Rule text:** Motion beats (run, walk, kneel, jump, dance, lift, sit, stand, sport) must use "wide shot, full-body, both feet visible, head-to-toe in frame" verbatim.

---

## IDENTITY ECHO (auto-fix, M11)
**Changed:** `visual_director.txt` — added IDENTITY ECHO (HARD) rule: every per-second beat must name the character's face/hair anchor.
**Why:** Without a per-beat text anchor for face geometry, LTX drifts face identity across 6s. Explicit repetition of "the man with dark curly hair" etc. keeps LTX's text-attention consistent.

---

## VERB DIVERSITY (auto-fix, M9)
**Changed:** `visual_director.txt` — added VERB DIVERSITY (HARD) rule when M9 drops below 0.80.
**Why:** Consecutive beats with the same verb root ("continues to walk", "still walking") signal that the scene is not advancing — LTX generates near-identical frames and the video feels static.

---

## CAMERA MOVE PER BEAT (auto-fix, M7)
**Changed:** `visual_director.txt` — added CAMERA MOVE PER BEAT (HARD) rule when M7 drops below 0.60.
**Why:** Static lock-offs across all 6 beats read as stock footage, not advertising. At least one camera move per beat drives perceived motion and cinematic quality.

---

## M12 full_body negative prompt (auto-fix, M12)
**Changed:** `ltx_provider.py` negative prompt — adds "cropped figure, cut-off feet, partial body, waist-up" when M12 drops below 0.65.
**Why:** Complements the visual_director FULL BODY rule at the model level. Text-side negative tokens penalise waist-up framings directly.

---

## F-CANON-PORTRAIT (iter7) — character cohesion across scenes
**Problem:** Character face/clothing visibly changed scene-to-scene. Root cause: scene 1 had no identity anchor (gray placeholder, text only), scenes 2–3 chained from prev-scene last-frame at strength 0.9 (drift compounded), scene ≥3 dropped last-frame entirely (text-only again). Drift was structural.

**Changed:**
- NEW `backend/app/orchestration/stages/canonical_portrait.py` — runs `character_portraits.generate_all` only (no backgrounds, no action stills, no products). Lightweight cousin of `image_pregen.run`.
- `backend/app/orchestration/pipeline.py` — added `run_canonical_portrait` facade method.
- `backend/app/orchestration/tasks/stage_tasks.py:task_pregen_images` — when `image_pregen_enabled=False`, runs `canonical_portrait` instead of full-skip. Project gets exactly one SD3.5 portrait per linked character.
- `backend/app/orchestration/stages/scene_video.py` — removed the `scene.order_index >= 3` last-frame purge. With portrait-anchored chain, drift no longer compounds, so tail scenes can keep continuity.
- `backend/app/providers/video/ltx_provider.py` — re-enabled `--character-image` pass-through (was logging "Skipping portrait" under F-TEXT-ONLY-LTX).
- `ltx_generate.py` — character-image strength 0.90 → 0.50, AND gated on `not _has_last_frame` so portrait only pins when frame 0 is otherwise empty.

**Why each piece:**
- One SD3.5 portrait per project anchors scene 1's frame 0. Scene 1's last-frame inherits portrait identity → scene 2 chains from a portrait-anchored last-frame → identity propagates transitively through all scenes.
- Strength 0.50 (was 0.90) avoids the standing-portrait → seated/running-action morph. The 0.90 value was calibrated for the action-stills era and is wrong without them.
- Gating portrait on `not _has_last_frame` prevents two conditions colliding at frame 0 (portrait + last-frame at the same `frame_index` confuses LTX's mask aggregation).
- Tail-scene last-frame purge was a workaround for drift; with the portrait anchor in place the workaround is harmful (kills continuity).

**Do not revert:**
- Do not push `--character-image` strength back to 0.90 — causes morph in actions like running/kneeling.
- Do not remove the `not _has_last_frame` gate in `ltx_generate.py` — colliding frame-0 conditions degrade output.
- Do not re-add the tail-scene last-frame purge unless the portrait anchor is also removed — they compensate for each other, removing one without the other reverts to drift.
- Do not enable `image_pregen_enabled=True` to "get portraits" — the canonical_portrait lite path already does that without re-introducing action stills.

**Verify next run:** M11 (face consistency) should rise from ~0.5–0.7 → ≥0.85 across all 4 scenes.

---

## F-CANON-PORTRAIT-REVERTED (iter7b) — picture-pin failed, escalate to Phase 2
**What I observed:** Smoke run on `9c1cce53` (running_shoes) post-iter7 reported **horrible visual quality** by user, AND M11 dropped from baseline 0.72 → 0.42. The portrait pin made face consistency *worse*, not better.

**Metric analysis (last 14 eval runs vs smoke):**
- Pre-iter7 baseline (text-only LTX, 13 runs): M11 ≈ 0.72 mean (range 0.67–0.78), auto_total ≈ 0.73.
- Post-iter7 smoke (2 runs same project): M11 = 0.42, auto_total = 0.78. M12 improved 0.00 → 0.50 (the only positive — portrait was full-body, helped framing).

**Diagnosis:** Pinning the SD3.5 portrait at frame 0 (strength 0.5) creates a mid-clip identity morph. LTX rolls out from a non-LTX-native face into its own natural face within ~0.5 s. InsightFace catches the cosine drop within-scene; user sees the morph as "horrible". This is the same failure family as F-NO-STILL-PINS / F-TEXT-ONLY-LTX — frame-condition pictures fight LTX's generative process and degrade quality.

**Reverted:**
- `backend/app/providers/video/ltx_provider.py` — restored "Skipping portrait" log instead of `--character-image` pass-through.
- `backend/app/orchestration/stages/scene_video.py` — restored the `scene.order_index >= 3` last-frame purge (without portrait anchor we need it again to prevent compound drift).

**Also disabled:**
- `canonical_portrait` stage is **NO LONGER RUN** (`stage_tasks.py:task_pregen_images` now full-skips when `image_pregen_enabled=False`). The portrait was being generated at ~30 s/project but no longer consumed by LTX after the revert — pure waste. Re-enable when Phase 2 (face-restoration) ships and actually uses the portrait file. The stage code (`stages/canonical_portrait.py` + `Pipeline.run_canonical_portrait`) stays in place — only the task wiring is paused.

**Hard learning — DO NOT RE-INTRODUCE FRAME-CONDITION PICTURES INTO LTX:**
- Action stills as conditions → stiff poses (F-NO-STILL-PINS).
- Background plates as conditions → static camera lock-off (F-NO-STILL-PINS).
- Character portrait as condition → mid-clip identity morph + M11 regression (F-CANON-PORTRAIT-REVERTED).
- Generalised rule: only `--condition-image` (prev-scene last-frame) is acceptable, and even that gets dropped for tail scenes ≥3 to avoid compound drift.

**Next step (per the plan's escalation rule "Phase 2 only if Phase 1 leaves M11 < 0.85"):** Phase 2 face-restoration post-process — operates AFTER LTX on output frames using the canonical portrait as reference. Doesn't insert pictures into LTX generation, so no morph risk. Cost ~20–30 s/scene. To be implemented next.

---

## F-FAR-CAMERA (iter7c) — every video framed too close to subject
**Problem:** Output videos consistently framed the subject at medium-close-up / talking-head distance even with FULL BODY (HARD RULE) and STRONG BIAS for wide shots already present. Subject filled the frame, environment got squeezed out.

**Three-layer fix:**
1. **Visual director (`visual_director.txt`):** added **CAMERA DISTANCE (HARD RULE — APPLIES TO EVERY SINGLE BEAT)** — mandates camera ≥12 ft (≈4 m) from subject, subject ≤40% of frame height, every per-second beat must include the literal phrase "camera 12 feet from subject, full body in frame, wide shot". Forbids close-up / headshot / bust shot / beauty shot / shoulders-up / dutch close. Allowed only wide / wide-establishing / medium-wide / full-body / environmental long. Single hands-on-product macro insert allowed only when explicitly demanded.
2. **LTX negative prompt (`ltx_provider.py`):** added "close-up, extreme close-up, headshot, bust shot, beauty shot, face filling frame, shoulders-up, dutch close, talking head, macro lens, telephoto compression, narrow depth of field" — penalises tight framings at the model level.
3. **LTX prompt prefix (`ltx_provider.py`):** every prompt now starts with "Wide cinematic shot, camera positioned 12 feet from subject, full body visible head-to-toe, environmental context fills the frame, subject occupies lower-middle third only." — belt-and-suspenders so even if the LLM slips a close-up into a beat, the prefix biases LTX toward wide.

**Why three layers:** the visual_director rule is the strongest signal but the LLM occasionally drops it on emotional beats (tagline, dialogue). The negative prompt and prefix are reinforcements that can't be skipped per beat. Identity preservation in iter7b was achieved with this same belt-and-suspenders pattern (text-side IDENTITY ECHO + last-frame chain).

**Do not revert:**
- Do not delete the CAMERA DISTANCE block in `visual_director.txt`. The LLM tends to drift back to close-ups for dialogue/tagline if not held to it.
- Do not remove `_FAR_CAMERA_PREFIX` from `ltx_provider.py`. It's the model-side anchor.
- Do not allow exceptions for "intimate emotional beats" — the user's complaint was specifically that everything was too close, including those.

**Verify:** in next pipeline run, visually inspect; expect full-body + environment context in every beat; no headshots even on tagline. If still too close, escalate to: (a) raise the distance to 16–20 ft, (b) increase guidance_scale, (c) add explicit "subject in distance" / "long shot" tokens to the prefix.

---

## F-WAN-PHANTOM (iter8) — Phantom-Wan 14B integration log

Adding a second video pipeline (Phantom-Wan 14B, subject-driven) alongside LTX. This section records what's been tried and what's worked so future-me does not repeat dead ends.

### Asset locations
- `~/Phantom/` — upstream repo (cloned from `github.com/Phantom-video/Phantom`)
- `~/Wan2.1-T2V-1.3B/` — base ckpt (T5 + VAE shared with Phantom). 11 GB.
- `~/Phantom-Wan-Models/` — Phantom 14B sharded safetensors (~57 GB) + Phantom 1.3B `.pth` (5.7 GB)
- `wan_generate.py` (repo root) — in-process wrapper

### Things that DON'T work (do not redo)

1. **`hf download` resume after killing the process AND deleting `.lock` files.** Removing the locks tells huggingface_hub the in-progress download is corrupt; it deletes the partials and starts from scratch. **Lesson: never `rm` the `.lock` files.** Kill the process and let it be — re-running `hf download` resumes correctly from the existing `.incomplete` files.

2. **Loading Phantom 14B weights with `torch.load(map_location='cuda:0')` or `safetensors.load_file(device='cuda:0')`.** The 30 GB state dict OOMs the 16 GB GPU at load time. Always load to CPU first, then move to GPU after FP8 cast. Implemented in `wan_generate.py:_load_state_to_cpu`.

3. **Single-GPU FP8 layerwise + DiT-on-GPU at full size.** After cast: ~14 GB on GPU 0. VAE encode of ref image needs ~600 MB, leaves ~150 MB headroom — OOMs on first activation.

4. **Single-GPU FP8 + DiT-kept-on-CPU + upstream `offload_model=True` swapping in/out.** Upstream calls `self.model.to(device)` per step. With VAE still on GPU eating 500 MB, the first DiT linear OOMs at the time_projection layer with `tried to allocate 600 MB, only 168 MB free`.

5. **`accelerate.dispatch_model` + leaving upstream code unchanged.** Phantom's `subject2video.py:291` unconditionally calls `self.model.to(self.device)` at every diffusion step. Accelerate raises `RuntimeError: You can't move a model that has some modules offloaded to cpu or disk.` **Fix:** monkey-patch `obj.model.to = lambda *a, **kw: obj.model` (and `.cpu` similarly) after dispatch.

6. **bf16 dispatch with CPU spillover at frame counts ≥ 33.** Two distinct failure modes both root-caused to the offload path:
   - **OOM:** at 65 frames + `11GiB/9GiB`, GPU 1 runs out of memory inside `rope_apply` (550 MB activation per attention block).
   - **Illegal memory access:** at 33 frames + same budget, sampling fails with `cudaErrorIllegalAddress` inside `accelerate.hooks.pre_forward → send_to_device`. The hook is `torch.compile`-wrapped (visible as `wrapper._compiled_fn` in the stack), and the cross-device tensor staging through that compiled wrapper corrupts CUDA state under activation pressure.
   - **Tried:** loosening to `9GiB/7GiB` to push more layers to CPU (more hook fires → faster failure). Did not help. CUDA_LAUNCH_BLOCKING did not localize the kernel.
   - **Fix:** kill the spillover entirely. Use FP8 layerwise + dispatch (point above) so the model fits on the two GPUs alone.

### Things that WORK
- **FP8 layerwise + multi-GPU dispatch (PRODUCTION RECIPE).** Set `WAN_FP8=1` in env; `wan_generate.py` then applies `apply_layerwise_casting(storage=fp8_e4m3fn, compute=bf16)` BEFORE `dispatch_model`. Result: 14B weights fit in **14 GB total across the two GPUs** (45 modules on GPU, 0 on CPU at default `8GiB`/`6GiB` budgets). With zero CPU spillover, accelerate's offload hooks don't fire — which sidesteps the torch.compile illegal-memory-access bug seen at 33+ frames in the bf16-dispatch path.
  - **Smoke (2026-05-08):** 832×480, 65 frames (4.06 s @ 16 fps), 5 steps → `/tmp/wan_4s_fp8.mp4` (3.2 MB, 17 min wall: 5 min load + 4:41 sampling at 56 s/step + ~7 min CPU VAE decode).
  - GPU memory after dispatch: GPU0 9.5 / 16.6 GB, GPU1 6.6 / 12.5 GB. Plenty of activation headroom.
- **Multi-GPU dispatch at bf16 (LEGACY, ≤17 frames only).** `max_memory={0:"11GiB",1:"9GiB",cpu:"60GiB"}` puts 32 modules on GPU and 13 on CPU. Works for short sequences. **Breaks at ≥33 frames**: accelerate's torch.compile'd offload hooks (`accelerate/hooks.py:50`) hit `cudaErrorIllegalAddress` during cross-device tensor moves. Even with frames small enough to "fit" memory-wise, the compiled offload path is the bug. Fix is to eliminate CPU spillover entirely — see FP8 recipe above.
  - **Smoke result (2026-05-08):** 832×480, 17 frames, 5 sampling steps → mp4 written. ~16 s/step on dispatch, VAE decode on CPU ~3 min for 17 frames. Total ~6 min for a 1 s clip; production 50 steps × 81 frames extrapolates to ~30 min/scene.
  - GPU memory after dispatch: GPU0 12.3 / 16.6 GB, GPU1 9.4 / 12.5 GB.
- **Single-GPU FP8 layerwise** path is implemented (and has its own VAE-CPU-during-sampling patch) but blocked by activation OOM on the 16 GB card. Kept as fallback for the day a 24+ GB GPU shows up.

### Architecture decisions (do not revisit without cause)
- **Subprocess provider, not in-process.** `WanPhantomVideoProvider` calls `wan_generate.py` via `subprocess.create_subprocess_exec` (same pattern as `LTXVideoProvider`). Reason: VRAM needs to be released cleanly between scenes; in-process imports keep `phantom_wan` modules and CUDA contexts resident.
- **No frame-condition pictures into Phantom.** Phantom takes reference images via its `s2v` mode (subject-driven), which injects identity at the model level. The `feedback_no_frame_conditioning_pictures.md` rule still applies — `condition_image_path` (last-frame chain) is IGNORED in `WanPhantomVideoProvider`; identity comes from `--ref-image` only.
- **No FP8 in multi-GPU mode.** Combined 28 GB at bf16 fits across the two cards; FP8 layerwise + dispatch hooks would compound and we hit no clear quality benefit.

### Wiring (shipped iter8)
- `Project.pipeline_profile` column added (migration `e5f8b1c4d2a9_add_pipeline_profile.py`, default `'ltx_text_only'`).
- `GET /api/pipelines` returns `profiles.list_profiles()`.
- `POST /api/projects` and `PUT /api/projects/{id}` accept optional `pipeline_profile` field, validated against `PROFILES`.
- `get_video_provider(profile_name)` routes to LTX or wan_phantom based on the project's profile.
- `task_pregen_images` runs whenever `profile.image_pregen_enabled or profile.canonical_portrait_enabled` (i.e., text-only LTX still skips, Phantom profiles run pregen so character ref images exist).
- `scene_video.generate_single` reads `project.pipeline_profile`, gates `pin_last_frame_chain`, `drop_last_frame_on_tail`, and `pin_action_stills` on the profile fields.
- `AssetOrchestrator.__init__` now accepts `provider_settings: dict`; `_video_settings()` reads `width/height/num_frames/fps/steps/guidance_text` from it before falling back to `settings.ltx_*`. Wired in `scene_video.py` from `profile.provider_settings`. Without this the Wan provider was silently getting LTX defaults (768×448 / 41 frames / 8 steps) instead of its profile values (832×480 / 81 frames / 50→30 steps).
- `wan_phantom_provider.py` exports `WAN_FP8=1` and `CUDA_VISIBLE_DEVICES=0,1` to its subprocess env — Phantom now defaults to the production FP8+dispatch recipe across both GPUs.
- `wan_generate.py` keeps VAE on GPU when `WAN_FP8=1` (saves ~7-9 min CPU decode per scene). Only forces VAE→CPU in the bf16-dispatch fallback (when both GPUs are packed with bf16 weights and there's no GPU room).
- `image_pregen_agent.py` now reads `profile.image_pregen_enabled and profile.pin_action_stills` to decide whether to run the action-stills phase. The `wan_phantom_text` profile sets both to False — so its pregen now does ONLY the canonical character portrait (~30 s) instead of 6+ InstantID action-still calls (which were getting silently dropped before reaching the provider, AND occasionally hung the worker when the InstantID daemon crashed).
- Wan profile `steps` reduced from 50 → 30 (Phantom holds quality at 30; saves ~12 min sampling per scene).

### TODO (next session)
- FE dropdown that calls `GET /api/pipelines` and posts `pipeline_profile` on project create.
- Tune `max_memory` once a real production-length smoke succeeds: push more layers onto GPU 0/1 if there's headroom — current 11/9 GiB was set for activation budget on the 5-step diag, may be tunable.
- Eval: run an A/B between `ltx_text_only` and `wan_phantom_text` on the same story, compare M11 (face cohesion) and visual quality.
