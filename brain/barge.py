"""Barge-in: the child starts talking while a toy is talking -> cut the toy and listen.

A toy cannot hear while its own speaker plays (shared codec), but the other toys' mics keep streaming. While one toy
talks, each of the others is watched for a voice clearly louder than that toy's own speech leaking into the room:
`ref` is the loudest 100 ms of leakage seen so far in this clip (it decays slowly), and a voice must beat it by
BARGE_RATIO for BARGE_MS in a row, above BARGE_MIN_RMS, and be speech to webrtcvad. Audio is RAM only: a 300 ms ring
per toy, handed to the normal segmenter on a trigger so the first word is not lost."""
from __future__ import annotations

import collections
import logging

import numpy as np
import webrtcvad

from . import config

log = logging.getLogger("barge")
FRAME_MS = 20


class BargeDetector:
    def __init__(self):
        self.vad = webrtcvad.Vad(config.VAD_AGGRESSIVENESS)
        self.st: dict[str, dict] = {}
        self.session = None
        self.max_ratio = 0.0     # for calibration: highest loudness-over-leakage ratio seen in the last clip

    def _state(self, toy):
        return self.st.setdefault(toy, dict(ref=0.0, win=collections.deque(maxlen=5), run=0, voiced=0, n=0,
                                            ring=collections.deque(maxlen=15), lag=collections.deque(maxlen=25)))

    def reset(self, session=None):
        self.session = session
        self.st.clear()
        self.max_ratio = 0.0

    def feed(self, toy: str, pcm: np.ndarray, session) -> list[np.ndarray] | None:
        """Returns the buffered frames (the start of the child's speech) when a barge-in is detected, else None."""
        if session != self.session:
            self.reset(session)
        if len(pcm) != 320:
            return None
        s = self._state(toy)
        s["ring"].append(pcm)
        rms = float(np.sqrt(np.mean(pcm.astype(np.float32) ** 2)))
        s["win"].append(rms)
        s["n"] += 1
        m = sum(s["win"]) / len(s["win"])
        s["ref"] = max(s["ref"] * 0.9985, m) if s["n"] > 5 else max(s["ref"], m)   # ~half-life 7 s at 50 frames/s
        if s["n"] < config.BARGE_WARMUP_MS // FRAME_MS:
            return None
        # compare with the leakage level from 0.5 s ago, before this voice rose (ref already includes the current frames)
        s["lag"].append(s["ref"])
        prior = s["lag"][0]
        loud = m > max(config.BARGE_MIN_RMS, config.BARGE_RATIO * prior)
        self.max_ratio = max(self.max_ratio, m / max(prior, 1.0))
        speech = self.vad.is_speech(pcm.tobytes(), config.SAMPLE_RATE)
        if loud and rms > config.BARGE_MIN_RMS * 0.6:
            s["run"] += 1
            s["voiced"] += bool(speech)
        else:
            s["run"] = s["voiced"] = 0
        if s["run"] * FRAME_MS >= config.BARGE_MS and s["voiced"] * 2 >= s["run"]:
            frames = list(s["ring"])
            self.reset(session)
            return frames
        return None
