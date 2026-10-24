#!/usr/bin/env bash
# Copy everything the venue needs to a USB drive:  bash tools/copy_to_usb.sh /Volumes/<DRIVE>
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DST="${1:?usage: copy_to_usb.sh /Volumes/DRIVE}/sentient"
mkdir -p "$DST/offline/model"
rsync -a --exclude .venv --exclude .venv-brain --exclude 'firmware/*/build' \
  --exclude 'brain/data/enroll.npz' --exclude '__pycache__' "$ROOT/" "$DST/"
cp -n "$HOME/.litert-lm/models/gemma4-e2b/model.litertlm" "$DST/offline/model/" || true
echo "model on USB: $(stat -f%z "$DST/offline/model/model.litertlm") bytes (want 2588147712)"
du -sh "$DST"
