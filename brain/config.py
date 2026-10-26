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
LLAMA_URL = os.environ.get("SENTIENT_LLAMA_URL", "http://127.0.0.1:8081").rstrip("/")
GENIEX_URL = os.environ.get("SENTIENT_GENIEX_URL", "http://127.0.0.1:18181").rstrip("/")
GENIEX_MODEL = os.environ.get("SENTIENT_GENIEX_MODEL", "google/gemma-4-E2B-it-qat-q4_0-gguf:Q4_0")

# Kokoro-82M (kokoro-onnx). Toys with a "kokoro" voice use it when these files and the package exist;
# otherwise they fall back to their Piper voice. On the Pi 5 CPU it runs ~0.8x real time (Piper ~10x).
KOKORO_DIR = Path(os.environ.get("SENTIENT_KOKORO_DIR", OFFLINE / "kokoro"))
USE_KOKORO = os.environ.get("SENTIENT_KOKORO", "1") != "0"
# int8 + ORT_ENABLE_ALL measured fastest on the Pi 5 (x1.1 real time vs x0.84 for fp32; q4/uint8 no better)
KOKORO_MODEL = os.environ.get("SENTIENT_KOKORO_MODEL", "kokoro-v1.0.int8.onnx")
SFX_DIR = Path(os.environ.get("SENTIENT_SFX_DIR", OFFLINE / "sfx"))   # tools/fetch_sfx.py (CC0, Freesound)
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
    "dyno": dict(name="Dyno", aruco=1, voice="en_GB-alba-medium", speaker=None, length=0.9, pitch=1.25,
                 kokoro="af_heart", kspeed=1.1, kpitch=1.15,   # Kokoro (American), pitched up
                 looks="a little green dinosaur plush",
                 persona="curious and bouncy; asks the child short questions about school and games; easily "
                         "amazed; sometimes growls with the {dino_growl} sound"),
    "sage": dict(name="Sage", aruco=2, voice="en_GB-alba-medium", speaker=None, length=1.08, pitch=1.0,
                 kokoro="bf_emma", kspeed=0.95, kpitch=1.0,    # Kokoro (British)
                 looks="a baby dressed up in a unicorn costume, with a horn",
                 persona="calm and careful; explains things simply; the reader who can look at books, worksheets "
                         "and pictures; helps with homework by giving hints, not just answers"),
    "penny": dict(name="Penny", aruco=3, voice="en_US-libritts_r-medium", speaker=20, length=0.95, pitch=1.25,
                  kokoro="af_heart", kspeed=1.05, kpitch=1.0,  # Kokoro (American)
                  looks="a penguin wearing a white hat",
                  persona="whimsical, silly and giggly; enjoys wordplay, playful comparisons and clearly marked "
                          "make-believe; gives careful, accurate answers to school questions, including facts, math "
                          "and spelling; admits when unsure and explores with the child; never makes deliberate errors"),
}
# What the toys talk about (2nd-5th grade). Idle banter picks one of BANTER_SEEDS.
AUDIENCE = "a child in 2nd to 5th grade (about 7 to 11 years old)"
TOPICS = [
    "school subjects: reading (including classic fairy tales), spelling, writing, math (adding, subtracting, "
    "times tables, fractions, word problems), science (animals, plants, weather, planets, the human body), "
    "maps and the 50 states, and history",
    "homework: help with hints and guiding questions so the child figures it out, not just the answer",
    "toys and games: board games, card games, puzzles, riddles, playground games, and learning games like "
    "spelling bee, math quiz, rhyming, I spy and 20 questions",
]
BANTER_SEEDS = [
    "a times-table quiz", "a spelling bee word", "a riddle", "rhyming words", "20 questions about an animal",
    "which planet is the biggest", "a math word problem", "fractions with pizza slices", "states and their capitals",
    "the water cycle", "a favorite board game", "I spy with colors", "a homework tip", "the Three Little Pigs",
    "a tricky spelling word", "how plants grow", "a favorite toy", "counting by fives",
]
# Voice settings changed from the dashboard persist here and override TOYS at startup.
VOICE_FILE = DATA / "voice_settings.json"
VOICE_FIELDS = ("kokoro", "kspeed", "kpitch", "voice", "speaker", "length", "pitch", "gain")


def save_voice_settings() -> None:
    VOICE_FILE.write_text(json.dumps({k: {f: t.get(f) for f in VOICE_FIELDS} for k, t in TOYS.items()}, indent=2))


def _load_voice_settings() -> None:
    try:
        saved = json.loads(VOICE_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return
    for toy, fields in saved.items():
        if toy in TOYS:
            TOYS[toy].update({f: v for f, v in fields.items() if f in VOICE_FIELDS})


TOY_ORDER = ["dyno", "sage", "penny"]
MAC_MAP_FILE = DATA / "toys.json"   # {"AA:BB:..": "dyno"} — auto-filled in arrival order, edit to reassign


_load_voice_settings()


def load_mac_map() -> dict[str, str]:
    try:
        return json.loads(MAC_MAP_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_mac_map(m: dict[str, str]) -> None:
    MAC_MAP_FILE.write_text(json.dumps(m, indent=2))


# ---- voice activity ----
VAD_AGGRESSIVENESS = 2       # 0..3; raise to 3 in a loud room
ENERGY_FLOOR = 100.0         # min RMS for speech; the adaptive NOISE_MULT term does the real work.
                             # Measured: quiet room ~12 / voice 140-1060; noisy venue 60-440 / voice 700-6000
NOISE_MULT = 4.0             # speech must be 4x the measured room noise (quiet ~100, venue ~600)
START_FRAMES = 6             # voiced frames out of last 10 to open an utterance
END_SILENCE_MS = 500
MIN_SPEECH_MS = 500
MAX_UTTER_MS = 8000
MIC_TAIL_S = 0.4             # mics stay muted this long after any toy stops talking
ARBITRATE_S = 0.12           # upper bound; stop sooner when all online mics have reported

# Responsive overlaps model, synthesis and playback. Patient preserves the old
# pause tolerance for children who pause between words. Neither changes VAD onset.
LATENCY_PROFILE = "responsive"
PLAY_FILLERS = True
PAUSE_CAPTURE_DURING_TURN = True
VISION_MAX_AGE_S = 3.0


def apply_latency_profile(name: str) -> None:
    global LATENCY_PROFILE, END_SILENCE_MS, ARBITRATE_S, PLAY_FILLERS
    if name not in ("responsive", "patient"):
        raise ValueError("Latency profile must be responsive or patient")
    LATENCY_PROFILE = name
    END_SILENCE_MS, ARBITRATE_S, PLAY_FILLERS = (
        (500, .12, True) if name == "responsive" else (700, .35, True))   # fillers mask Gemma's ~3-5 s on the Pi

# ---- perception ----
CAPTURE_FPS = 0.5            # one snapshot per toy every 2 s; paused entirely during a turn
FACE_MATCH = 0.40            # SFace cosine; OpenCV suggests 0.363
PET_MATCH = 0.60
GREET_COOLDOWN_S = 120
IDLE_BANTER_S = 45           # 0 disables idle toy-to-toy chatter

# ---- LLM ----
VISION_MODE = os.environ.get("SENTIENT_VISION", "sage")   # sage | always | never
RESET_AFTER_TURNS = 8
MAX_LINES = 3                # one line each when all three toys are here
