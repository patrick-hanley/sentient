"""Floor control for half-duplex toys: one talker at a time, the child always wins.

States: idle, human_talking, agent_talking (one toy), handoff (just after a clip ended). Today this is a passive
monitor: AtomHub reports every agent clip, and any breach (two toys at once, a toy starting while the child is
talking) is counted rather than prevented, so a run can prove "no pile-up". The child's speech is reported by
callers that see it live (the test rig); the brain only sees whole utterances after the fact. Preempting a toy
mid-clip needs a STOP command in the firmware, which does not exist yet.
"""
from __future__ import annotations

import threading
import time

IDLE, HUMAN, AGENT, HANDOFF = "idle", "human_talking", "agent_talking", "handoff"
HANDOFF_S = 0.5      # HANDOFF decays to IDLE after this long without a follow-on clip


class FloorControl:
    def __init__(self, clock=time.monotonic):
        self.clock, self.lock = clock, threading.Lock()
        self.state, self.talker = IDLE, None
        self.active: set[str] = set()      # toys currently playing
        self.human = False
        self.ended_at = 0.0
        self.violations = {"pile_up": 0, "talk_over": 0}

    def human_start(self):
        with self.lock:
            self.human = True
            if self.active:
                self.violations["talk_over"] += 1   # the child spoke over a toy: they win, but record it
            self.state, self.talker = HUMAN, None

    def human_end(self):
        with self.lock:
            self.human = False
            self._after_clip()

    def agent_start(self, toy):
        with self.lock:
            if self.active - {toy}:
                self.violations["pile_up"] += 1
            if self.human:
                self.violations["talk_over"] += 1
            self.active.add(toy)
            self.state, self.talker = AGENT, toy

    def agent_end(self, toy):
        with self.lock:
            self.active.discard(toy)
            self.ended_at = self.clock()
            self._after_clip(handoff=True)

    def _after_clip(self, handoff=False):
        if self.human:
            self.state, self.talker = HUMAN, None
        elif self.active:
            self.state, self.talker = AGENT, next(iter(self.active))
        else:
            self.state, self.talker = (HANDOFF if handoff else IDLE), None

    def snapshot(self):
        with self.lock:
            if self.state == HANDOFF and self.clock() - self.ended_at > HANDOFF_S:
                self.state = IDLE
            return {"state": self.state, "talker": self.talker, **self.violations}
