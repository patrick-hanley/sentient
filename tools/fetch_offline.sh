#!/usr/bin/env bash
# Downloads everything the brain needs so nothing is fetched on venue Wi-Fi.
# Each artifact lands in its own folder under offline/. Safe to re-run (curl -C -).
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OFF="$ROOT/offline"
mkdir -p "$OFF"
get() {  # get <dir> <url> [outname]
  local d="$OFF/$1" url="$2" out="${3:-$(basename "${2%%\?*}")}"
  mkdir -p "$d"
  if curl -fL --retry 3 -C - -o "$d/$out" "$url"; then echo "OK   $1/$out"; else echo "FAIL $1/$out ($url)"; fi
}

echo "== GGUF (Mac fallback brain) — background =="
(
  get gguf https://huggingface.co/ggml-org/gemma-4-E2B-it-GGUF/resolve/main/gemma-4-E2B-it-Q4_0.gguf
  get gguf https://huggingface.co/ggml-org/gemma-4-E2B-it-GGUF/resolve/main/mmproj-gemma-4-E2B-it-Q8_0.gguf
) > "$OFF/gguf.log" 2>&1 &
GGUF_PID=$!

echo "== Vision models =="
get vision https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx
get vision https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx
get vision https://storage.googleapis.com/mediapipe-models/object_detector/efficientdet_lite0/float32/latest/efficientdet_lite0.tflite
get vision https://storage.googleapis.com/mediapipe-models/image_embedder/mobilenet_v3_small/float32/latest/mobilenet_v3_small.tflite

echo "== Piper voices =="
PV=https://huggingface.co/rhasspy/piper-voices/resolve/main/en
for v in en_US/amy/medium/en_US-amy-medium en_GB/alba/medium/en_GB-alba-medium \
         en_US/ryan/medium/en_US-ryan-medium en_US/libritts_r/medium/en_US-libritts_r-medium; do
  get piper "$PV/$v.onnx"; get piper "$PV/$v.onnx.json"
done

echo "== Whisper base.en (Mac fallback STT) =="
get whisper https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.en.bin

echo "== aarch64 wheelhouses (Pi 5 = py3.13, Jetson = py3.10) =="
PLAT=""
for p in manylinux2014_aarch64 manylinux_2_17_aarch64 manylinux_2_27_aarch64 manylinux_2_28_aarch64 \
         manylinux_2_31_aarch64 manylinux_2_34_aarch64 manylinux_2_35_aarch64; do PLAT="$PLAT --platform $p"; done
for pv in 3.13 3.10; do
  W="$OFF/wheels-py${pv/./}-aarch64"; mkdir -p "$W"
  for pkgs in "litert-lm-api numpy opencv-python-headless webrtcvad-wheels piper-tts" "litert-lm" "mediapipe"; do
    python3 -m pip download -q --only-binary=:all: --implementation cp --python-version "$pv" $PLAT -d "$W" $pkgs \
      && echo "OK   py$pv: $pkgs" || echo "FAIL py$pv: $pkgs"
  done
done

echo "== Mac venv ($ROOT/.venv) =="
[ -d "$ROOT/.venv" ] || python3 -m venv "$ROOT/.venv"
"$ROOT/.venv/bin/pip" install -q --upgrade pip
for p in esptool pyserial numpy opencv-python-headless webrtcvad-wheels piper-tts; do
  "$ROOT/.venv/bin/pip" install -q "$p" && echo "OK   mac: $p" || echo "FAIL mac: $p"
done

echo "== brew llama.cpp + whisper-cpp =="
brew install llama.cpp whisper-cpp >/dev/null 2>&1 && echo "OK   brew" || echo "FAIL brew"

wait $GGUF_PID; cat "$OFF/gguf.log" | grep -E "^(OK|FAIL)"
echo "== DONE =="; du -sh "$OFF"/*
