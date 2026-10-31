# Jetson Orin Nano Super as the brain (set up Oct 30 2026)

JetPack 6.2 (L4T R36.4.3) booted from a 128 GB SD card (`jp62-orin-nano-sd-card-image.zip` from NVIDIA, written with `dd`), set up
headless over the USB-C serial console (`screen /dev/cu.usbmodem… 115200`) because there was no HDMI. A 1 TB NVMe is `/data`.

| Item | Value |
|---|---|
| Host | `sentient@sentient-jetson.local` (key auth, passwordless sudo), 192.168.2.6 on the Mac's shared ethernet |
| Power | `jetson-perf.service`: `nvpmodel -m 2` (MAXN_SUPER) + `jetson_clocks` at boot |
| Storage | NVMe ext4 at `/data` (fstab, `nofail`): repo `/data/sentient`, model `/data/models/model.litertlm`, llama.cpp CUDA build `/data/build`, Kitten venv `/data/bench-k312` |
| Services | `sentient-brain` (`--backend litert`, GPU, `SENTIENT_VISION=never`), `sentient-kitten` (port 8099), `jetson-perf` |
| Toys' network | NetworkManager hotspot `sentient-hotspot` on `wlP1p1s0` (SSID `sentient-brain`, 2.4 GHz ch 6, 10.42.0.1); the password is the private one in `firmware/toy-client/secrets.h`, not the public default |
| Toy names | `brain/data/toys.json` maps MAC → name; it is NOT auto-correct on a new brain (arrival order), so copy it from the old brain |

Install steps used: `bash tools/setup_brain.sh` (SKIP_HOTSPOT=1), then `pip install numpy opencv-python-headless webrtcvad-wheels piper-tts cryptography`
from PyPI (not in the wheelhouse), `uv venv --python 3.12 /data/bench-k312` + the KittenTTS wheel, the Gemma model from
`litert-community/gemma-4-E2B-it-litert-lm` on Hugging Face, and a CUDA llama.cpp build (`-DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=87`).

## Measured (same prompts, brain system prompt; `tools/llm_bench.py`)

| | first token | first line | whole reply |
|---|---|---|---|
| Jetson LiteRT CPU | 1.14 s | 2.5 s | 5.8 s |
| **Jetson LiteRT GPU** | **0.24 s** | **0.84 s** | **2.3 s** |
| llama.cpp CUDA (llama-bench, Q4_0) | pp256 1291 tok/s | | tg 30 tok/s |

Live event turns (toy-side timestamps): first audible sample **1.06–1.09 s** after the turn starts, vs about 4 s on the Pi 5.
A real spoken-question turn was not yet measured (adds the ~0.6 s end-of-speech wait and Gemma hearing the audio).

## To do
Motion-sensor calibration and the Parent Board PIN/data live on the old brain and are not carried over; real-speech latency test;
Pi's `brain/data` (voice settings, enrolled faces) is not copied; try vision on the GPU.
