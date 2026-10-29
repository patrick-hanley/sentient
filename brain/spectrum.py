"""Frequency content of the audio, for judging conversion quality. Numpy only.

`metrics()` works on any 16-bit PCM (what we send to an Atom, or what an Atom's mic hears).
`Monitor` keeps ~10 s of band levels per mic (content-free numbers, no audio). Raw audio is held
in RAM for `/tap.wav` only when SENTIENT_DEBUG_RECORD=1, like debugrec."""
from __future__ import annotations

import collections
import threading

import numpy as np

from . import debugrec

BANDS = [(0, 500), (500, 1000), (1000, 2000), (2000, 4000), (4000, 6000), (6000, 7200), (7200, 8000)]
FRAME = 1600   # 100 ms at 16 kHz


def _power(x: np.ndarray, n: int = 1024) -> tuple[np.ndarray, np.ndarray]:
    """Mean power spectrum (Hann frames, 50% overlap) and the frequency of each bin; full scale = 1.0."""
    x = x.astype(np.float32) / 32768.0
    if len(x) < n:
        x = np.pad(x, (0, n - len(x)))
    win = np.hanning(n).astype(np.float32)
    starts = range(0, len(x) - n + 1, n // 2)
    p = np.mean([np.abs(np.fft.rfft(x[s:s + n] * win)) ** 2 for s in starts], axis=0) / (win ** 2).sum()
    return p, np.fft.rfftfreq(n, 1 / 16000.0)


def band_db(x: np.ndarray, sr: int = 16000) -> dict[str, float]:
    """Level of each band in dB re full scale (power summed across the band)."""
    p, f = _power(x)
    out = {}
    for lo, hi in BANDS:
        sel = (f >= lo) & (f < hi if hi < 8000 else f <= hi)
        out[f"{lo}-{hi}"] = round(float(10 * np.log10(p[sel].sum() + 1e-12)), 1)
    return out


def metrics(pcm: bytes | np.ndarray) -> dict:
    x = np.frombuffer(pcm, "<i2") if isinstance(pcm, (bytes, bytearray)) else np.asarray(pcm)
    if len(x) == 0:
        return {}
    p, f = _power(x)
    cum = np.cumsum(p) / max(p.sum(), 1e-20)
    xf = x.astype(np.float32)
    return {"bands_db": band_db(x),
            "rms_dbfs": round(float(20 * np.log10(np.sqrt(np.mean((xf / 32768) ** 2)) + 1e-9)), 1),
            "peak": int(np.abs(x.astype(np.int32)).max()),
            "clipped": int((np.abs(x.astype(np.int32)) >= 32760).sum()),
            "rolloff95_hz": int(f[min(np.searchsorted(cum, 0.95), len(f) - 1)]),
            "above_7k_share_pct": round(float(100 * p[f >= 7000].sum() / max(p.sum(), 1e-20)), 3)}


class Monitor:
    def __init__(self, seconds: int = 10):
        self.frames: dict[str, collections.deque] = {}
        self.buf: dict[str, list] = {}
        self.audio: dict[str, collections.deque] = {}
        self.maxframes = seconds * 10
        self.lock = threading.Lock()

    def add(self, toy: str, pcm: np.ndarray) -> None:
        with self.lock:
            b = self.buf.setdefault(toy, [])
            b.append(pcm)
            if sum(len(c) for c in b) < FRAME:
                return
            x = np.concatenate(b)
            self.buf[toy] = []
            self.frames.setdefault(toy, collections.deque(maxlen=self.maxframes)).append(band_db(x))
            if debugrec.enabled():
                self.audio.setdefault(toy, collections.deque(maxlen=self.maxframes * 3)).append(x.astype("<i2"))

    def latest(self, toy: str, frames: int = 10) -> dict:
        """Average of the last `frames` 100 ms windows (default 1 s), dB per band."""
        with self.lock:
            fr = list(self.frames.get(toy, []))[-frames:]
        if not fr:
            return {}
        return {k: round(float(np.mean([f[k] for f in fr])), 1) for k in fr[0]}

    def tap(self, toy: str, seconds: float) -> bytes:
        """Last `seconds` of the mic as int16 PCM; empty unless SENTIENT_DEBUG_RECORD=1."""
        with self.lock:
            chunks = list(self.audio.get(toy, []))
        if not chunks:
            return b""
        x = np.concatenate(chunks)
        return x[-int(seconds * 16000):].tobytes()
