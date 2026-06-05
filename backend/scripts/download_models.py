#!/usr/bin/env python
"""Download the model weights OpenFlow's GPU providers need.

Idempotent: re-running skips already-downloaded files. Weights land under
MODELS_ROOT (default <repo>/models), matching the defaults in app.config.

Usage:
    python backend/scripts/download_models.py --all
    python backend/scripts/download_models.py --ltx --sd35
    MODELS_ROOT=/data/models python backend/scripts/download_models.py --wan22

Gated repos (e.g. Stable Diffusion 3.5) require `huggingface-cli login` or
HF_TOKEN in the environment. See docs/MODELS_AND_WEIGHTS.md.
"""

import argparse
import os
import sys
from pathlib import Path

# repo_id -> destination subdir under MODELS_ROOT
MODELS = {
    "ltx": ("Lightricks/LTX-Video", "ltx/LTX-Video"),
    "wan22": ("Wan-AI/Wan2.2-TI2V-5B-Diffusers", "wan22/TI2V-5B-Diffusers"),
    "sd35": ("stabilityai/stable-diffusion-3.5-medium", "sd35/stable-diffusion-3.5-medium"),
}
GATED = {"sd35"}


def models_root() -> Path:
    repo_root = Path(__file__).resolve().parents[2]
    return Path(os.getenv("MODELS_ROOT", str(repo_root / "models")))


def download_one(key: str, root: Path) -> None:
    from huggingface_hub import snapshot_download

    repo_id, subdir = MODELS[key]
    dest = root / subdir
    token = os.getenv("HF_TOKEN") or None
    print(f"↓ {key}: {repo_id} -> {dest}")
    if key in GATED and not token:
        print(f"  ⚠ {repo_id} is gated; run `huggingface-cli login` or set HF_TOKEN first.")
    snapshot_download(repo_id=repo_id, local_dir=str(dest), token=token, resume_download=True)
    print(f"  ✓ {key} ready")


def main() -> int:
    ap = argparse.ArgumentParser(description="Download OpenFlow model weights.")
    for key in MODELS:
        ap.add_argument(f"--{key}", action="store_true", help=f"download {key}")
    ap.add_argument("--all", action="store_true", help="download everything")
    args = ap.parse_args()

    selected = [k for k in MODELS if getattr(args, k)] or (list(MODELS) if args.all else [])
    if not selected:
        ap.print_help()
        return 1

    root = models_root()
    root.mkdir(parents=True, exist_ok=True)
    print(f"MODELS_ROOT = {root}\n")
    for key in selected:
        download_one(key, root)
    print("\nDone. GFPGAN/CodeFormer weights are fetched on first use by those libs.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
