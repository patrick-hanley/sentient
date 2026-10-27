"""Tests for the measurement tooling: scoring, floor control, packet-loss counting, debug recorder, judge maths.
Run: python tools/test_harness.py"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
from brain import debugrec
from brain.atoms import Atom, AtomHub, ulaw_encode
from brain.floor import FloorControl
import judge
import score_run
import virtual_atoms


def events(rows):
    d = tempfile.mkdtemp()
    p = Path(d) / "run.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in rows))
    return p


class ScoreTests(unittest.TestCase):
    def test_gaps_overlap_and_talk_over(self):
        p = events([
            {"ev": "speech_start", "toy": "dyno", "label": "say:hi", "t": 0},
            {"ev": "speech_end", "toy": "dyno", "label": "say:hi", "t": 1.0},
            {"ev": "play_start", "toy": "dyno", "dur": 0.5, "t": 2.0}, {"ev": "play_end", "toy": "dyno", "dur": 0.5, "t": 2.5},
            {"ev": "play_start", "toy": "dyno", "dur": 3.0, "t": 5.0}, {"ev": "play_end", "toy": "dyno", "dur": 3.0, "t": 8.0},
            {"ev": "play_start", "toy": "sage", "dur": 2.0, "t": 7.0}, {"ev": "play_end", "toy": "sage", "dur": 2.0, "t": 9.0},
        ])
        r = score_run.score(p)
        self.assertEqual(r["first_audio_s"]["p50"], 1.0)
        self.assertEqual(r["first_real_reply_s"]["p50"], 4.0)
        self.assertEqual(r["overlaps"], 1)
        self.assertEqual(r["dead_air_gaps"], 0)        # the 2.5 s gap is under the 3 s dead-air limit
        self.assertAlmostEqual(sum(r["talk_share"].values()), 1.0, places=1)

    def test_simultaneous_children_count_as_one_utterance(self):
        rows = []
        for i, toy in enumerate(("dyno", "sage", "penny")):
            rows += [{"ev": "speech_start", "toy": toy, "label": "say:x", "t": 0.1 * i},
                     {"ev": "speech_end", "toy": toy, "label": "say:x", "t": 1.0 + 0.1 * i}]
        self.assertEqual(score_run.score(events(rows))["human_utterances"], 1)


class FloorTests(unittest.TestCase):
    def test_pile_up_and_talk_over_are_counted(self):
        f = FloorControl()
        f.agent_start("dyno")
        f.agent_start("sage")
        self.assertEqual(f.snapshot()["pile_up"], 1)
        f.human_start()
        self.assertEqual(f.snapshot()["talk_over"], 1)
        f.agent_end("dyno")
        f.agent_end("sage")
        f.human_end()
        self.assertEqual(f.snapshot()["state"], "idle")

    def test_returns_to_idle_no_deadlock(self):
        t = [0.0]
        f = FloorControl(clock=lambda: t[0])
        f.agent_start("dyno")
        f.agent_end("dyno")
        self.assertEqual(f.snapshot()["state"], "handoff")
        t[0] = 1.0
        self.assertEqual(f.snapshot()["state"], "idle")


class HubTests(unittest.TestCase):
    def hub(self):
        h = object.__new__(AtomHub)
        h.atoms, h.by_ip, h.by_addr, h.force_mute, h.mute_until = {}, {}, {}, False, 0.0
        h.got = []
        h.on_audio = lambda toy, pcm: h.got.append(toy)
        return h

    def packet(self, seq):
        return b"M" + seq.to_bytes(2, "little") + np.zeros(320, "<i2").tobytes()

    def test_sequence_gaps_count_loss_but_resync_does_not(self):
        h = self.hub()
        a = h.by_ip["10.0.0.5"] = Atom("m", "10.0.0.5", "dyno")
        for seq in (1, 2, 5, 6, 400):      # 2 missing, then a resync jump
            h._handle(self.packet(seq), "10.0.0.5")
        self.assertEqual(a.lost, 2)

    def test_virtual_atoms_sharing_an_ip_route_by_udp_port(self):
        h = self.hub()
        a = h.by_addr[("127.0.0.1", 111)] = Atom("m1", "127.0.0.1", "dyno", hport=8001)
        b = h.by_addr[("127.0.0.1", 222)] = Atom("m2", "127.0.0.1", "sage", hport=8002)
        h._handle(self.packet(1), "127.0.0.1", 222)
        self.assertEqual(h.got, ["sage"])
        self.assertEqual((a.pkts, b.pkts), (0, 1))
        self.assertEqual(b.base, "127.0.0.1:8002")


class ClockTests(unittest.TestCase):
    def test_syncr_recovers_offset_and_playing_maps_to_brain_time(self):
        import time
        h = HubTests().hub()
        a = h.by_ip["10.0.0.5"] = Atom("m", "10.0.0.5", "dyno")
        got = []
        h.on_playback = lambda toy, kind, when: got.append((kind, when))
        sent = time.monotonic()
        a.sync_sent[b"7"] = sent
        atom_clock = sent + 0.002 + 5000.0          # Atom replies 2 ms later, its clock is 5000 s ahead
        h._handle(b"SYNCR 7 %d" % int(atom_clock * 1e6), "10.0.0.5")
        self.assertAlmostEqual(a.clock_off, 5000.0, delta=0.01)
        h._handle(b"PLAYING %d" % int((sent + 3.0 + 5000.0) * 1e6), "10.0.0.5")
        self.assertEqual(got[0][0], "PLAYING")
        self.assertAlmostEqual(got[0][1], sent + 3.0, delta=0.01)


class MiscTests(unittest.TestCase):
    def test_ulaw_roundtrip_is_close(self):
        x = (np.sin(np.arange(800) / 20) * 8000).astype(np.int16)
        y = virtual_atoms.ulaw_decode(ulaw_encode(x))
        self.assertLess(float(np.abs(x.astype(int) - y).max()), 400)

    def test_debug_recorder_is_off_by_default_and_cleans_up_when_on(self):
        os.environ.pop("SENTIENT_DEBUG_RECORD", None)
        self.assertIsNone(debugrec.save("in", "dyno", b"\0\0" * 100))
        os.environ["SENTIENT_DEBUG_RECORD"] = "1"
        try:
            path = debugrec.save("in", "dyno", b"\0\0" * 100)
            self.assertTrue(os.path.exists(path))
            self.assertTrue(path.startswith(tempfile.gettempdir()) or "sentient-debug-audio" in path)
        finally:
            os.environ.pop("SENTIENT_DEBUG_RECORD")

    def test_judge_agreement(self):
        j = {"a": {"coherence": 4, "on_topic": 5}}
        h = {"a": {"coherence": 5, "on_topic": 2}}
        self.assertEqual(judge.agreement(j, h), {"pairs": 2, "within_tol": 0.5, "mean_abs_err": 2.0})


if __name__ == "__main__":
    unittest.main()
