"""All tunables in one place. Edit freely at the venue."""
from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OFFLINE = Path(os.environ.get("SENTIENT_OFFLINE", ROOT / "offline"))
DATA = Path(__file__).resolve().parent / "data"
DATA.mkdir(exist_ok=True)

TOY_TALK = int(os.environ.get("SENTIENT_TOY_TALK", "0"))   # idle-banter conversation advice level (brain/toytalk.py); 0 = off
SCENE_TOPIC = int(os.environ.get("SENTIENT_SCENE_TOPIC", "1"))   # ON (graded keep, docs/grades/ledger.md s1b/s2d); 1 = a toy-to-toy chat keeps one [TOPIC] instead of fresh [GRADE TOPICS] each turn (docs/gemma-conversation-settings.md #1)
JUST_SAID = int(os.environ.get("SENTIENT_JUST_SAID", "0"))       # 1 = a continuing toy chat quotes the last two lines and asks the first line to build on them (#3; needs SCENE_TOPIC)
BEATS = int(os.environ.get("SENTIENT_BEATS", "1"))               # ON (graded keep s2d); 1 = each line of a continuing toy chat gets a job: ask -> answer -> playful reaction (#2; needs SCENE_TOPIC)
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
PARENT_PORT = int(os.environ.get("SENTIENT_PARENT_PORT", "8090"))   # Parent Board (PIN, encrypted profiles); 0 = off
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
    "the water cycle", "a favorite board game", "the colors of the rainbow", "a homework tip", "the Three Little Pigs",
    "a tricky spelling word", "how plants grow", "a favorite toy", "counting by fives",
]
# Voice settings changed from the dashboard persist here and override TOYS at startup.
VOICE_FILE = DATA / "voice_settings.json"
VOICE_FIELDS = ("kitten", "kokoro", "kspeed", "kpitch", "voice", "speaker", "length", "pitch", "gain")


def save_voice_settings() -> None:
    VOICE_FILE.write_text(json.dumps({k: {f: t[f] for f in VOICE_FIELDS if t.get(f) is not None or f in ("kokoro", "speaker")}
                                      for k, t in TOYS.items()}, indent=2))


def _load_voice_settings() -> None:
    try:
        saved = json.loads(VOICE_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return
    for toy, fields in saved.items():
        if toy in TOYS:
            # null means "not set" (an older save wrote gain: null): keep the default then
            TOYS[toy].update({f: v for f, v in fields.items() if f in VOICE_FIELDS and (v is not None or f in ("kokoro", "speaker"))})


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
BARGE_IN = os.environ.get("SENTIENT_BARGE_IN", "1") != "0"   # the child talks over a toy: cut it, listen
BARGE_RATIO = float(os.environ.get("SENTIENT_BARGE_RATIO", "3.0"))   # voice must beat the toy's own leakage by this factor
BARGE_MIN_RMS = float(os.environ.get("SENTIENT_BARGE_MIN_RMS", "350"))
BARGE_MS = 160               # ...for this long, in a row
BARGE_WARMUP_MS = 300        # learn the leakage level first
# Cross-toy echo cancellation (brain/aec.py, docs/aec.md): the listeners' mics keep working while a toy talks
AEC = os.environ.get("SENTIENT_AEC", "1") == "1"             # ON by default (fw 3.9 fixed the lost mic audio; docs/aec.md); SENTIENT_AEC=0 turns it off
# Fact guard (brain/factcheck.py): every toy line is checked before it is spoken; wrong sums, letter counts, spellings, counting runs,
# known counts (legs, sides, days...), planets and capitals are fixed in place, or the sentence is dropped. The facts can not be wrong.
FACT_GUARD = os.environ.get("SENTIENT_FACT_GUARD", "1") == "1"
# Toy chats about a curriculum item get its verified one-line summary as [TRUE FACTS] (the facts the chat may use)
TRUE_FACTS = os.environ.get("SENTIENT_TRUE_FACTS", "0") == "1"   # s4 16.34, s4c 16.00 vs 16.59: not a graded keep yet
# the stronger facts sentence in the system prompt (s4: repeats 1 -> 9 with it; off until graded clean). The fact guard does not need it.
STRICT_FACTS_PROMPT = os.environ.get("SENTIENT_STRICT_FACTS", "0") == "1"
AEC_PARTS = 8                # filter = 8 x 20 ms blocks = 160 ms of room echo
AEC_MU = float(os.environ.get("SENTIENT_AEC_MU", "0.5"))
AEC_SEARCH_S = 0.4           # seconds of the clip heard before the first GCC-PHAT lag search (warm starts skip it)
AEC_PLACE_S = 0.3            # seconds of a later clip heard before its narrow re-alignment around the last lag
AEC_MIN_SCORE_PLACE = 4.0
AEC_MIN_SCORE = 6.0          # PHAT peak over the search range's other lags: weaker means no echo heard
AEC_DT_RATIO = 2.0           # residual amplitude over the predicted leftover echo + noise that marks a second voice
AEC_MIN_RMS = 250.0          # ...and it must be at least this loud (int16 RMS)
AEC_BARGE_MS = 120           # ...for this long, mostly speech to webrtcvad, to cut the toy
AEC_PREROLL_FRAMES = 15      # residual frames kept before the first loud one, so the first word is not lost
AEC_EXPLAIN_RATIO = 0.45     # a loud residual that a re-adapted filter removes this much of is echo-path change, not the child
AEC_WARM = 0                 # 1 = a later clip of a pair starts cancelling at once with the last filter and lag (verified after AEC_WARM_S)
AEC_WARM_S = 0.2             # audible echo heard before the warm lag is checked with a narrow GCC-PHAT
AEC_RES = 1                  # 1 = residual echo suppressor after the filter (per-bin gain from the echo the filter predicts)
AEC_RES_ALPHA = 3.5          # over-subtraction of the estimated residual echo
AEC_RES_FLOOR = 0.1          # lowest gain (0.1 = -20 dB)
AEC_RES_DT = 0.3             # alpha is scaled by this while a second voice is detected (double-talk protection)
AEC_RES_ONSET = 1.0          # alpha is multiplied by this during the first AEC_RES_ONSET_S of a clip while no second voice is detected
AEC_RES_ONSET_S = 1.0
AEC_MAG = 1                  # 1 = before the filter can be trusted (cold start, warm check), a stored per-pair echo-path magnitude |H(f)| x the placed reference drives the suppressor
AEC_MAG_ALPHA = 1.0          # over-subtraction in that mode (the magnitude is only a prior: be conservative)
AEC_PERSIST = int(os.environ.get("SENTIENT_AEC_PERSIST", "1"))   # 1 = keep each pair's echo lag and path magnitude across restarts (numbers only, no audio)
AEC_PATHS_FILE = DATA / "aec_paths.json"
AEC_PATHS_MAX_AGE_H = 168     # a stored path older than this (toys moved, a new room) is ignored
AEC_STOP_LATENCY_S = 0.04    # STOP is sent -> speaker silent (the clip's reference is cut then)
MIC_TAIL_S = 0.4             # mics stay muted this long after any toy stops talking
ARBITRATE_S = 0.12           # upper bound; stop sooner when all online mics have reported

# Responsive overlaps model, synthesis and playback. Patient preserves the old
# pause tolerance for children who pause between words. Neither changes VAD onset.
LATENCY_PROFILE = "responsive"
PLAY_FILLERS = True
BRIDGE_WAIT_S = 0.35         # next line not rendered after this long: its speaker plays a canned reaction
MAX_BRIDGES = 3              # per turn
PAUSE_CAPTURE_DURING_TURN = True
VISION_MAX_AGE_S = 3.0


def apply_latency_profile(name: str) -> None:
    global LATENCY_PROFILE, END_SILENCE_MS, ARBITRATE_S, PLAY_FILLERS
    if name not in ("responsive", "patient"):
        raise ValueError("Latency profile must be responsive or patient")
    LATENCY_PROFILE = name
    END_SILENCE_MS, ARBITRATE_S, PLAY_FILLERS = (
        (500, .12, True) if name == "responsive" else (700, .35, True))   # fillers mask Gemma's ~3-5 s on the Pi

# ---- CPU budgeting (Linux only; experiment on the Pi 5, e.g. SENTIENT_LLM_CORES=0,1,2 SENTIENT_TTS_CORES=3) ----
def _cores(name):
    raw = os.environ.get(name, "").strip()
    return {int(x) for x in raw.split(",") if x.strip().isdigit()} or None


LLM_CORES, TTS_CORES = _cores("SENTIENT_LLM_CORES"), _cores("SENTIENT_TTS_CORES")


def pin(cores) -> None:
    """Restrict the calling thread (and threads it creates afterwards) to `cores`; no-op where unsupported."""
    if cores and hasattr(os, "sched_setaffinity"):
        os.sched_setaffinity(0, cores)


# ---- perception ----
# Camera policy (brain/camera.py): the cameras are OFF. A toy takes ONE picture only when the child asks what it sees
# ("what do you see", "look at this", "what is this"), from the toy that heard the child, and the camera is off again after.
# Continuous capture (the old behaviour: greet familiar faces, always-fresh [SCENE]) is opt-in: SENTIENT_CAMERA_CONTINUOUS=1.
CAPTURE_CONTINUOUS = os.environ.get("SENTIENT_CAMERA_CONTINUOUS", "0") == "1"
# Camera mode, switchable from the dashboard and kept across restarts (brain/data/camera_mode.json):
#   off      the toys never take a picture (asked what they see, they say their eyes are off)
#   request  the default: one picture only when the child asks (look / I spy), camera off again after
#   always   continuous capture (CAPTURE_CONTINUOUS)
CAMERA_MODES = ("off", "request", "always")
CAMERA_MODE_FILE = DATA / "camera_mode.json"
LOOK_ON_REQUEST = True


def set_camera_mode(mode: str, save: bool = True) -> str:
    global CAMERA_MODE, CAPTURE_CONTINUOUS, LOOK_ON_REQUEST
    if mode not in CAMERA_MODES:
        raise ValueError(mode)
    CAMERA_MODE, CAPTURE_CONTINUOUS, LOOK_ON_REQUEST = mode, mode == "always", mode != "off"
    if save:
        try:
            CAMERA_MODE_FILE.write_text(json.dumps({"mode": mode}))
        except OSError:
            pass
    return mode


try:
    CAMERA_MODE = json.loads(CAMERA_MODE_FILE.read_text())["mode"]
    if CAMERA_MODE not in CAMERA_MODES or os.environ.get("SENTIENT_CAMERA_CONTINUOUS"):
        raise ValueError
except (OSError, ValueError, KeyError, TypeError):
    CAMERA_MODE = "always" if CAPTURE_CONTINUOUS else "request"
set_camera_mode(CAMERA_MODE, save=False)
# I spy (brain/camera.py): when the child plays I spy, every turn of the game takes ONE picture from the toy that heard them and the
# toys guess only things in it (or say nothing there matches). The game ends after ISPY_GAME_S without the child, or on "stop playing".
ISPY = os.environ.get("SENTIENT_ISPY", "1") == "1"
ISPY_GAME_S = float(os.environ.get("SENTIENT_ISPY_GAME_S", "90"))
CAPTURE_FPS = 0.5            # continuous mode only: one snapshot per toy every 2 s; paused entirely during a turn
FACE_MATCH = 0.40            # SFace cosine; OpenCV suggests 0.363
PET_MATCH = 0.60
GREET_COOLDOWN_S = 120
IDLE_BANTER_S = 45           # 0 disables idle toy-to-toy chatter
# The child leads (Nov 15, user: "the conversations should center around what the human wants to talk about"): answer the child's
# subject first and stay on it; questions about the parent's notes are answered; "stop" quiets the toys.
CHILD_LEADS = os.environ.get("SENTIENT_CHILD_LEADS", "1") == "1"
CHILD_MAX_LINES = int(os.environ.get("SENTIENT_CHILD_MAX_LINES", "2"))   # the child spoke: one answer + at most one short add-on
IDLE_AFTER_CHILD_S = float(os.environ.get("SENTIENT_IDLE_AFTER_CHILD_S", "180"))   # no toy-to-toy chat this soon after the child spoke
STOP_QUIET_S = float(os.environ.get("SENTIENT_STOP_QUIET_S", "600"))              # after "stop": no toy-to-toy chat for this long
# Conversation log for review (brain/convlog.py): RAM only, last CONVLOG_MAX turns; the child's words + the toys' lines
CONVLOG = os.environ.get("SENTIENT_CONVLOG", "1") == "1"
CONVLOG_MAX = int(os.environ.get("SENTIENT_CONVLOG_MAX", "2000"))
QUIET_AFTER_S = (180, 600)   # no child contact (speech, tap, motion, someone seen) for a random time in this range: the toys go silent

# ---- LLM ----
VISION_MODE = os.environ.get("SENTIENT_VISION", "sage")   # sage | always | never
VISION_MODEL = os.environ.get("SENTIENT_VISION_MODEL", "gemma")   # gemma (own vision, no extra model) | llamacpp | florence | none; see brain/vision_model.py
RESET_AFTER_TURNS = 8
MAX_LINES = 4                # e.g. dyno, sage, dyno, penny: toys may speak more than once

# ---- conversation metrics + coaching (brain/metrics.py, brain/coaching.py, docs/metrics.md) ----
METRICS_ON = os.environ.get("SENTIENT_METRICS", "1") != "0"
METRICS_IDLE_GAP_S = 180     # a pause this long ends a session (the rubric samples 5-10 minute windows)
METRICS_MAX_SESSION_S = 600  # ...and a session never runs longer than this, so every session is a 5-10 minute sample
METRICS_MIN_SESSION_S = 60   # shorter sessions are counted but not scored
METRICS_MIN_CHILD_UTTS = 3
METRICS_JUDGE = os.environ.get("SENTIENT_METRICS_JUDGE", "0") == "1"   # local-Gemma second opinion, off by default (needs RAM-only text)

HEALTH_POLL_S = float(os.environ.get("SENTIENT_HEALTH_POLL_S", "30"))   # brain/atoms.py: refresh each toy's /status (codec failures, volume)
