#!/usr/bin/env bash
# Gemma Hackathon weekend setup — run on Patrick's MacBook Pro
# Sets up: LiteRT-LM venv, Gemma 4 E2B model, Raspberry Pi OS Lite image, esptool
# Safe to re-run: downloads resume, existing files are verified, not re-fetched.
set -uo pipefail

MODEL_URL="https://huggingface.co/litert-community/gemma-4-E2B-it-litert-lm/resolve/main/gemma-4-E2B-it.litertlm"
MODEL_BYTES=2588147712
MODEL_DIR="$HOME/.litert-lm/models/gemma4-e2b"
MODEL_FILE="$MODEL_DIR/model.litertlm"
PI_DIR_URL="https://downloads.raspberrypi.com/raspios_lite_arm64/images/raspios_lite_arm64-2026-10-06"
PI_FILE="2026-10-06-raspios-trixie-arm64-lite.img.xz"
PI_PATH="$HOME/Downloads/$PI_FILE"
VENV="$HOME/.litert-env"

echo "== 1/5  Python check =="
PY=""
for c in python3.12 python3.11 python3.10 python3; do
  if command -v "$c" >/dev/null 2>&1; then
    v=$("$c" -c 'import sys; print(sys.version_info >= (3,10))')
    if [ "$v" = "True" ]; then PY="$c"; break; fi
  fi
done
if [ -z "$PY" ]; then
  echo "ERROR: need Python 3.10+. Install from https://www.python.org/downloads/ or 'brew install python@3.12', then re-run."
  exit 1
fi
echo "Using $PY ($($PY --version))"

echo "== 2/5  LiteRT-LM environment =="
[ -d "$VENV" ] || "$PY" -m venv "$VENV"
# shellcheck disable=SC1091
source "$VENV/bin/activate"
pip install -q --upgrade pip
pip install -q litert-lm esptool
echo "litert-lm: $(command -v litert-lm || echo MISSING)"
echo "esptool:   $(command -v esptool.py || command -v esptool || echo MISSING)"

echo "== 3/5  Gemma 4 E2B model (~2.6 GB, resumable) =="
mkdir -p "$MODEL_DIR"
if [ -f "$MODEL_FILE" ] && [ "$(stat -f%z "$MODEL_FILE" 2>/dev/null || stat -c%s "$MODEL_FILE")" = "$MODEL_BYTES" ]; then
  echo "Already downloaded and size-verified: $MODEL_FILE"
else
  curl -L -C - -o "$MODEL_FILE" "$MODEL_URL"
  sz=$(stat -f%z "$MODEL_FILE" 2>/dev/null || stat -c%s "$MODEL_FILE")
  if [ "$sz" = "$MODEL_BYTES" ]; then
    echo "Model OK ($sz bytes)"
  else
    echo "WARNING: model size is $sz, expected $MODEL_BYTES — re-run the script to resume."
  fi
fi

echo "== 4/5  Raspberry Pi OS Lite 64-bit image =="
if [ -f "$PI_PATH" ]; then
  echo "Image already present: $PI_PATH (verifying checksum)"
else
  curl -L -C - -o "$PI_PATH" "$PI_DIR_URL/$PI_FILE"
fi
curl -s -o "$HOME/Downloads/$PI_FILE.sha256" "$PI_DIR_URL/$PI_FILE.sha256"
(cd "$HOME/Downloads" && shasum -a 256 -c "$PI_FILE.sha256" 2>/dev/null) \
  && echo "Pi image checksum OK" \
  || echo "NOTE: checksum file format differs — verify manually before flashing."

echo "== 5/5  Done =="
echo "Model:  $MODEL_FILE"
echo "Image:  $PI_PATH"
echo "Venv:   $VENV  (activate with: source $VENV/bin/activate)"
echo ""
echo "Smoke test the model (interactive, first run has a short warmup):"
echo "  source $VENV/bin/activate"
echo "  litert-lm run --model-path $MODEL_FILE"
echo ""
echo "Flash the Pi when it arrives: Raspberry Pi Imager -> Use custom -> pick the .img.xz in Downloads."
echo "Pi-side install (after first boot) is a separate step: pip install litert-cli, then copy the model over."
