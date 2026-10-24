#!/usr/bin/env bash
# Run ON the Pi 5 / Jetson from the copied sentient/ folder:  bash tools/setup_brain.sh
# Offline: installs from offline/wheels-py3XX-aarch64, places the model, starts the hotspot.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYV=$(python3 -c 'import sys;print(f"{sys.version_info[0]}{sys.version_info[1]}")')
WH="$ROOT/offline/wheels-py${PYV}-aarch64"
echo "== Python 3.${PYV#3} / wheelhouse $WH"
[ -d "$WH" ] || { echo "No wheelhouse for py$PYV (have: $(ls -d "$ROOT"/offline/wheels-*))"; exit 1; }

VENV="$ROOT/.venv-brain"
if python3 -m venv "$VENV" 2>/dev/null; then PIP="$VENV/bin/pip"; PY="$VENV/bin/python"
else echo "venv unavailable (apt install python3-venv) — falling back to pip --user"; PIP="python3 -m pip"; PY=python3; EXTRA="--user"; fi
for pkgs in "numpy opencv-python-headless webrtcvad-wheels piper-tts" "litert-lm-api" "litert-lm" "mediapipe"; do
  $PIP install -q ${EXTRA:-} --no-index -f "$WH" $pkgs && echo "OK   $pkgs" || echo "FAIL $pkgs"
done

echo "== Model"
M="$HOME/.litert-lm/models/gemma4-e2b/model.litertlm"
mkdir -p "$(dirname "$M")"
if [ "$(stat -c%s "$M" 2>/dev/null)" != "2588147712" ]; then
  SRC="$ROOT/offline/model/model.litertlm"
  [ -f "$SRC" ] && cp "$SRC" "$M" || echo "Model not found — copy it to $M (scp from Mac, USB, or venue drive)"
fi
echo "model size: $(stat -c%s "$M" 2>/dev/null) (want 2588147712)"

echo "== Hotspot (2.4 GHz) for the Atoms"
if command -v nmcli >/dev/null; then
  sudo nmcli dev wifi hotspot ssid sentient-brain password sentient123 band bg \
    && nmcli -g IP4.ADDRESS dev show "$(nmcli -t -f DEVICE,TYPE dev | awk -F: '$2=="wifi"{print $1; exit}')"
else echo "nmcli missing — use the phone hotspot instead"; fi

echo "== Next:"
echo "  cd $ROOT && $PY -m brain.main --selftest   (add --cpu on a Pi 5)"
echo "  cd $ROOT && $PY -m brain.main               (dashboard on :8080)"
