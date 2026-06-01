#!/bin/bash
# Train an SDXL DreamBooth-LoRA on the dataset built by build_dataset.py.
#
# 16-GB-VRAM-safe settings:
#   - mixed_precision fp16
#   - rank 16  (good identity capture without overfitting)
#   - batch_size 1
#   - gradient_checkpointing
#   - 8-bit Adam (bitsandbytes)
#   - 800 steps  (~15-25 min on a 5070 Ti)
set -euo pipefail

cd "$(dirname "$0")"

PY=/home/akash/.pyenv/versions/video-app/bin/python
INSTANCE_DIR="$PWD/dataset_runner_man"
OUTPUT_DIR="$PWD/lora_runner_man"
INSTANCE_PROMPT="ohwx man, full-body photo, athletic young man with short dark brown hair wearing a charcoal grey performance tee, dark technical shorts, and white athletic trainers"

if [ ! -d "$INSTANCE_DIR" ]; then
  echo "ERROR: instance dir missing — run build_dataset.py first"
  exit 1
fi

# Count pngs (excluding the _pose_refs subdir)
N_PNG=$(find "$INSTANCE_DIR" -maxdepth 1 -name "*.png" | wc -l)
if [ "$N_PNG" -lt 5 ]; then
  echo "ERROR: only $N_PNG training images — need at least 5"
  exit 1
fi
echo "Training on $N_PNG images at $INSTANCE_DIR"

export PYTORCH_CUDA_ALLOC_CONF="expandable_segments:True"

# Move every non-instance file (captions, pose-skel sidecars, pose_refs
# subdir) OUT of the dataset dir for the duration of training — the
# trainer iterates every file in `--instance_data_dir` and tries to
# Image.open() each one, which crashes on .txt files and produces bad
# training images from the skeleton sidecars.
HOLD="$PWD/_train_hold"
rm -rf "$HOLD"
mkdir -p "$HOLD"
shopt -s nullglob
for f in "$INSTANCE_DIR"/*_pose_skel.png "$INSTANCE_DIR"/*.txt; do
  mv "$f" "$HOLD/"
done
shopt -u nullglob
[ -d "$INSTANCE_DIR/_pose_refs" ] && mv "$INSTANCE_DIR/_pose_refs" "$HOLD/_pose_refs"

cleanup() {
  shopt -s nullglob
  for f in "$HOLD"/*_pose_skel.png "$HOLD"/*.txt; do
    mv "$f" "$INSTANCE_DIR/"
  done
  shopt -u nullglob
  [ -d "$HOLD/_pose_refs" ] && mv "$HOLD/_pose_refs" "$INSTANCE_DIR/_pose_refs"
  rmdir "$HOLD" 2>/dev/null || true
}
trap cleanup EXIT

N_TRAIN=$(find "$INSTANCE_DIR" -maxdepth 1 -name "*.png" | wc -l)
echo "After cleanup: $N_TRAIN training images"

"$PY" -u train_dreambooth_lora_sdxl.py \
  --pretrained_model_name_or_path="stabilityai/stable-diffusion-xl-base-1.0" \
  --pretrained_vae_model_name_or_path="madebyollin/sdxl-vae-fp16-fix" \
  --instance_data_dir="$INSTANCE_DIR" \
  --output_dir="$OUTPUT_DIR" \
  --instance_prompt="$INSTANCE_PROMPT" \
  --resolution=1024 \
  --train_batch_size=1 \
  --gradient_accumulation_steps=2 \
  --gradient_checkpointing \
  --use_8bit_adam \
  --learning_rate=1e-4 \
  --lr_scheduler="cosine" \
  --lr_warmup_steps=50 \
  --max_train_steps=800 \
  --rank=16 \
  --mixed_precision="fp16" \
  --seed=42 \
  --enable_xformers_memory_efficient_attention 2>/dev/null \
  || \
"$PY" -u train_dreambooth_lora_sdxl.py \
  --pretrained_model_name_or_path="stabilityai/stable-diffusion-xl-base-1.0" \
  --pretrained_vae_model_name_or_path="madebyollin/sdxl-vae-fp16-fix" \
  --instance_data_dir="$INSTANCE_DIR" \
  --output_dir="$OUTPUT_DIR" \
  --instance_prompt="$INSTANCE_PROMPT" \
  --resolution=1024 \
  --train_batch_size=1 \
  --gradient_accumulation_steps=2 \
  --gradient_checkpointing \
  --use_8bit_adam \
  --learning_rate=1e-4 \
  --lr_scheduler="cosine" \
  --lr_warmup_steps=50 \
  --max_train_steps=800 \
  --rank=16 \
  --mixed_precision="fp16" \
  --seed=42

echo "LoRA training complete → $OUTPUT_DIR"
ls -la "$OUTPUT_DIR" | head -10
