"""Content-free turn timings. Overlapping stage durations must not be summed."""
from __future__ import annotations

import collections
from contextlib import contextmanager
import json
import subprocess
import threading
import time


class HostSampler:
    """Background Pi health and per-Atom link quality, merged into each turn record (timings only)."""

    def __init__(self, hub, period=5.0):
        self.hub, self.period = hub, period
        self._latest, self._cpu_prev = {}, None
        self.lock = threading.Lock()

    def start(self):
        threading.Thread(target=self._run, daemon=True, name="host-sampler").start()

    def latest(self):
        with self.lock:
            return dict(self._latest)

    @staticmethod
    def _read(path):
        try:
            with open(path) as f:
                return f.read()
        except OSError:
            return None

    def _cpu_pct(self):
        raw = self._read("/proc/stat")
        if not raw:
            return None
        v = [int(x) for x in raw.splitlines()[0].split()[1:]]
        total, idle = sum(v), v[3] + (v[4] if len(v) > 4 else 0)
        prev, self._cpu_prev = self._cpu_prev, (total, idle)
        if not prev or total == prev[0]:
            return None
        return round(100 * (1 - (idle - prev[1]) / (total - prev[0])), 1)

    def sample(self):
        s = {}
        sync = getattr(self.hub, "sync_clocks", None)
        if sync:
            sync()
        cpu = self._cpu_pct()
        if cpu is not None:
            s["cpu_pct"] = cpu
        temp = self._read("/sys/class/thermal/thermal_zone0/temp")
        if temp:
            s["temp_c"] = round(int(temp) / 1000, 1)
        try:
            out = subprocess.run(["vcgencmd", "get_throttled"], capture_output=True, text=True, timeout=1).stdout
            s["throttled"] = out.strip().split("=")[-1]
        except (OSError, subprocess.SubprocessError):
            pass
        atoms = {}
        for toy, a in list(self.hub.atoms.items()):
            info = {"pkts": a.pkts, "lost": a.lost, "sync_rtt_ms": round(a.sync_rtt * 1000, 1) if a.clock_off is not None else None}
            if not self.hub.talking:    # the Atom's httpd is busy during /play
                try:
                    with self.hub._http.open(f"http://{a.base}/status", timeout=1) as r:
                        info["rssi"] = json.loads(r.read()).get("rssi")
                except (OSError, ValueError):
                    pass
            atoms[toy] = info
        s["atoms"] = atoms
        return s

    def _run(self):
        while True:
            try:
                s = self.sample()
                with self.lock:
                    prev = self._latest.get("atoms", {})
                    for toy, info in s.get("atoms", {}).items():   # keep last RSSI while an Atom is busy
                        if "rssi" not in info and "rssi" in prev.get(toy, {}):
                            info["rssi"] = prev[toy]["rssi"]
                    self._latest = s
            except Exception:  # noqa: BLE001 — telemetry must never hurt the brain
                pass
            time.sleep(self.period)


class TurnLog:
    """Recent turn snapshots in memory plus an append-only JSONL file (timings only, no audio or text)."""

    def __init__(self, path=None, keep=200):
        self.path = path
        self.recent = collections.deque(maxlen=keep)
        self.lock = threading.Lock()
        self.count = 0

    def add(self, snap):
        with self.lock:
            self.count += 1
            snap = dict(snap, turn_id=self.count, wall=round(time.time(), 3))
            self.recent.append(snap)
            if self.path:
                try:
                    with open(self.path, "a") as f:
                        f.write(json.dumps(snap) + "\n")
                except OSError:
                    pass
        return snap

    def summary(self):
        """p50/p95 of each milestone and stage over recent ok turns."""
        with self.lock:
            turns = [t for t in self.recent if t.get("status") == "ok"]
        out = {}
        for group in ("milestones_ms", "stage_work_ms"):
            for name in sorted({k for t in turns for k in t.get(group, {})}):
                vals = sorted(t[group][name] for t in turns if name in t.get(group, {}))
                out[name] = {"n": len(vals), "p50": round(vals[len(vals) // 2], 1),
                             "p95": round(vals[min(len(vals) - 1, int(len(vals) * .95))], 1)}
        return {"turns": list(self.recent), "summary": out}


class TurnTrace:
    def __init__(self, origin=None, source="event", toy=None):
        self.origin = time.monotonic() if origin is None else origin
        self.toy = toy
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
            return {"source": self.source, "toy": self.toy, "status": self.status,
                    "reference": {"speech": "last_voiced_frame_received", "event": "event_start"}.get(self.source, "turn_start"),
                    "milestones_ms": dict(self.events),
                    "stage_work_ms": {key: round(value, 2) for key, value in self.durations.items()},
                    "audio_onset_measured": "atom_first_sample_ms" in self.events}
