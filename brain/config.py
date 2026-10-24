"""All tunables in one place. Edit freely at the venue."""
from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OFFLINE = Path(os.environ.get("SENTIENT_OFFLINE", ROOT / "offline"))
DATA = Path(__file__).resolve().parent / "data"
DATA.mkdir(exist_ok=True)

MODEL_LITERT = Path(os.environ.get("SENTIENT_MODEL", Path.home() / ".litert-lm/models/gemma4-e2b/model.litertlm"))
MODEL_GGUF = OFFLINE / "gguf/gemma-4-E2B-it-Q4_0.gguf"
MMPROJ_GGUF = OFFLINE / "gguf/mmproj-gemma-4-E2B-it-Q8_0.gguf"
WHISPER_MODEL = OFFLINE / "whisper/ggml-base.en.bin"
LLAMA_URL = "http://127.0.0.1:8081"

YUNET = OFFLINE / "vision/face_detection_yunet_2023mar.onnx"
SFACE = OFFLINE / "vision/face_recognition_sface_2021dec.onnx"
OBJ_DET = OFFLINE / "vision/efficientdet_lite0.tflite"
EMBEDDER = OFFLINE / "vision/mobilenet_v3_small.tflite"
ENROLL_DB = DATA / "enroll.npz"

# ---- network ----
BRAIN_PORT = 5005      # Atoms -> brain (HELLO, mic, BTN)
ATOM_PORT = 5006       # brain -> Atoms (ACK)
DASH_PORT = 8080
SAMPLE_RATE = 16000
# Speech sent to the Atoms: "ulaw" = 8-bit G.711 (half the bytes of "pcm"). PLAY_RATE 8000 halves it again
# (telephone quality; fine on the tiny speaker if the network is very slow).
PLAY_CODEC = "ulaw"
PLAY_RATE = 16000            # 16000 on a local AP (Mac hotspot / Pi / Jetson); 8000 on a phone hotspot (~250 ms RTT)

# ---- toys ----
# aruco = tag id on the toy's chest (tools/make_aruco_sheet.py).
# pitch > 1 raises the voice (resample trick), length < 1 speaks faster.
TOYS = {
    "pip": dict(name="Pip", aruco=1, voice="en_GB-alba-medium", speaker=None, length=0.9, pitch=1.25,
                persona="curious and bouncy; asks the child short questions; easily amazed"),
    "sage": dict(name="Sage", aruco=2, voice="en_GB-alba-medium", speaker=None, length=1.08, pitch=1.0,
                 persona="calm and careful; explains things simply; the reader who can look at books and pictures"),
    "noodle": dict(name="Noodle", aruco=3, voice="en_US-libritts_r-medium", speaker=20, length=0.95, pitch=1.25,
                   persona="silly and giggly; is confidently WRONG about easy things so the child gets to correct her, "
                           "then happily thanks them"),
}
TOY_ORDER = ["pip", "sage", "noodle"]
MAC_MAP_FILE = DATA / "toys.json"   # {"AA:BB:..": "pip"} — auto-filled in arrival order, edit to reassign


def load_mac_map() -> dict[str, str]:
    try:
        return json.loads(MAC_MAP_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_mac_map(m: dict[str, str]) -> None:
    MAC_MAP_FILE.write_text(json.dumps(m, indent=2))


# ---- voice activity ----
VAD_AGGRESSIVENESS = 2       # 0..3; raise to 3 in a loud room
ENERGY_FLOOR = 600.0         # min RMS for speech. Measured: room 60–440, voice at arm's length 700–6000
NOISE_MULT = 3.0             # speech must be this many times the adaptive noise floor
START_FRAMES = 6             # voiced frames out of last 10 to open an utterance
END_SILENCE_MS = 700
MIN_SPEECH_MS = 500
MAX_UTTER_MS = 8000
MIC_TAIL_S = 0.4             # mics stay muted this long after any toy stops talking
ARBITRATE_S = 0.35           # wait this long for the same speech on other mics

# ---- perception ----
CAPTURE_FPS = 1.5
FACE_MATCH = 0.40            # SFace cosine; OpenCV suggests 0.363
PET_MATCH = 0.60
GREET_COOLDOWN_S = 120
IDLE_BANTER_S = 45           # 0 disables idle toy-to-toy chatter

# ---- LLM ----
VISION_MODE = os.environ.get("SENTIENT_VISION", "sage")   # sage | always | never
RESET_AFTER_TURNS = 8
MAX_LINES = 2
