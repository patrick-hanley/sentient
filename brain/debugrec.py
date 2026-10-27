"""Opt-in WAV capture for judging runs. Off unless SENTIENT_DEBUG_RECORD=1.

Files go to a private temp dir that is deleted at exit, and anything older than
MAX_AGE_S is pruned on every write. Nothing is ever written under the repo."""
from __future__ import annotations

import atexit
import itertools
import os
import shutil
import tempfile
import threading
import time
import wave

from . import config

MAX_AGE_S = 3600
_lock = threading.Lock()
_dir = None
_n = itertools.count(1)


def enabled() -> bool:
    return os.environ.get("SENTIENT_DEBUG_RECORD") == "1"


def directory() -> str | None:
    global _dir
    if not enabled():
        return None
    with _lock:
        if _dir is None:
            _dir = tempfile.mkdtemp(prefix="sentient-debug-audio-")
            atexit.register(shutil.rmtree, _dir, True)
    return _dir


def save(kind: str, toy: str, pcm: bytes) -> str | None:
    """Write 16 kHz mono int16 `pcm` as <kind>-<toy>-<n>.wav; returns the path (or None when disabled)."""
    d = directory()
    if not d or not pcm:
        return None
    now = time.time()
    for name in os.listdir(d):
        path = os.path.join(d, name)
        try:
            if now - os.path.getmtime(path) > MAX_AGE_S:
                os.unlink(path)
        except OSError:
            pass
    path = os.path.join(d, f"{kind}-{toy}-{next(_n):04d}.wav")
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(config.SAMPLE_RATE)
        w.writeframes(pcm)
    return path
