"""Per-child progress (session summaries + coaching state), encrypted in the Parent Board store.

Same envelope as the profiles: one file per child, sealed with the family DEK through Parent._seal/_open, so it can only
be read while the board is unlocked and is wiped with the child (Parent.delete_child) or with everything (wipe_all).
Only numbers and tags are ever put in here - no transcripts, no audio, no sentences (see docs/metrics.md).
"""
from __future__ import annotations

import json

from . import coaching
from .parent import Locked, _atomic_write, _wipe_file

MAX_SESSIONS = 60


class ProgressStore:
    def __init__(self, parent):
        self.p = parent

    def _name(self, cid):
        return f"progress-{cid}.enc"

    def _known(self, cid):
        self.p._require()
        self.p._child(cid)       # KeyError for an unknown child

    def load(self, cid: str) -> dict:
        with self.p._lock:
            self._known(cid)
            try:
                with open(self.p._file(self._name(cid)), "rb") as f:
                    data = json.loads(self.p._open(self.p._dek, f.read(), f"progress-{cid}".encode()))
            except OSError:
                data = {}
            data.setdefault("sessions", [])
            data.setdefault("coach", coaching.new_state())
            return data

    def save(self, cid: str, data: dict) -> None:
        with self.p._lock:
            self._known(cid)
            data["sessions"] = data["sessions"][-MAX_SESSIONS:]
            _atomic_write(self.p._file(self._name(cid)), self.p._seal(self.p._dek, json.dumps(data).encode(), f"progress-{cid}".encode()))

    def add_session(self, cid: str, summary: dict) -> list[dict]:
        """Store a finished session, then let the coaching loop look at it. Returns the coaching log entries it made."""
        with self.p._lock:
            data = self.load(cid)
            summary = dict(summary, id=f"s{summary.get('start', 0)}")
            data["sessions"].append(summary)
            made = coaching.after_session(data["coach"], summary, self.p.now())
            self.save(cid, data)
            return made

    def delete_session(self, cid: str, sid: str) -> bool:
        with self.p._lock:
            data = self.load(cid)
            keep = [s for s in data["sessions"] if s.get("id") != sid]
            hit = len(keep) != len(data["sessions"])
            data["sessions"] = keep
            self.save(cid, data)
            return hit

    def clear(self, cid: str, coach_too: bool = True) -> None:
        """The parent deletes the child's history (and, by default, what the toys learned from it)."""
        with self.p._lock:
            data = self.load(cid)
            data["sessions"] = []
            if coach_too:
                data["coach"] = coaching.new_state()
            self.save(cid, data)

    def wipe(self, cid: str) -> None:
        _wipe_file(self.p._file(self._name(cid)))

    def mutate_coach(self, cid: str, fn) -> object:
        with self.p._lock:
            data = self.load(cid)
            res = fn(data["coach"])
            self.save(cid, data)
            return res
