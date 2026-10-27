"""Per-toy voice activity detection -> whole utterances."""
from __future__ import annotations

import collections
import queue
import time
from dataclasses import dataclass

import numpy as np
import webrtcvad

from . import config

FRAME_MS = 20


@dataclass
class Utterance:
    toy: str
    start: float
    end: float
    pcm: np.ndarray       # int16 mono 16 kHz
    rms: float            # mean RMS over voiced frames: loudest mic = closest toy
    last_voiced_received: float | None = None  # monotonic host receipt time, not sensor time
    emitted: float | None = None
    arbitrated: float | None = None
    speech_ms: float = 0.0   # first voiced pre-roll to last voiced frame, host clock


class Segmenter:
    def __init__(self, toy: str, out: "queue.Queue[Utterance]"):
        self.toy, self.out = toy, out
        self.vad = webrtcvad.Vad(config.VAD_AGGRESSIVENESS)
        self.noise = 150.0
        self.level = 0.0
        self.reset()

    def reset(self):
        self.pre = collections.deque(maxlen=15)
        self.hist = collections.deque(maxlen=10)
        self.active = False
        self.buf: list[np.ndarray] = []
        self.voiced = 0
        self.voiced_rms = 0.0
        self.silence = 0

    def feed(self, pcm: np.ndarray):
        if len(pcm) != 320:
            return
        rms = float(np.sqrt(np.mean(pcm.astype(np.float32) ** 2)))
        self.level = rms
        speech = (rms > max(config.ENERGY_FLOOR, self.noise * config.NOISE_MULT)
                  and self.vad.is_speech(pcm.tobytes(), config.SAMPLE_RATE))
        if not speech:
            self.noise = 0.98 * self.noise + 0.02 * rms
        if not self.active:
            self.pre.append(pcm)
            self.hist.append(speech)
            if sum(self.hist) >= config.START_FRAMES:
                self.active = True
                self.start = time.time() - len(self.pre) * FRAME_MS / 1000
                self.buf = list(self.pre)
                self.voiced, self.voiced_rms, self.silence = sum(self.hist), rms * sum(self.hist), 0
                self.last_voiced_received = time.monotonic()
                self.start_mono = self.last_voiced_received - len(self.pre) * FRAME_MS / 1000
            return
        self.buf.append(pcm)
        if speech:
            self.last_voiced_received = time.monotonic()
            self.voiced += 1
            self.voiced_rms += rms
            self.silence = 0
        else:
            self.silence += 1
        if (self.silence * FRAME_MS >= config.END_SILENCE_MS
                or len(self.buf) * FRAME_MS >= config.MAX_UTTER_MS):
            if self.voiced * FRAME_MS >= config.MIN_SPEECH_MS:
                pcm_all = np.concatenate(self.buf[: len(self.buf) - max(0, self.silence - 10)])
                self.out.put(Utterance(self.toy, self.start, time.time(), pcm_all,
                                       self.voiced_rms / max(1, self.voiced),
                                       self.last_voiced_received, time.monotonic(), None,
                                       (self.last_voiced_received - self.start_mono) * 1000))
            self.reset()


def arbitrate(first: Utterance, q: "queue.Queue[Utterance]", expected_toys=None) -> Utterance:
    """The same voice reaches every toy's mic: keep the loudest copy."""
    best = first
    expected = set(expected_toys) if expected_toys is not None else None
    seen = {first.toy}
    deadline = time.monotonic() + config.ARBITRATE_S
    while (left := deadline - time.monotonic()) > 0:
        if expected is not None and expected <= seen:
            break
        try:
            u = q.get(timeout=left)
        except queue.Empty:
            break
        if u.start < first.end + 1.0 and u.end > first.start - 1.0:   # overlapping speech
            seen.add(u.toy)
            if u.rms > best.rms:
                best = u
        else:
            q.put(u)   # a genuinely separate utterance: leave it for the next turn
            break
    return best


def normalize(pcm: np.ndarray, peak: float = 0.7) -> np.ndarray:
    x = pcm.astype(np.float32)
    m = float(np.max(np.abs(x))) or 1.0
    return np.clip(x * (peak * 32767 / m), -32768, 32767).astype("<i2")
