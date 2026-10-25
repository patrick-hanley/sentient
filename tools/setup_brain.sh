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
# mediapipe drags in opencv-contrib-python (needs libGL, absent on Pi OS Lite) over the headless build:
# put headless back — aruco, YuNet and SFace are all in it.
$PIP uninstall -q -y opencv-contrib-python opencv-python 2>/dev/null
$PIP install -q ${EXTRA:-} --no-index -f "$WH" --no-deps --force-reinstall opencv-python-headless && echo "OK   opencv headless restored"

echo "== Model"
M="$HOME/.litert-lm/models/gemma4-e2b/model.litertlm"
mkdir -p "$(dirname "$M")"
if [ "$(stat -c%s "$M" 2>/dev/null)" != "2588147712" ]; then
  SRC="$ROOT/offline/model/model.litertlm"
  [ -f "$SRC" ] && cp "$SRC" "$M" || echo "Model not found — copy it to $M (scp from Mac, USB, or venue drive)"
fi
echo "model size: $(stat -c%s "$M" 2>/dev/null) (want 2588147712)"

echo "== Hotspot (2.4 GHz) for the Atoms"
# Pass your own password: HOTSPOT_PASS=... bash tools/setup_brain.sh  (it must match the Atoms' secrets.h).
# SKIP_HOTSPOT=1 leaves Wi-Fi alone (e.g. when the Mac hosts the hotspot).
if [ -n "${SKIP_HOTSPOT:-}" ]; then echo "skipped (SKIP_HOTSPOT set)"
elif command -v nmcli >/dev/null; then
  command -v raspi-config >/dev/null && sudo raspi-config nonint do_wifi_country US   # Pi OS keeps Wi-Fi off until a country is set
  sudo rfkill unblock wifi 2>/dev/null
  sudo nmcli dev wifi hotspot con-name sentient-hotspot ssid sentient-brain password "${HOTSPOT_PASS:-sentient123}" band bg \
    && sudo nmcli con modify sentient-hotspot connection.autoconnect yes connection.autoconnect-priority 100 \
    && nmcli -g IP4.ADDRESS dev show "$(nmcli -t -f DEVICE,TYPE dev | awk -F: '$2=="wifi"{print $1; exit}')"
else echo "nmcli missing — use the phone hotspot instead"; fi

if [ -n "${INSTALL_SERVICE:-}" ]; then
  echo "== Start the brain at boot (systemd: sentient-brain)"
  sudo tee /etc/systemd/system/sentient-brain.service >/dev/null <<UNIT
[Unit]
Description=Sentient toys brain
After=network-online.target
Wants=network-online.target

[Service]
User=$USER
WorkingDirectory=$ROOT
ExecStart=$PY -m brain.main ${BRAIN_ARGS:---cpu}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT
  sudo systemctl daemon-reload && sudo systemctl enable sentient-brain && echo "enabled; logs: journalctl -u sentient-brain -f"
fi

echo "== Next:"
echo "  cd $ROOT && $PY -m brain.main --selftest   (add --cpu on a Pi 5)"
echo "  cd $ROOT && $PY -m brain.main               (dashboard on :8080)"
