"""Speech conditioning between the TTS engines and the Atoms' speakers. Numpy only (runs on the Pi).

Order in Voices.render: band-limited resample (in tts._resample) -> trim silence -> [level] -> [speaker EQ, off by default] -> soft limit.
Bump VERSION whenever any of it changes: clip ids and the disk cache include it, so the clips stored on the
Atoms are re-rendered and re-uploaded."""
from __future__ import annotations

import hashlib
import json
import os
from functools import lru_cache
from pathlib import Path

import numpy as np

VERSION = 2
ENABLED = os.environ.get("SENTIENT_DSP", "1") != "0"
EQ_FILE = Path(__file__).with_name("speaker_eq.json")
EQ_ENABLED = os.environ.get("SENTIENT_DSP_EQ", "0") == "1"   # off: the Atoms' chain compresses, boosts barely reach the room (EXPERIMENTS.md)
LEVEL_DBFS = float(os.environ["SENTIENT_DSP_LEVEL"]) if os.environ.get("SENTIENT_DSP_LEVEL") else None   # off by default
SR = 16000


def resample(x: np.ndarray, src: float, dst: float, taps: int = 241, beta: float = 7.0) -> np.ndarray:
    """Any-ratio resampling: Kaiser-sinc low-pass at 90% of the target Nyquist (when shrinking, so nothing folds back),
    then cubic (Catmull-Rom) interpolation instead of linear. Measured: <-90 dB aliasing, -0.2 dB at 4 kHz where
    linear interpolation lost -0.9 dB; 13 ms per 5 s of speech. A full windowed-sinc interpolator is flatter at 6 kHz
    but ~30x slower on the Pi's TTS core."""
    x = np.asarray(x, np.float32)
    if abs(src - dst) < 1 or len(x) == 0:
        return x
    if dst < src and len(x) >= taps:
        fc = 0.9 * dst / 2
        n = np.arange(taps) - (taps - 1) // 2
        h = 2 * fc / src * np.sinc(2 * fc * n / src) * np.kaiser(taps, beta)
        x = np.convolve(x, (h / h.sum()).astype(np.float32), mode="same")
    pos = np.arange(int(round(len(x) * dst / src))) * (src / dst)
    i = np.floor(pos).astype(np.int64)
    t = (pos - i).astype(np.float32)
    p = np.pad(x, (2, 3))
    i = i + 2
    y0, y1, y2, y3 = p[i - 1], p[i], p[i + 1], p[i + 2]
    return 0.5 * (2 * y1 + (y2 - y0) * t + (2 * y0 - 5 * y1 + 4 * y2 - y3) * t * t + (3 * (y1 - y2) + y3 - y0) * t ** 3)


def trim(x: np.ndarray, thresh_dbfs: float = -50.0, lead_ms: int = 30, tail_ms: int = 120) -> np.ndarray:
    """Cut the neural voices' silent head and tail, keeping a short natural margin. x is int16-scaled float."""
    n = SR // 100
    frames = len(x) // n
    if frames < 4:
        return x
    rms = np.sqrt(np.mean((x[:frames * n].reshape(frames, n) / 32768.0) ** 2, axis=1) + 1e-12)
    live = np.nonzero(20 * np.log10(rms) > thresh_dbfs)[0]
    if len(live) == 0:
        return x
    a = max(0, live[0] * n - lead_ms * SR // 1000)
    b = min(len(x), (live[-1] + 1) * n + tail_ms * SR // 1000)
    y = x[a:b].copy()
    fade = min(len(y), SR // 200)   # 5 ms fade-in so a cut can never click
    y[:fade] *= np.linspace(0, 1, fade, dtype=np.float32)
    return y


def active_rms_dbfs(x: np.ndarray) -> float:
    """RMS of the frames that actually contain speech (so pauses don't change the level)."""
    n = SR // 100
    frames = len(x) // n
    if frames == 0:
        return -99.0
    f = (x[:frames * n].reshape(frames, n) / 32768.0).astype(np.float64)
    r = np.sqrt(np.mean(f ** 2, axis=1) + 1e-12)
    live = r[20 * np.log10(r) > -45]
    return float(20 * np.log10(np.sqrt(np.mean(live ** 2)) + 1e-12)) if len(live) else -99.0


def design_eq(hz, db, taps: int = 257) -> np.ndarray:
    """Zero-phase FIR from a gain curve (dB at hz). Linear between points on a log-frequency axis."""
    f = np.fft.rfftfreq(1024, 1 / SR)
    g = np.interp(np.log10(np.maximum(f, 1.0)), np.log10(np.asarray(hz, float)), np.asarray(db, float))
    h = np.fft.irfft(10 ** (g / 20))
    h = np.roll(h, taps // 2)[:taps] * np.hamming(taps)
    return h.astype(np.float32)


@lru_cache(maxsize=1)
def _curves() -> dict:
    try:
        return json.loads(EQ_FILE.read_text())
    except (OSError, ValueError):
        return {}


@lru_cache(maxsize=8)
def _fir(toy: str):
    c = _curves().get(toy)
    return design_eq(c["hz"], c["db"]) if c else None


@lru_cache(maxsize=8)
def _speaker_fir(toy: str):
    """The toy's measured speaker response as a FIR (zero-phase): loudness is judged through it, because the
    bass the EQ boosts is mostly not reproduced by the little driver."""
    c = _curves().get(toy)
    return design_eq(c["resp_hz"], c["resp_db"], taps=513) if c and "resp_hz" in c else None


def fingerprint() -> str:
    """Part of every clip id: changes with VERSION or when a speaker curve is re-measured."""
    if not ENABLED:
        return ""
    raw = EQ_FILE.read_bytes() if EQ_ENABLED and EQ_FILE.exists() else b""
    return f"{VERSION}.{hashlib.sha1(raw + str(LEVEL_DBFS).encode() + str(EQ_ENABLED).encode()).hexdigest()[:6]}"


def soft_limit(x: np.ndarray, knee: float = 0.95) -> np.ndarray:
    return x / (1.0 + (np.abs(x) / knee) ** 8) ** (1.0 / 8.0)


def finish(pcm: bytes, toy: str) -> bytes:
    """16 kHz int16 speech -> trimmed, levelled (optional), speaker-equalised, soft-limited int16."""
    if not ENABLED or not pcm:
        return pcm
    x = np.frombuffer(pcm, "<i2").astype(np.float32)
    x = trim(x)
    if LEVEL_DBFS is not None:
        x *= 10 ** ((LEVEL_DBFS - active_rms_dbfs(x)) / 20)
    fir = _fir(toy) if EQ_ENABLED else None
    if fir is not None:
        spk = _speaker_fir(toy)
        heard = (lambda y: active_rms_dbfs(np.convolve(y, spk, mode="same"))) if spk is not None else active_rms_dbfs
        before = heard(x)
        x = np.convolve(x, fir, mode="same")
        x *= 10 ** ((before - heard(x)) / 20)   # tone changes, loudness as the speaker plays it does not
    return (soft_limit(x / 32768.0) * 32768.0).astype("<i2").tobytes()
