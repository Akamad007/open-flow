#!/bin/bash
# v2: 40 images instead of 20, rank 32 instead of 16, 1500 steps instead of 800.
# Outputs to lora_runner_man_v2/ — leaves v1 intact for comparison.
set -euo pipefail

cd "$(dirname "$0")"

PY=/home/akash/.pyenv/versions/video-app/bin/python
INSTANCE_DIR="$PWD/dataset_runner_man"
OUTPUT_DIR="$PWD/lora_runner_man_v2"
INSTANCE_PROMPT="ohwx man, full-body photo, athletic young man with short dark brown hair wearing a charcoal grey performance tee, dark technical shorts, and white athletic trainers"

if [ ! -d "$INSTANCE_DIR" ]; then
  echo "ERROR: instance dir missing — run build_dataset.py first"
  exit 1
fi

N_PNG=$(find "$INSTANCE_DIR" -maxdepth 1 -name "*.png" | wc -l)
echo "Training on $N_PNG raw images at $INSTANCE_DIR (will filter pose_skel sidecars next)"

export PYTORCH_CUDA_ALLOC_CONF="expandable_segments:True"

HOLD="$PWD/_train_hold_v2"
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
  --lr_warmup_steps=100 \
  --max_train_steps=1500 \
  --rank=32 \
  --mixed_precision="fp16" \
  --seed=42

echo "LoRA v2 training complete → $OUTPUT_DIR"
ls -la "$OUTPUT_DIR" | head -10
