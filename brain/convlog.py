"""Conversation log for review (Nov 15, user: "a simple way to upload the conversation logs, get graded by a better model and
improvements made"). One entry per turn: what the child said (words only), what each toy said, and a few flags. RAM only: never written
to disk by the brain, gone on restart, cleared on request. Read it from the brain itself (GET /convlog on 127.0.0.1: the review tool
over ssh) or on the PIN-protected Parent Board (download / clear). tools/review_convlog.py pulls it, scores it and prepares the review.
"""
from __future__ import annotations

import collections
import threading
import time

from . import config


class ConvLog:
    def __init__(self, maxlen: int | None = None):
        self.items = collections.deque(maxlen=maxlen or config.CONVLOG_MAX)
        self.lock = threading.Lock()
        self.cleared_at = time.time()

    def add(self, *, kind: str, heard_by: str | None, heard: str, said: list, status: str, latency_s: float | None = None,
            flags: dict | None = None) -> None:
        if not config.CONVLOG:
            return
        e = {"t": time.strftime("%Y-%m-%d %H:%M:%S"), "kind": kind, "heard_by": heard_by, "heard": heard or "",
             "said": [[w, t] for w, t in said], "status": status, "latency_s": latency_s, "flags": {k: v for k, v in (flags or {}).items() if v}}
        with self.lock:
            self.items.append(e)

    def dump(self) -> dict:
        with self.lock:
            return {"since": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.cleared_at)), "turns": list(self.items)}

    def clear(self) -> int:
        with self.lock:
            n = len(self.items)
            self.items.clear()
            self.cleared_at = time.time()
            return n

    def __len__(self):
        return len(self.items)
