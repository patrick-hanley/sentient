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


class StopTests(unittest.TestCase):
    def rows(self, cut, extra):
        r = [{"ev": "play_start", "toy": "dyno", "dur": 10.0, "t": 5.0},
             {"ev": "speech_start", "toy": "sage", "label": "say:Stop!", "expect": "stop", "t": 9.0},
             {"ev": "barge", "mode": "echo canceller", "t": 9.15},
             {"ev": "play_end", "toy": "dyno", "dur": 10.0, "cut": cut, "t": 9.2 if cut else 15.0},
             {"ev": "play_start", "toy": "sage", "dur": 1.2, "t": 16.0}, {"ev": "play_end", "toy": "sage", "dur": 1.2, "t": 17.2},
             {"ev": "clock_sync", "toy": "dyno", "err_ms": -0.4, "t": 30.0}]
        if extra:
            r += [{"ev": "play_start", "toy": "penny", "dur": 6.0, "t": 18.0}, {"ev": "play_end", "toy": "penny", "dur": 6.0, "t": 24.0}]
        return events(sorted(r, key=lambda e: e["t"]))

    def test_cut_and_quiet_is_ok(self):
        s = score_run.score(self.rows(True, False))["stop"]
        self.assertEqual((s["n"], s["ok"], s["cut_while_talking"]), (1, 1, "1/1"))
        self.assertEqual(s["silent_after_s"]["max"], 0.2)
        self.assertEqual(s["each"][0]["noticed_by"], "echo canceller")
        self.assertEqual(s["clock_sync_err_ms_max"], 0.4)

    def test_toy_that_keeps_talking_fails(self):
        self.assertEqual(score_run.score(self.rows(False, False))["stop"]["ok"], 0)

    def test_more_than_the_one_listening_line_fails(self):
        s = score_run.score(self.rows(True, True))["stop"]
        self.assertEqual((s["ok"], s["each"][0]["extra_toy_clips"]), (0, 1))


class StoryTests(unittest.TestCase):
    """Story mode (brain/story.py): the child reads aloud, the toys only add sounds."""

    def test_start_is_the_child_reading_not_asking_for_a_story(self):
        from brain import story
        for t in ("I'm going to read you a story.", "Can I read you my book?", "Story time!", "Listen to my story."):
            self.assertTrue(story.wants_story(t), t)
        for t in ("Can you tell me a story?", "Dyno, tell me a long story about a dragon.", "Read me a story please.", "I like stories."):
            self.assertFalse(story.wants_story(t), t)

    def test_the_end_only_as_its_own_sentence(self):
        from brain import story
        for t in ("The end.", "And they lived happily ever after. The end.", "I'm done reading.", "That's the end!"):
            self.assertTrue(story.ends(t), t)
        for t in ("They walked to the end of the road.", "At the end of the day the fox slept."):
            self.assertFalse(story.ends(t), t)

    def test_sound_fits_the_words(self):
        from brain import story
        for t, want in (("It was a dark night and the rain fell on the roof.", "rain"), ("Someone knocked on the door.", "knock"),
                        ("The dog barked at the cat.", "dog"), ("A little dog ran to the park.", "dog"),
                        ("The frog jumped into the pond.", "splash"), ("The big dinosaur roared.", "dino_roar"),
                        ("The dog did not bark.", None), ("She put on her shoes and went outside.", None),
                        ("Once upon a time there was a girl named Mia.", None)):
            self.assertEqual(story.pick(t), want, t)
        self.assertIsNone(story.pick("The dog barked.", skip={"dog"}))              # played a moment ago
        self.assertIsNone(story.pick("The rain fell.", available={"dog", "knock"}))  # no such recording

    def test_story_words_are_not_commands(self):
        from brain import story
        self.assertTrue(story.is_command("Stop!"))
        self.assertFalse(story.is_command('"Stop!" cried the wolf.'))
        self.assertTrue(story.asks_toy("Dyno, are you listening?", "dyno|dino"))
        self.assertFalse(story.asks_toy("Penny the penguin waddled home.", "penny"))

    def test_only_a_lone_tag_from_the_model_is_a_sound(self):
        from brain import story
        self.assertEqual(story.model_sound(["{owl}"]), "owl")
        self.assertIsNone(story.model_sound(["{owl} What a spooky night!"]))
        self.assertIsNone(story.model_sound(["{owl}"], available={"rain"}))

    def rows(self, sound="rain", at=14.2, talk=False):
        r = [{"ev": "speech_start", "toy": "sage", "label": "say:Once upon a time.", "expect": "quiet", "dur": 2.0, "t": 5.0},
             {"ev": "speech_start", "toy": "sage", "label": "say:The rain fell.", "expect": "sound:rain", "dur": 2.0, "t": 10.0},
             {"ev": "story_sound", "sound": sound, "toy": "dyno", "t": at},
             {"ev": "play_start", "toy": "dyno", "dur": 2.0, "t": at + .05}, {"ev": "play_end", "toy": "dyno", "dur": 2.0, "t": at + 2.05},
             {"ev": "speech_start", "toy": "sage", "label": "say:The end.", "expect": "end", "dur": 1.0, "t": 20.0},
             {"ev": "play_start", "toy": "sage", "dur": 2.5, "t": 23.0}, {"ev": "play_end", "toy": "sage", "dur": 2.5, "t": 25.5}]
        if talk:
            r += [{"ev": "play_start", "toy": "penny", "dur": 3.0, "t": 8.0}, {"ev": "play_end", "toy": "penny", "dur": 3.0, "t": 11.0}]
        return events(sorted(r, key=lambda e: e["t"]))

    def test_score_right_sound_and_no_words(self):
        s = score_run.score(self.rows())["story"]
        self.assertEqual((s["n"], s["ok"], s["right_sound"], s["false_sounds"], s["toy_spoke_while_reading"]), (3, 3, "1/1", 0, 0))
        self.assertEqual(s["sound_after_s"]["max"], 2.2)

    def test_score_wrong_sound_or_a_talking_toy_fails(self):
        s = score_run.score(self.rows(sound="dog"))["story"]
        self.assertEqual((s["ok"], s["right_sound"], s["false_sounds"]), (2, "0/1", 1))
        s = score_run.score(self.rows(talk=True))["story"]
        self.assertEqual((s["ok"], s["toy_spoke_while_reading"]), (2, 1))

    def test_score_sound_during_a_quiet_sentence_fails(self):
        s = score_run.score(self.rows(at=8.0))["story"]      # played after "Once upon a time", before the rain was read
        self.assertEqual((s["ok"], s["false_sounds"]), (1, 1))


class ClockSyncTests(unittest.TestCase):
    def run_sync(self, ppm, minutes=30):
        """Pings every 5 s for `minutes`; the Atom's crystal runs `ppm` off. Returns (new error, old best-ping-ever error) in ms."""
        rng = np.random.default_rng(3)
        a = Atom(mac="m", ip="1.1.1.1", toy="dyno")
        clock = lambda t: t * (1 + ppm * 1e-6) + 1234.5
        old_rtt, old_off = 9.9, None
        t = 100.0
        for _ in range(minutes * 12):
            for _ in range(4):
                up, down = .0015 + rng.exponential(.003), .0015 + rng.exponential(.003)
                a.add_sync(t, up + down, clock(t + up))
                if up + down < old_rtt:
                    old_rtt, old_off = up + down, clock(t + up) - (t + (up + down) / 2)
                t += .02
            t += 5
        true = clock(t) - t
        return abs(a.off(t) - true) * 1000, abs(old_off - true) * 1000

    def test_offset_follows_crystal_drift(self):
        new, old = self.run_sync(-30)
        self.assertLess(new, 1.0)        # within a millisecond after half an hour
        self.assertGreater(old, 20.0)    # the single best ping ever is stale by the drift

    def test_no_drift_still_accurate(self):
        self.assertLess(self.run_sync(0)[0], 1.0)

    def test_first_pings_give_an_offset_at_once(self):
        a = Atom(mac="m", ip="1.1.1.1", toy="dyno")
        a.add_sync(10.0, .004, 510.002)
        self.assertAlmostEqual(a.off(10.5), 500.0, places=3)


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
