#!/usr/bin/env bash
# Run with: bash scripts/test.sh
# Make sure the video-app pyenv virtualenv is active first:
#   pyenv activate video-app
set -euo pipefail

TORCH_CUDA_INDEX_URL="https://download.pytorch.org/whl/cu124"

# -----------------------------
# Upgrade pip
# -----------------------------
python -m pip install --upgrade pip setuptools wheel

# -----------------------------
# PyTorch with CUDA 12.4
# -----------------------------
pip install --index-url "$TORCH_CUDA_INDEX_URL" \
  torch==2.6.0+cu124 torchvision==0.21.0+cu124 torchaudio==2.6.0+cu124

# -----------------------------
# Core packages for LTX-Video via Diffusers
# -----------------------------
pip install \
  diffusers \
  transformers \
  accelerate \
  safetensors \
  sentencepiece \
  protobuf \
  huggingface_hub \
  imageio \
  imageio-ffmpeg \
  opencv-python \
  einops

# -----------------------------
# Optional but useful
# -----------------------------
pip install \
  xformers==0.0.29.post3 \
  bitsandbytes

# -----------------------------
# Smoke test
# -----------------------------
python - <<'PY'
import torch
print("torch:", torch.__version__)
print("cuda available:", torch.cuda.is_available())
if torch.cuda.is_available():
    print("gpu:", torch.cuda.get_device_name(0))
PY

echo
echo "Done. Run the generator with:"
echo "  python ltx_generate.py --prompt \"your prompt\" --output output.mp4"