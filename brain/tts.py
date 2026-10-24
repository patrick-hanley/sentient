"""Piper voices per toy, rendered to 16 kHz mono int16 bytes for the Atoms."""
from __future__ import annotations

import logging
import threading

import numpy as np

from . import config

log = logging.getLogger("tts")


def _resample(x: np.ndarray, src: float, dst: float) -> np.ndarray:
    if abs(src - dst) < 1:
        return x
    n = int(round(len(x) * dst / src))
    return np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x)


class Voices:
    def __init__(self):
        from piper import PiperVoice  # imported here so --help works without piper
        self._voices = {}
        self._lock = threading.Lock()
        for name in {t["voice"] for t in config.TOYS.values()}:
            path = config.OFFLINE / "piper" / f"{name}.onnx"
            self._voices[name] = PiperVoice.load(str(path))
            log.info("voice loaded: %s", name)
        self._cache: dict[tuple[str, str], bytes] = {}

    def render(self, toy: str, text: str) -> bytes:
        key = (toy, text)
        if key in self._cache:
            return self._cache[key]
        from piper import SynthesisConfig
        t = config.TOYS[toy]
        voice = self._voices[t["voice"]]
        syn = SynthesisConfig(speaker_id=t["speaker"], length_scale=t["length"] * t["pitch"])
        with self._lock:  # onnxruntime sessions are not re-entrant-safe across threads here
            chunks = list(voice.synthesize(text, syn_config=syn))
        if not chunks:
            return b""
        sr = chunks[0].sample_rate
        audio = np.concatenate([c.audio_int16_array for c in chunks]).astype(np.float32)
        # pitch trick: synthesized slower by `pitch`, then played back `pitch`x faster.
        audio = _resample(audio, sr * t["pitch"], config.SAMPLE_RATE)
        pcm = np.clip(audio, -32768, 32767).astype("<i2").tobytes()
        if len(self._cache) < 500:
            self._cache[key] = pcm
        return pcm

    def prerender(self, lines: list[tuple[str, str]]) -> None:
        for toy, text in lines:
            self.render(toy, text)
