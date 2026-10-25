"""Content-free turn timings. Overlapping stage durations must not be summed."""
from __future__ import annotations

from contextlib import contextmanager
import threading
import time


class TurnTrace:
    def __init__(self, origin=None, source="event"):
        self.origin = time.monotonic() if origin is None else origin
        self.source, self.status = source, "running"
        self.events, self.durations = {}, {}
        self.lock = threading.Lock()

    def mark(self, name, when=None, first=True):
        elapsed = max(0., ((time.monotonic() if when is None else when) - self.origin) * 1000)
        with self.lock:
            if not first or name not in self.events:
                self.events[name] = round(elapsed, 2)

    @contextmanager
    def span(self, name):
        started = time.monotonic()
        try:
            yield
        finally:
            with self.lock:
                self.durations[name] = self.durations.get(name, 0.) + (time.monotonic() - started) * 1000

    def finish(self, status):
        self.mark("turn_done_ms")
        with self.lock:
            self.status = status

    def snapshot(self):
        with self.lock:
            return {"source": self.source, "status": self.status,
                    "reference": {"speech": "last_voiced_frame_received", "event": "event_start"}.get(self.source, "turn_start"),
                    "milestones_ms": dict(self.events),
                    "stage_work_ms": {key: round(value, 2) for key, value in self.durations.items()},
                    "audio_onset_measured": False}
