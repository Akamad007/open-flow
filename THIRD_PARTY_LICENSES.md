# Third-Party Licenses & Model Usage

OpenFlow's own code is MIT ([LICENSE](LICENSE)). It also **drives** third-party
models and libraries that are **not** covered by that MIT grant and are **not**
redistributed in this repo — you download them yourself. Each carries its own
license and restrictions. **Review these before any commercial use.**

## AI models

| Model | Used for | License | Key restrictions |
|---|---|---|---|
| **Stable Diffusion 3.5 Medium** | image / identity stills | Stability AI Community License | Free for research & for orgs under a revenue threshold; **commercial use above it requires a paid Stability license**. Gated on Hugging Face. |
| **LTX-Video** (Lightricks) | video generation | See model card (OpenRAIL-style) | Use-based restrictions; no illegal/harmful content. |
| **Wan 2.2 TI2V-5B** (Wan-AI) | video generation | Apache-2.0 (verify on model card) | Generally permissive; verify current terms. |
| **FrameINO / MotionINO** | motion-scene fine-tune | Per upstream | Verify before use. |
| **InstantID** | face-identity synthesis | Apache-2.0 (models) + see upstream | **Identity/likeness synthesis — consent required.** See [ETHICAL_USE.md](ETHICAL_USE.md). |
| **ControlNet (OpenPose)** | pose control | Per upstream | — |
| **Chatterbox** | text-to-speech | Per upstream | Voice cloning — use consented reference audio only. |
| **GFPGAN / CodeFormer** | face restoration | Apache-2.0 / S-Lab License (non-commercial clauses — check) | CodeFormer's S-Lab license restricts commercial use. |
| Civitai LoRAs (optional) | style adapters | Per-LoRA on Civitai | Each LoRA has its own terms; check each. |

## Python / JS dependencies

Backend dependencies are listed in `backend/requirements*.txt` and frontend
dependencies in `frontend/package.json`. They are predominantly MIT / BSD /
Apache-2.0. Generate a full bill of materials with:

```bash
pip install pip-licenses && pip-licenses --format=markdown
cd frontend && npx license-checker --summary
```

## Notes

- OpenFlow does **not** vendor model weights; `download_models.py` fetches them
  from their official sources under their own licenses.
- `CodeFormer/` and `gfpgan/` directories are vendored upstream code, gitignored,
  and retain their original licenses.
- This table is informational, not legal advice. When in doubt, consult the
  upstream model card and a lawyer for commercial deployments.
