"""Who is talking, by voice (Nov 15). A speaker-embedding model (sherpa-onnx + NVIDIA NeMo TitaNet-small, CPU, ~60 ms per clip)
turns an utterance into a 192-number voice print. Chosen on the Jetson over WeSpeaker CAM++ / CAM++-LM / ResNet34-LM and
TitaNet-large: 8 voices, 1-2 s test clips vs prints learned from 6 others: TitaNet-small 32/32 right, same voice >= 0.69,
different voices <= 0.47 (CAM++ 23/32, different voices up to 0.97 on short clips). Same privacy rules as faces (brain/teach.py):

  * PRINTS ONLY: the audio is RAM-only as always; only the vector is kept, encrypted inside the person's Parent Board entry
    (the one their face was taught under), deleted with it; nothing is learned while the board is locked;
  * only people a parent enrolled (with consent) ever get a voice; an unknown voice stays unknown;
  * names and vectors are never logged.

How a voice is learned, safest first:
  1. the Parent Board's "Learn voice" button: the next few things said near any toy are that person;
  2. the person says who they are ("I'm Dad", "it's Dad") and Dad is enrolled;
  3. automatically: the toy that heard it sees exactly ONE face, a known one, and the voice does not sound like someone else
     (once a person has MIN_PRINTS, a new print must also sound like them).
"""
from __future__ import annotations

import logging
import os
import re
import threading

import numpy as np

from . import config

log = logging.getLogger("voiceid")

MODEL = os.environ.get("SENTIENT_SPEAKER_MODEL", str(config.ROOT / "models" / "nemo_en_titanet_small.onnx"))
MATCH = float(os.environ.get("SENTIENT_VOICE_MATCH", "0.55"))   # cosine: same voice >= 0.69, different <= 0.47 (synthetic voices)
MARGIN = 0.06            # the best person must beat the runner-up by this much
MIN_S = 0.8              # shorter speech gives an unreliable print
MIN_PRINTS = 3           # prints before a voice is claimed, and before auto-learning needs the voice to agree
MAX_PRINTS = 30


class VoiceID:
    def __init__(self, model: str = MODEL):
        self.ex = None
        self._lock = threading.Lock()
        try:
            import sherpa_onnx as so
            if os.path.exists(model):
                self.ex = so.SpeakerEmbeddingExtractor(so.SpeakerEmbeddingExtractorConfig(model=model, num_threads=2, provider="cpu"))
                log.info("voice prints ready (%d numbers)", self.ex.dim)
            else:
                log.warning("voice prints off: no speaker model at %s", model)
        except Exception as e:  # noqa: BLE001 — no package: the toys just cannot tell voices apart
            log.warning("voice prints off (%s)", e)

    def __bool__(self):
        return self.ex is not None

    def embed(self, pcm) -> np.ndarray | None:
        if self.ex is None or pcm is None or len(pcm) < MIN_S * config.SAMPLE_RATE:
            return None
        x = np.asarray(pcm)
        x = (x.astype(np.float32) / 32768.0) if x.dtype == np.int16 else x.astype(np.float32)
        with self._lock:
            s = self.ex.create_stream()
            s.accept_waveform(config.SAMPLE_RATE, x)
            s.input_finished()
            if not self.ex.is_ready(s):
                return None
            v = np.asarray(self.ex.compute(s), dtype=np.float32)
        n = float(np.linalg.norm(v))
        return v / n if n > 0 else None


def _cos(a, b) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))


def match(voices, vec, threshold: float = MATCH):
    """voices: [(eid, name, role, [vec])]. Returns (eid, name, role, score) of the best person, or None. Each person scores the
    mean of their best 3 prints (one lucky print does not decide)."""
    if vec is None:
        return None
    scored = []
    for eid, name, role, vecs in voices:
        if len(vecs) < MIN_PRINTS:
            continue
        top = sorted((_cos(vec, v) for v in vecs), reverse=True)[:3]
        scored.append((sum(top) / len(top), eid, name, role))
    scored.sort(reverse=True)
    if not scored or scored[0][0] < threshold or (len(scored) > 1 and scored[0][0] - scored[1][0] < MARGIN):
        return None
    s, eid, name, role = scored[0]
    return eid, name, role, s


def agrees(vecs, vec, threshold: float = MATCH) -> bool:
    if not vecs:
        return True
    top = sorted((_cos(vec, v) for v in vecs), reverse=True)[:3]
    return sum(top) / len(top) >= threshold


INTRO = re.compile(r"\b(?:i'?m|i am|it'?s|it is|this is|my name is|me,)\s+(?:your\s+)?([a-z][a-z' -]{1,30}?)\s*(?:[.!?,]|$|\bhere\b)", re.I)


def introduced(text: str) -> str | None:
    """"I'm Dad", "it's Grandma here", "my name is Ana" -> the name said (lower case)."""
    m = INTRO.search(text or "")
    return m.group(1).strip().lower() if m else None
