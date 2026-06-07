#!/usr/bin/env bash
# download_civitai_loras.sh — fetch the 4 new TI2V-5B LoRAs from CivitAI.
#
# CivitAI requires a personal API token (free, https://civitai.com/user/account).
# Run:
#   CIVITAI_TOKEN=<your_token> ./scripts/download_civitai_loras.sh
#
# Each LoRA is ~150-300MB. The catalog (backend/app/config/wan22_lora_catalog.yaml)
# expects them at $LORA_DIR with the exact filenames below — don't rename.

set -euo pipefail

if [ -z "${CIVITAI_TOKEN:-}" ]; then
  echo "ERROR: CIVITAI_TOKEN env var is required."
  echo "  Get one at https://civitai.com/user/account → API Keys."
  echo "  Then:  CIVITAI_TOKEN=xxx ./scripts/download_civitai_loras.sh"
  exit 1
fi

LORA_DIR="${LORA_DIR:-${MODELS_ROOT:-$HOME/models}/wan22/loras/5b}"
mkdir -p "$LORA_DIR"

# Each line: version_id  expected_filename  display_name
LORAS=$(cat <<'EOF'
2076237 wan_flat_color_2.2.5b_v2.safetensors Flat-Color-Anime
2175490 Wan_2.2_5B_Realistic_Fire.safetensors Realistic-Fire
2116232 Aether_Blast-LoRA-Wan22_5b-v1.safetensors Aether-Blast
2161146 Wan22_5B_Zoom_Art.safetensors Zoom-Art
EOF
)

while IFS=$' \t' read -r vid fname label; do
  out="$LORA_DIR/$fname"
  if [ -f "$out" ]; then
    sz=$(stat -c%s "$out")
    if [ "$sz" -gt 10000000 ]; then
      echo "✓ $label (already present, $(numfmt --to=iec $sz))"
      continue
    fi
    echo "? $label (existing file <10MB — re-downloading)"
  fi
  echo "↓ $label (v$vid)"
  curl -sSL --fail \
    -H "Authorization: Bearer $CIVITAI_TOKEN" \
    -o "$out" \
    "https://civitai.com/api/download/models/$vid"
  sz=$(stat -c%s "$out")
  echo "  → $(numfmt --to=iec $sz)  $fname"
done <<< "$LORAS"

echo
echo "All done. Restart celery workers so the catalog reload picks up the new LoRAs:"
echo "  ./scripts/start_all.sh stop && ./scripts/start_all.sh"
