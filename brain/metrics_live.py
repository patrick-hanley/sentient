"""Glue between the Director and the metrics/coaching modules. Every method is exception-proof: measuring and coaching
must never be able to break a turn. Director edits are one-liners that call into this class (docs/metrics.md)."""
from __future__ import annotations

import logging
import statistics
import time

from . import coaching, config
from .metrics import SessionTracker
from .progress import ProgressStore

log = logging.getLogger("metrics")


def safe(fn):
    def wrapper(self, *a, **k):
        try:
            return fn(self, *a, **k)
        except Exception:  # noqa: BLE001
            log.debug("metrics hook failed", exc_info=True)
            return None
    wrapper.__name__ = fn.__name__
    return wrapper


class Live:
    def __init__(self, get_parent=lambda: None, noise=lambda: None, toys_online=lambda: None, idle=lambda: True, llm=lambda: None,
                 clock=time.monotonic, wall=time.time, **tracker_kw):
        self.get_parent, self.idle, self.get_llm = get_parent, idle, llm
        self.enabled = config.METRICS_ON
        names = [t["name"] for t in config.TOYS.values()]
        kw = dict(idle_gap_s=config.METRICS_IDLE_GAP_S, max_s=config.METRICS_MAX_SESSION_S, min_s=config.METRICS_MIN_SESSION_S,
                  min_child_utts=config.METRICS_MIN_CHILD_UTTS)
        kw.update(tracker_kw)
        self.tracker = SessionTracker(toy_names=names, clock=clock, wall=wall, noise=noise, toys_online=toys_online,
                                      on_session=self._session_done, **kw)
        self.clock = clock
        self._play_start: dict = {}
        self._coach: dict = {}        # child id -> coaching state (cached copy of the encrypted one)
        self._pending_child = None    # an utterance waiting for its words (audio-mode models report them mid-turn)
        self.last_events: list = []   # what the last session changed: numbers only, for the dashboard/board

    # ---------------- who is playing
    def _store(self):
        p = self.get_parent()
        return (p, ProgressStore(p)) if p is not None and p.unlocked() else (None, None)

    @safe
    def sync(self):
        """Attach the session to the child marked 'Playing now' (only while the board is unlocked), else anonymous."""
        p = self.get_parent()
        child = p.bound_child() if p is not None and p.unlocked() else None
        cid = child["id"] if child else None
        self.tracker.set_subject(cid)
        if cid and cid not in self._coach:
            _, store = self._store()
            self._coach[cid] = store.load(cid)["coach"] if store else coaching.new_state()
        self.tracker.knobs = dict(self._coach[cid]["knobs"]) if cid and self._coach.get(cid, {}).get("enabled", True) else {}
        return cid

    def refresh(self, cid):
        """The parent changed a child's coaching settings: drop the cached copy so the next turn reloads it."""
        self._coach.pop(cid, None)
        self.sync()

    def _state(self):
        cid = self.tracker.subject
        return self._coach.get(cid) if cid else None

    def _session_done(self, summary, subject):
        if not subject:
            return
        p, store = self._store()
        if store is None:
            self.tracker.anon.append(summary)     # locked meanwhile: keep it anonymous, in RAM
            return
        try:
            made = store.add_session(subject, summary)
            self._coach[subject] = store.load(subject)["coach"]
            self.last_events = [{k: e[k] for k in ("kind", "knob", "frm", "to") if k in e} for e in made]
        except Exception:  # noqa: BLE001 — child deleted, board locked mid-write...
            log.debug("could not store the session summary", exc_info=True)
            self._coach.pop(subject, None)

    # ---------------- hooks called by the Director
    @safe
    def child_pending(self, u):
        if self.enabled:
            self.sync()
            self._pending_child = u

    @safe
    def child_text(self, text):
        """The words of the pending utterance (STT result or the model's HEARD line). Features computed, text dropped."""
        u, self._pending_child = self._pending_child, None
        if self.enabled and u is not None:
            self._utt(u, text)

    @safe
    def child_unresolved(self, status="ok"):
        """The model never reported words for the pending utterance: count its timing, with unknown text features.
        Not for a turn that ignored the sound as non-speech (that was not the child talking)."""
        u, self._pending_child = self._pending_child, None
        if self.enabled and u is not None and status == "ok":
            self._utt(u, None)

    def _utt(self, u, text):
        end = u.last_voiced_received if u.last_voiced_received is not None else self.clock()
        start = getattr(u, "start_mono", None) or end - (u.speech_ms or 1000) / 1000
        self.tracker.child_text(start, end, text)

    @safe
    def playback(self, toy, kind, when):
        if not self.enabled:
            return
        if kind == "PLAYING":
            self._play_start[toy] = when
        elif toy in self._play_start:
            self.tracker.audio(self._play_start.pop(toy), when)

    @safe
    def turn_open(self, initiated: bool):
        if self.enabled:
            self.sync()
            self.tracker.turn_open(self.clock(), initiated)

    @safe
    def toy_line(self, text):
        if self.enabled:
            self.tracker.toy_line(text)

    @safe
    def turn_close(self, status):
        if self.enabled:
            self.tracker.turn_close(self.clock(), status)

    @safe
    def barge(self):
        if self.enabled:
            self.tracker.barge()

    @safe
    def activation(self):
        if self.enabled:
            self.tracker.activation()

    @safe
    def tick(self):
        if self.enabled:
            self.tracker.tick()

    # ---------------- what the toys use
    def coaching_block(self) -> str:
        try:
            st = self._state() if self.enabled else None
            return coaching.block(st) if st else ""
        except Exception:  # noqa: BLE001
            return ""

    def idle_banter_s(self, base: float) -> float:
        """Idle-chatter wait: longer for a child who needs more time (and, in RAM only, after a run of unanswered cues)."""
        try:
            st = self._state()
            transient = coaching.transient_level(self.tracker.consec_unanswered) if self.enabled else 0
            if st is None:
                return base * coaching.patience_multiplier({"patience": 0}, transient) if self.enabled else base
            return base * coaching.patience_multiplier(st, transient)
        except Exception:  # noqa: BLE001
            return base

    # ---------------- views
    def dashboard(self) -> dict:
        """Anonymous live counters for the open dashboard on :8080: no child identity, no text."""
        try:
            d = self.tracker.live()
            d["enabled"] = self.enabled
            d["coaching_on_for_current"] = bool(self.coaching_block())
            return d
        except Exception:  # noqa: BLE001
            return {"enabled": self.enabled, "active": False, "result": None, "recent": []}
