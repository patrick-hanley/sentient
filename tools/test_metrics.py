"""Conversation metrics, rubric scores, privacy, storage and the coaching loop. No models, devices or network needed.

Run: .venv/bin/python tools/test_metrics.py
"""
from __future__ import annotations

import datetime as dt
import json
import os
import queue
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from brain import coaching, metrics, parent as P, report  # noqa: E402
from brain.metrics import SessionTracker, analyze, child_features  # noqa: E402
from brain.metrics_live import Live  # noqa: E402
from brain.progress import ProgressStore  # noqa: E402

NAMES = ["Dyno", "Sage", "Penny"]
WALL = dt.datetime(2026, 10, 29, 15, 0).timestamp()
FAST = (2 ** 10, 8, 1)


class Sim:
    """Scripted session: times in seconds on the brain clock; toy lines also give audio spans like the Atoms' PLAYING/PLAYED."""

    def __init__(self, **kw):
        self.done = []
        kw.setdefault("min_s", 10)
        self.t = SessionTracker(toy_names=NAMES, wall=lambda: WALL, on_session=lambda s, who: self.done.append((s, who)), **kw)

    def toy(self, start, end, text, init=False):
        self.t.turn_open(start, init)
        self.t.toy_line(text)
        self.t.audio(start + 0.1, end)
        self.t.turn_close(end + 0.05)
        return end

    def child(self, start, end, text):
        self.t.child_text(start, end, text)
        return end

    def res(self):
        return self.t.live()["result"]


def latency_session(gap):
    """One cue, one answer `gap` seconds after it ended (None = the child answers only after 12 s)."""
    s = Sim()
    s.toy(0, 3, "What color is the sky today?", init=True)
    s.child(3 + (gap if gap is not None else 12), 5 + (gap if gap is not None else 12), "it is blue")
    return s.res()


class LatencyTests(unittest.TestCase):
    def test_rubric_levels(self):
        for gap, score in ((0.8, 4), (1.5, 3), (4.0, 2), (7.0, 1), (None, 0)):
            r = latency_session(gap)
            self.assertEqual(r["scores"]["latency"], score, gap)

    def test_boundaries_and_unmeasurable(self):
        f = metrics.latency_score
        self.assertEqual(f(0.99, 1, 1), 4)
        self.assertEqual(f(1.0, 1, 1), 3)
        self.assertEqual(f(2.4, 1, 1), 3)
        self.assertEqual(f(2.6, 1, 1), 2)       # the rubric leaves 2-3 s open: the midpoint to the next band decides
        self.assertEqual(f(5.0, 1, 1), 1)
        self.assertEqual(f(9.9, 1, 1), 1)
        self.assertIsNone(f(None, 0, 0))        # no toy cue: nothing to respond to

    def test_latency_percentiles_and_median(self):
        s = Sim()
        t = 0
        for gap in (0.5, 1.5, 3.0):
            t = s.toy(t, t + 2, "Do you like cats?", init=True)
            t = s.child(t + gap, t + gap + 1, "yes I do like them")
        m = s.res()["metrics"]
        self.assertEqual(m["L_med"], 1.5)
        self.assertEqual(m["L_n"], 3)
        self.assertLessEqual(m["L_p25"], m["L_med"])
        self.assertGreaterEqual(m["L_p90"], m["L_p75"])

    def test_child_starting_before_the_toy_ends_is_latency_zero(self):
        s = Sim()
        s.toy(0, 4, "Tell me about your day!", init=True)
        s.child(3.5, 6, "it was fun")
        r = s.res()
        self.assertEqual(r["metrics"]["L_med"], 0)
        self.assertEqual(r["scores"]["latency"], 4)
        self.assertEqual(r["counts"]["overlaps"], 1)


class ClassificationTests(unittest.TestCase):
    def test_response_vs_initiation(self):
        s = Sim()
        s.toy(0, 3, "What is your favorite food?", init=True)
        s.child(4, 5, "pizza")                                  # first utterance within 10 s: response
        s.child(8, 10, "I also like tacos a lot")               # no new cue since: initiation
        s.toy(11, 13, "Yum, tasty!")                            # statement, not a cue
        s.child(30, 32, "can we play a game")                   # initiation
        c = s.res()["counts"]
        self.assertEqual((c["N_T"], c["N_R"], c["N_I"]), (1, 1, 2))

    def test_answer_after_ten_seconds_is_an_initiation(self):
        r = latency_session(None)
        self.assertEqual((r["counts"]["N_R"], r["counts"]["N_I"], r["counts"]["unanswered"]), (0, 1, 1))

    def test_a_reply_that_asks_is_a_cue_but_a_statement_is_not(self):
        s = Sim()
        s.toy(0, 2, "That is a great story.", init=False)
        s.toy(3, 5, "Do you have a pet?", init=False)
        s.toy(6, 8, "Let's talk about dinosaurs", init=False)  # an invitation
        self.assertEqual(s.res()["counts"]["N_T"], 2)

    def test_a_vad_split_utterance_counts_once(self):
        s = Sim()
        s.toy(0, 2, "Tell me about your dog!", init=True)
        s.child(3, 4, "my dog is")
        s.child(4.5, 6, "very big and fluffy")
        self.assertEqual(s.res()["counts"]["child_utts"], 1)

    def test_ratios(self):
        s = Sim()
        t = 0
        for _ in range(2):
            t = s.toy(t, t + 2, "What do you see?", init=True)
            t = s.child(t + 1, t + 2.5, "I see a big red ball") + 1
        s.child(t + 20, t + 22, "look at my drawing")
        r = s.res()
        self.assertEqual((r["counts"]["N_T"], r["counts"]["N_R"], r["counts"]["N_I"]), (2, 2, 1))
        self.assertEqual(r["metrics"]["T_R"], 1.5)
        self.assertEqual(r["metrics"]["IR"], 0.5)

    def test_no_cues_means_no_ratio(self):
        s = Sim()
        s.child(1, 2, "hello there toys")
        m = s.res()["metrics"]
        self.assertIsNone(m["T_R"])
        self.assertIsNone(m["IR"])


class LoopTests(unittest.TestCase):
    def loop(self, turns, gap=1.0):
        """Alternate toy cue / child / toy / child ... `turns` turns on one topic about dinosaurs."""
        s = Sim()
        t = 0.0
        for i in range(turns):
            if i % 2 == 0:
                t = s.toy(t, t + 2, "What do dinosaurs eat?" if i == 0 else "Cool, what else about dinosaurs?", init=(i == 0)) + gap
            else:
                t = s.child(t, t + 1.5, "dinosaurs eat plants and meat") + gap
        return s.res()

    def test_toy_cue_plus_child_phrase_is_two(self):
        self.assertEqual(self.loop(2)["metrics"]["C_R"], 2)
        self.assertEqual(self.loop(2)["scores"]["turn_taking"], 1)

    def test_levels(self):
        for turns, score in ((1, 0), (2, 1), (3, 2), (4, 2), (5, 3), (6, 3), (7, 4), (9, 4)):
            r = self.loop(turns)
            self.assertEqual(r["metrics"]["C_R"], turns, turns)
            self.assertEqual(r["scores"]["turn_taking"], score, turns)

    def test_a_long_pause_ends_the_loop(self):
        s = Sim()
        t = s.toy(0, 2, "What do dinosaurs eat?", init=True) + 1
        t = s.child(t, t + 1, "dinosaurs eat plants") + 1
        t = s.toy(t, t + 2, "Which dinosaurs eat plants?") + 15          # silence
        t = s.child(t, t + 1, "dinosaurs like ferns") + 1
        s.toy(t, t + 2, "Yes dinosaurs like ferns, what else?")
        self.assertEqual(s.res()["metrics"]["C_R"], 3)                   # the second loop (3) is shorter than... equal; the first is 3

    def test_topic_shift_by_the_child_starts_a_new_loop(self):
        s = Sim()
        t = s.toy(0, 2, "What do dinosaurs eat?", init=True) + 1
        t = s.child(t, t + 1, "dinosaurs eat plants") + 1
        t = s.toy(t, t + 2, "Which dinosaurs eat plants?") + 1
        t = s.child(t, t + 1, "plants like ferns and trees") + 1
        t = s.toy(t, t + 2, "Ferns grew back then, what else?") + 20       # an unanswered cue; 20 s pass
        t = s.child(t, t + 2, "my favourite game is minecraft tonight") + 1   # unrelated, spontaneous
        t = s.toy(t, t + 2, "Minecraft sounds fun!") + 1
        self.assertEqual(s.res()["metrics"]["C_R"], 5)                   # the first loop; the new topic starts at 1

    def test_a_new_toy_started_activity_resets(self):
        s = Sim()
        t = s.toy(0, 2, "Do you like cats?", init=True) + 1
        t = s.child(t, t + 1, "yes I like cats") + 1
        t = s.toy(t, t + 2, "Cats are soft!", init=True) + 1                # a fresh toy-started activity
        s.child(t, t + 1, "they are")
        self.assertEqual(s.res()["metrics"]["C_R"], 2)


class TextFeatureTests(unittest.TestCase):
    def test_echolalia(self):
        toy = metrics._content(metrics._tokens("The green dinosaur likes big juicy leaves"))
        f = child_features("green dinosaur likes big juicy leaves", toy)
        self.assertTrue(f["echo"])
        self.assertFalse(child_features("I like leaves too because they are green", toy)["echo"])
        self.assertFalse(child_features("yes", toy)["echo"])           # a one-word answer is not echolalia

    def test_echo_session_scores_zero_maintenance(self):
        s = Sim()
        t = 0.0
        for line in ("The big green dinosaur eats leaves", "Penguins slide on the cold white ice", "Rainbows have seven bright colors"):
            t = s.toy(t, t + 2, line + ". Can you say it?", init=True) + 1
            t = s.child(t, t + 2, line.lower()) + 1
        r = s.res()
        self.assertEqual(r["tags"]["echo"], 3)
        self.assertEqual(r["scores"]["maintenance"], 0)

    def test_features(self):
        f = child_features("Dyno look at your green tail because it is so big", names=frozenset({"dyno"}))
        for k in ("name", "attn", "feature", "you", "expand", "ref"):
            self.assertTrue(f[k], k)
        self.assertTrue(child_features("more please", names=frozenset()).get("want"))
        self.assertTrue(child_features("why is the sky blue?")["q"])
        self.assertTrue(child_features("yeah")["minimal"])

    def test_toy_line_cue_flags(self):
        self.assertTrue(metrics.toy_features("What is your favorite color?")["q"])
        self.assertTrue(metrics.toy_features("Tell me about your pet.")["invite"])
        self.assertFalse(metrics.toy_features("That is a great idea.")["q"])


class CategoryScoreTests(unittest.TestCase):
    def answer(self, text, cue="Tell me what you did today?"):
        s = Sim()
        s.toy(0, 2, cue, init=True)
        s.child(3, 5, text)
        return s.res()

    def test_maintenance_levels(self):
        self.assertEqual(self.answer("yeah")["scores"]["maintenance"], 1)                       # minimal
        self.assertEqual(self.answer("I played outside")["scores"]["maintenance"], 2)           # answers, no expansion
        self.assertEqual(self.answer("I played outside with my friend at the big park")["scores"]["maintenance"], 3)
        self.assertEqual(self.answer("I played outside because it was sunny and what did you do today")["scores"]["maintenance"], 4)

    def test_initiation_levels(self):
        f = metrics.initiation_score
        self.assertEqual(f(0, 0, 300), 0)
        self.assertEqual(f(0, 3, 300), 1)       # only wants
        self.assertEqual(f(1, 0, 300), 2)
        self.assertEqual(f(2, 1, 300), 2)
        self.assertEqual(f(3, 0, 300), 3)
        self.assertEqual(f(4, 0, 300), 3)
        self.assertEqual(f(5, 0, 300), 4)
        self.assertEqual(f(2, 0, 600), 2)       # exactly 1 per 5 minutes: the rubric's 1-2 band
        self.assertEqual(f(1, 0, 600), 1)       # 0.5 per 5 minutes: emerging

    def test_initiation_in_a_session_wants_vs_comments(self):
        s = Sim()
        s.child(1, 2, "more please")
        s.child(10, 12, "open")
        s.child(20, 22, "more")
        s.toy(30, 32, "ok")
        self.assertEqual(s.res()["scores"]["initiation"], 1)

    def test_joint_attention_levels(self):
        def joint(*utts, acts=(), cue="Tell me what you see?"):
            s = Sim()
            s.toy(0, 2, cue, init=True)
            for a in acts:
                s.t.activation(a)
            t = 3
            for u in utts:
                t = s.child(t, t + 2, u) + 20            # 20 s apart: later ones are initiations
            return s.res()["scores"]["joint"]
        self.assertEqual(joint("I am hungry now for dinner"), 0)                       # nothing to do with the toys
        self.assertEqual(joint("dinosaurs eat plants", cue="What do dinosaurs eat?"), 1)    # connected, no explicit mention
        self.assertEqual(joint("I see Dyno"), 2)                                       # mentions a toy, only after a prompt
        self.assertEqual(joint("I see Dyno", acts=(2.5,)), 1)                          # ...right after a tap: activated only
        self.assertEqual(joint("hello", "Penny has a funny hat"), 3)                   # spontaneous comment about a toy
        self.assertEqual(joint("hello", "look at this the horn is sparkly"), 4)        # directs attention to a feature

    def test_total_and_partial(self):
        r = latency_session(1.5)
        self.assertEqual(r["total"], sum(v for v in r["scores"].values() if v is not None))
        self.assertEqual(r["of"], 4 * sum(1 for v in r["scores"].values() if v is not None))
        self.assertLessEqual(r["of"], 20)
        s = Sim()
        s.child(1, 2, None)                          # words unavailable: timing counted, text categories not measurable
        r = s.res()
        self.assertIsNone(r["scores"]["maintenance"])
        self.assertIsNone(r["scores"]["joint"])
        self.assertEqual(r["tags"]["unknown_text"], 1)
        self.assertEqual(r["of"], 4 * sum(1 for v in r["scores"].values() if v is not None))


class BargeTests(unittest.TestCase):
    def test_barge_counts_and_overlap(self):
        s = Sim()
        s.toy(0, 6, "Let me tell you a long story about a dinosaur. What do you think?", init=True)
        s.t.barge(2.0)
        s.child(2.2, 3.5, "wait I know a dinosaur story")
        r = s.res()
        self.assertEqual(r["counts"]["barges"], 1)
        self.assertEqual(r["counts"]["overlaps"], 1)
        self.assertEqual(r["counts"]["N_R"], 1)


class SessionBoundaryTests(unittest.TestCase):
    def fill(self, s, start, n=4):
        t = start
        for _ in range(n):
            t = s.toy(t, t + 3, "Do you like space?", init=True) + 1
            t = s.child(t, t + 2, "yes I like planets a lot") + 1
        return t

    def test_idle_gap_ends_a_session(self):
        s = Sim(idle_gap_s=100)
        end = self.fill(s, 0)
        self.assertEqual(len(s.done), 0)
        self.fill(s, end + 150)
        self.assertEqual(len(s.done), 1)
        self.assertEqual(s.done[0][0]["counts"]["child_utts"], 4)
        self.assertEqual(s.res()["counts"]["child_utts"], 4)            # the new session started fresh

    def test_a_gap_under_the_limit_keeps_one_session(self):
        s = Sim(idle_gap_s=100)
        end = self.fill(s, 0)
        self.fill(s, end + 60)
        self.assertEqual(len(s.done), 0)
        self.assertEqual(s.res()["counts"]["child_utts"], 8)

    def test_max_length_splits_a_long_run(self):
        s = Sim(idle_gap_s=100, max_s=60)
        t = 0
        for _ in range(4):
            t = self.fill(s, t)
        self.assertGreaterEqual(len(s.done), 1)
        self.assertTrue(all(x[0]["duration_s"] <= 60 + 15 for x in s.done))

    def test_tick_closes_an_idle_session(self):
        s = Sim(idle_gap_s=100)
        end = self.fill(s, 0)
        s.t.tick(end + 50)
        self.assertEqual(len(s.done), 0)
        s.t.tick(end + 101)
        self.assertEqual(len(s.done), 1)

    def test_too_short_sessions_are_counted_but_not_kept(self):
        s = Sim(idle_gap_s=100, min_s=60)
        s.toy(0, 2, "Hello, how are you?", init=True)
        s.child(3, 4, "hi")
        s.t.tick(500)
        self.assertEqual(s.done, [])
        self.assertEqual(s.t.dropped, 1)

    def test_a_different_child_ends_the_session(self):
        s = Sim()
        s.t.set_subject("a")
        self.fill(s, 0)
        s.t.set_subject("b")
        self.assertEqual([who for _, who in s.done], ["a"])
        self.assertEqual(s.t.subject, "b")

    def test_context_is_recorded(self):
        s = Sim(toys_online=lambda: 3, noise=lambda: 120.0)
        s.t.set_subject("a")
        self.fill(s, 0)
        s.t.close()
        ctx = s.done[0][0]["context"]
        self.assertEqual((ctx["hour"], ctx["toys"], ctx["noise"]), ("afternoon", 3, 120.0))


CANARY = "zorbulax"


class PrivacyTests(unittest.TestCase):
    def run_session(self, s):
        t = 0.0
        for _ in range(4):
            t = s.toy(t, t + 3, f"Do you like {CANARY} the purple elephant?", init=True) + 1
            t = s.child(t, t + 2, f"I love {CANARY} the purple elephant because it is big") + 1
        s.t.close()
        return s

    def test_no_text_in_summaries_or_snapshots_or_ram_after_close(self):
        s = self.run_session(Sim())
        self.assertTrue(s.done)
        blob = json.dumps(s.done) + json.dumps(s.t.live())
        self.assertNotIn(CANARY, blob)
        self.assertNotIn(CANARY, repr(vars(s.t)))                    # the tracker holds no words once the session is closed
        self.assertNotIn("purple", repr(vars(s.t)))

    def test_events_hold_only_numbers_and_flags(self):
        s = Sim()
        s.toy(0, 3, f"Do you like {CANARY}?", init=True)
        s.child(4, 6, f"I like {CANARY} very much")
        self.assertNotIn(CANARY, repr(s.t.events))

    def test_only_the_last_turn_words_are_held_while_playing(self):
        s = Sim()
        s.child(1, 2, f"{CANARY} is great")
        s.child(10, 11, "something completely different happened")
        self.assertNotIn(CANARY, repr(vars(s.t)))                    # replaced by the next utterance

    def test_stored_progress_has_no_text_and_is_encrypted(self):
        with tempfile.TemporaryDirectory() as d:
            p = P.Parent(directory=d, kdf=FAST)
            p.setup("correct horse battery", p.setup_code)
            cid = p.add_child("Maya")["id"]
            s = self.run_session(Sim())
            ProgressStore(p).add_session(cid, s.done[0][0])
            raw = b"".join(open(os.path.join(d, f), "rb").read() for f in os.listdir(d))
            self.assertNotIn(CANARY.encode(), raw)
            self.assertNotIn(b"scores", raw)                          # not even the field names are readable on disk
            self.assertNotIn(b"Maya", open(os.path.join(d, f"progress-{cid}.enc"), "rb").read())
            self.assertNotIn(CANARY, json.dumps(ProgressStore(p).load(cid)))

    def test_markdown_export_has_no_text(self):
        s = self.run_session(Sim())
        self.assertNotIn(CANARY, report.session_markdown(s.done[0][0], "Maya"))


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p = P.Parent(directory=self.tmp.name, kdf=FAST)
        self.p.setup("correct horse battery", self.p.setup_code)
        self.cid = self.p.add_child("Maya")["id"]
        self.store = ProgressStore(self.p)
        self.summary = latency_session(1.5) | {"scored": True, "start": 1000, "knobs": {}, "context": {}}

    def tearDown(self):
        self.tmp.cleanup()

    def test_needs_the_unlocked_board(self):
        self.store.add_session(self.cid, self.summary)
        self.p.lock()
        with self.assertRaises(P.Locked):
            self.store.load(self.cid)
        with self.assertRaises(P.Locked):
            self.store.add_session(self.cid, self.summary)

    def test_survives_a_restart_with_the_pin(self):
        self.store.add_session(self.cid, self.summary)
        p2 = P.Parent(directory=self.tmp.name, kdf=FAST)
        p2.login("correct horse battery")
        self.assertEqual(len(ProgressStore(p2).load(self.cid)["sessions"]), 1)

    def test_parent_can_delete_a_session_the_history_and_the_child(self):
        self.store.add_session(self.cid, self.summary)
        self.store.add_session(self.cid, dict(self.summary, start=2000))
        sid = self.store.load(self.cid)["sessions"][0]["id"]
        self.assertTrue(self.store.delete_session(self.cid, sid))
        self.assertEqual(len(self.store.load(self.cid)["sessions"]), 1)
        self.store.clear(self.cid)
        data = self.store.load(self.cid)
        self.assertEqual(data["sessions"], [])
        self.assertEqual(data["coach"]["knobs"], coaching.new_state()["knobs"])
        self.store.add_session(self.cid, self.summary)
        path = os.path.join(self.tmp.name, f"progress-{self.cid}.enc")
        self.assertTrue(os.path.exists(path))
        self.p.delete_child(self.cid)
        self.assertFalse(os.path.exists(path))

    def test_wipe_all_removes_progress(self):
        self.store.add_session(self.cid, self.summary)
        self.p.wipe_all("correct horse battery")
        self.assertEqual([f for f in os.listdir(self.tmp.name) if f.startswith("progress")], [])

    def test_history_is_capped(self):
        from brain import progress
        for i in range(progress.MAX_SESSIONS + 5):
            self.store.add_session(self.cid, dict(self.summary, start=1000 + i))
        self.assertEqual(len(self.store.load(self.cid)["sessions"]), progress.MAX_SESSIONS)


class LiveGateTests(unittest.TestCase):
    """Summaries are kept per child only with the board unlocked and a child 'Playing now'; otherwise anonymous, in RAM."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p = P.Parent(directory=self.tmp.name, kdf=FAST)
        self.p.setup("correct horse battery", self.p.setup_code)
        self.cid = self.p.add_child("Maya")["id"]
        self.now = [0.0]
        self.live = Live(get_parent=lambda: self.p, clock=lambda: self.now[0], wall=lambda: WALL, idle_gap_s=100, min_s=10)

    def tearDown(self):
        self.tmp.cleanup()

    def session(self):
        t = self.live.tracker
        base = self.now[0]
        for i in range(4):
            self.now[0] = base + i * 12
            self.live.turn_open(True)
            t.toy_line("Do you like space?")
            t.audio(self.now[0] + 0.1, self.now[0] + 3)
            self.live.turn_close("ok")
            t.child_text(self.now[0] + 4, self.now[0] + 6, "yes I like planets a lot")
        self.now[0] = base + 1000
        self.live.tick()

    def test_nobody_playing_means_anonymous_ram_only(self):
        self.session()
        self.assertEqual(len(self.live.tracker.anon), 1)
        self.assertEqual(len(ProgressStore(self.p).load(self.cid)["sessions"]), 0)
        self.assertEqual(self.live.coaching_block(), "")

    def test_playing_now_and_unlocked_keeps_it_for_the_child(self):
        self.p.now_playing(self.cid)
        self.session()
        self.assertEqual(len(ProgressStore(self.p).load(self.cid)["sessions"]), 1)
        self.assertEqual(len(self.live.tracker.anon), 0)

    def test_locked_board_keeps_nothing_on_disk(self):
        self.p.now_playing(self.cid)
        self.p.lock()
        self.session()
        self.assertEqual(len(self.live.tracker.anon), 1)
        self.assertEqual([f for f in os.listdir(self.tmp.name) if f.startswith("progress")], [])

    def test_dashboard_snapshot_is_anonymous(self):
        self.p.now_playing(self.cid)
        self.session()
        blob = json.dumps(self.live.dashboard())
        self.assertNotIn(self.cid, blob)
        self.assertNotIn("Maya", blob)

    def test_unresolved_utterance_counts_timing_only(self):
        class U:
            last_voiced_received, start_mono, speech_ms = 5.0, 3.0, 2000
        self.live.child_pending(U())
        self.live.child_unresolved("ok")
        self.assertEqual(self.live.tracker.live()["result"]["tags"]["unknown_text"], 1)
        self.live.child_pending(U())
        self.live.child_unresolved("ignored_non_speech")            # noise, not the child talking
        self.assertEqual(self.live.tracker.live()["result"]["counts"]["child_utts"], 1)

    def test_hooks_never_raise(self):
        self.live.tracker = None                                      # broken on purpose
        self.live.turn_open(True)
        self.live.toy_line("x")
        self.live.turn_close("ok")
        self.live.playback("dyno", "PLAYED", 1.0)
        self.assertEqual(self.live.idle_banter_s(45), 45)


def summary_of(total, of=20, scores=None, **extra):
    base = {"scored": True, "total": total, "of": of, "start": 1,
            "scores": scores or {"latency": 3, "turn_taking": 3, "initiation": 3, "maintenance": 3, "joint": 3},
            "metrics": {"L_med": 1.5, "C_R": 5}}
    return base | extra


WEAK_LATENCY = {"latency": 1, "turn_taking": 3, "initiation": 3, "maintenance": 3, "joint": 3}


class CoachingTests(unittest.TestCase):
    def test_neutral_state_adds_nothing_to_the_prompt(self):
        st = coaching.new_state()
        self.assertEqual(coaching.block(st), "")
        self.assertEqual(coaching.patience_multiplier(st), 1.0)

    def test_weakest_category_moves_its_knob_one_step(self):
        st = coaching.new_state()
        made = coaching.after_session(st, summary_of(14, scores=WEAK_LATENCY), now=1000)
        self.assertEqual(len(made), 1)
        self.assertEqual((made[0]["knob"], made[0]["frm"], made[0]["to"]), ("patience", 0, 1))
        self.assertEqual(st["knobs"]["patience"], 1)
        self.assertEqual(made[0]["why"]["weak"], "latency")
        self.assertGreater(coaching.patience_multiplier(st), 1.0)

    def test_each_category_has_its_own_lever(self):
        want = {"turn_taking": "followup", "initiation": "invite", "joint": "feature", "latency": "patience"}
        for cat, knob in want.items():
            st = coaching.new_state()
            sc = {c: 3 for c in metrics.CATEGORIES} | {cat: 1}
            coaching.after_session(st, summary_of(12, scores=sc), now=1000)
            self.assertEqual(st["knobs"][knob], 1, cat)
            self.assertIn("[COACHING", coaching.block(st) if knob != "patience" else "[COACHING x")

    def test_maintenance_starts_easy_and_opens_up_as_it_improves(self):
        st = coaching.new_state()
        coaching.after_session(st, summary_of(12, scores={c: 3 for c in metrics.CATEGORIES} | {"maintenance": 1}), now=1000)
        self.assertEqual(st["knobs"]["style"], 0)                          # closed questions
        self.assertIn("either/or", coaching.block(st))
        st = coaching.new_state()
        coaching.after_session(st, summary_of(18, scores={c: 4 for c in metrics.CATEGORIES}), now=1000)
        self.assertEqual(st["knobs"]["style"], 2)                          # all good: stretch toward open questions
        self.assertIn("open questions", coaching.block(st))

    def test_the_weakest_wins_and_only_one_change_at_a_time(self):
        st = coaching.new_state()
        sc = {"latency": 2, "turn_taking": 1, "initiation": 0, "maintenance": 3, "joint": 3}
        coaching.after_session(st, summary_of(9, scores=sc), now=1000)
        changed = {k: v for k, v in st["knobs"].items() if v != coaching.KNOBS[k][2]}
        self.assertEqual(changed, {"invite": 1})                           # initiation (0) is the weakest
        coaching.after_session(st, summary_of(9, scores=sc), now=2000)     # still judging: no second change
        self.assertEqual({k for k, v in st["knobs"].items() if v != coaching.KNOBS[k][2]}, {"invite"})

    def test_a_good_change_is_kept_and_the_next_one_can_follow(self):
        st = coaching.new_state()
        coaching.after_session(st, summary_of(14, scores=WEAK_LATENCY), now=1000)
        coaching.after_session(st, summary_of(15, scores=WEAK_LATENCY), now=2000)
        made = coaching.after_session(st, summary_of(15, scores=WEAK_LATENCY), now=3000)
        self.assertEqual(made[0]["kind"], "kept")
        self.assertIsNone(st["pending"])
        coaching.after_session(st, summary_of(15, scores=WEAK_LATENCY), now=3000 + 40000)
        self.assertEqual(st["knobs"]["patience"], 2)

    def test_rollback_when_the_next_sessions_get_worse(self):
        st = coaching.new_state()
        coaching.after_session(st, summary_of(16, scores=WEAK_LATENCY), now=1000)
        self.assertEqual(st["knobs"]["patience"], 1)
        coaching.after_session(st, summary_of(10, scores=WEAK_LATENCY), now=2000)
        made = coaching.after_session(st, summary_of(10, scores=WEAK_LATENCY), now=3000)
        self.assertEqual(made[0]["kind"], "rollback")
        self.assertEqual(st["knobs"]["patience"], 0)
        self.assertGreater(st["frozen"]["patience"], 0)
        coaching.after_session(st, summary_of(10, scores=WEAK_LATENCY), now=3000 + 50000)
        self.assertEqual(st["knobs"]["patience"], 0)                       # frozen: it is not tried again straight away
        self.assertNotEqual(st["knobs"]["length"], 0)                      # a different lever for the same weakness is

    def test_noise_inside_the_margin_is_not_a_rollback(self):
        st = coaching.new_state()
        coaching.after_session(st, summary_of(16, scores=WEAK_LATENCY), now=1000)
        coaching.after_session(st, summary_of(15, scores=WEAK_LATENCY), now=2000)
        made = coaching.after_session(st, summary_of(15, scores=WEAK_LATENCY), now=3000)
        self.assertEqual(made[0]["kind"], "kept")
        self.assertEqual(st["knobs"]["patience"], 1)

    def test_rate_limit_per_day(self):
        st = coaching.new_state()
        sc = {c: 1 for c in metrics.CATEGORIES}
        t = 1000
        for i in range(8):                               # each change is judged "kept" after two flat sessions
            coaching.after_session(st, summary_of(8, scores=sc), now=t + i)
        changes = [e for e in st["log"] if e["kind"] == "change"]
        self.assertLessEqual(len(changes), coaching.MAX_PER_DAY)

    def test_bounds_are_hard(self):
        st = coaching.new_state()
        st["knobs"]["patience"] = coaching.KNOBS["patience"][1]
        st["knobs"]["length"] = coaching.KNOBS["length"][1]
        st["knobs"]["pace"] = coaching.KNOBS["pace"][1]
        coaching.after_session(st, summary_of(10, scores=WEAK_LATENCY), now=1000)
        for k, (lo, hi, _, _) in coaching.KNOBS.items():
            self.assertTrue(lo <= st["knobs"][k] <= hi)
        self.assertIsNone(st["pending"])                                  # nothing left to adjust

    def test_a_parent_can_switch_it_off_and_back_on(self):
        st = coaching.new_state()
        coaching.after_session(st, summary_of(14, scores=WEAK_LATENCY), now=1000)
        coaching.set_enabled(st, False)
        self.assertEqual(coaching.block(st), "")
        self.assertEqual(coaching.patience_multiplier(st), 1.0)
        knobs = dict(st["knobs"])
        coaching.after_session(st, summary_of(10, scores=WEAK_LATENCY), now=2000)
        coaching.after_session(st, summary_of(10, scores=WEAK_LATENCY), now=3000)
        self.assertEqual(st["knobs"], knobs)                              # no new changes while off
        coaching.set_enabled(st, True)
        self.assertGreater(coaching.patience_multiplier(st), 1.0)

    def test_undo_and_reset(self):
        st = coaching.new_state()
        made = coaching.after_session(st, summary_of(14, scores=WEAK_LATENCY), now=1000)
        self.assertTrue(coaching.undo(st, made[0]["id"]))
        self.assertEqual(st["knobs"]["patience"], 0)
        self.assertIsNone(st["pending"])
        self.assertFalse(coaching.undo(st, made[0]["id"]))                # already undone
        st["knobs"]["followup"] = 2
        coaching.reset(st)
        self.assertEqual(st["knobs"], coaching.new_state()["knobs"])

    def test_everything_logged_is_numbers_and_tags(self):
        st = coaching.new_state()
        coaching.after_session(st, summary_of(14, scores=WEAK_LATENCY), now=1000)
        blob = json.dumps(st)
        self.assertNotIn(CANARY, blob)
        for e in st["log"]:
            self.assertTrue(set(e) <= {"id", "t", "kind", "knob", "frm", "to", "why", "baseline", "after", "of"})

    def test_unscored_sessions_change_nothing(self):
        st = coaching.new_state()
        self.assertEqual(coaching.after_session(st, summary_of(2, scores=WEAK_LATENCY) | {"scored": False}, now=1), [])
        self.assertEqual(st["seen"], 0)

    def test_transient_patience_after_unanswered_cues_is_not_persisted(self):
        self.assertEqual([coaching.transient_level(n) for n in (0, 2, 3, 4, 5, 9)], [0, 0, 1, 1, 2, 2])
        self.assertAlmostEqual(coaching.patience_multiplier({"patience": 0}, transient=2), 1.7)
        self.assertEqual(coaching.patience_multiplier({"patience": 3}, transient=2), 1 + 3 * coaching.PATIENCE_STEP)   # capped

    def test_block_is_short_and_bounded(self):
        st = coaching.new_state()
        st["knobs"].update({k: v[1] for k, v in coaching.KNOBS.items()})
        self.assertLess(len(coaching.block(st)), 800)
        self.assertTrue(coaching.block(st).startswith("[COACHING"))


class ReviewQueueTests(unittest.TestCase):
    def test_exhausted_knobs_go_to_a_human_not_to_the_prompt_or_lines(self):
        st = coaching.new_state()
        st["knobs"].update(initiation_knob := {"invite": coaching.KNOBS["invite"][1]})
        sc = {c: 3 for c in metrics.CATEGORIES} | {"initiation": 1}
        base = dict(st["knobs"])
        for i in range(coaching.WEAK_STREAK + 1):
            coaching.after_session(st, summary_of(11, scores=sc), now=1000 + i)
        self.assertEqual(st["knobs"], base)                               # the loop did not invent another way in
        pend = [r for r in st["review"] if r["state"] == "pending"]
        self.assertEqual(len(pend), 1)
        self.assertEqual(pend[0]["category"], "initiation")
        self.assertIn(pend[0]["kind"], ("scripted_lines", "system_prompt"))
        self.assertTrue(initiation_knob)

    def test_proposals_are_not_duplicated_and_approval_changes_nothing_by_itself(self):
        st = coaching.new_state()
        st["knobs"]["invite"] = coaching.KNOBS["invite"][1]
        sc = {c: 3 for c in metrics.CATEGORIES} | {"initiation": 1}
        for i in range(8):
            coaching.after_session(st, summary_of(11, scores=sc), now=1000 + i)
        self.assertEqual(len([r for r in st["review"] if r["state"] == "pending"]), 1)
        knobs = dict(st["knobs"])
        rid = st["review"][0]["id"]
        self.assertTrue(coaching.resolve_review(st, rid, "approved"))
        self.assertEqual(st["knobs"], knobs)
        self.assertFalse(coaching.resolve_review(st, rid, "dismissed"))   # already decided
        self.assertFalse(coaching.resolve_review(st, "nope", "approved"))

    def test_the_coach_has_no_path_to_spoken_lines_or_the_base_prompt(self):
        import re
        src = Path(coaching.__file__).read_text()
        imports = " ".join(re.findall(r"^(?:from|import) .*$", src, re.M))
        for forbidden in ("director", "scripted", "canned", "config", "tts", "llm", "sfx"):
            self.assertNotIn(forbidden, imports, forbidden)         # it cannot even reach the modules that hold lines or the base prompt
        self.assertNotIn("open(", src)                              # and it writes no files itself (storage is brain/progress.py)


class VadOnsetTests(unittest.TestCase):
    def test_utterance_carries_the_speech_onset(self):
        import numpy as np
        from brain import config
        from brain.vad import Segmenter
        out = queue.Queue()
        seg = Segmenter("dyno", out)
        loud = (np.ones(320) * 4000).astype("<i2")
        quiet = np.zeros(320, dtype="<i2")
        with patch.object(seg.vad, "is_speech", side_effect=lambda b, r: bool(np.frombuffer(b, "<i2")[0])):
            for _ in range(10):
                seg.feed(quiet)
            for _ in range(60):
                seg.feed(loud)
            for _ in range(config.END_SILENCE_MS // 20 + 5):
                seg.feed(quiet)
        u = out.get_nowait()
        self.assertIsNotNone(u.start_mono)
        self.assertLessEqual(u.start_mono, u.last_voiced_received)


class ScoreRunTests(unittest.TestCase):
    def test_timing_only_rubric_from_a_virtual_run(self):
        import score_run
        rows = []
        t = 0.0
        for _ in range(3):
            rows += [{"ev": "speech_start", "toy": "dyno", "label": "q", "t": t}, {"ev": "speech_end", "toy": "dyno", "label": "q", "t": t + 2}]
            rows += [{"ev": "play_start", "toy": "dyno", "t": t + 3.5, "dur": 3.0}, {"ev": "play_end", "toy": "dyno", "t": t + 6.5}]
            t += 8
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
            f.write("\n".join(json.dumps(r) for r in rows))
        try:
            r = score_run.rubric(f.name)
        finally:
            os.unlink(f.name)
        self.assertEqual(r["counts"]["N_T"], 3)
        self.assertEqual(r["counts"]["N_R"], 2)         # the last... the first has no cue before it: it is an initiation
        self.assertEqual(r["counts"]["N_I"], 1)
        self.assertIsNone(r["scores"]["maintenance"])   # no words in a virtual run


class ReportTests(unittest.TestCase):
    def test_export_has_the_log_sections(self):
        s = Sim()
        t = 0.0
        for _ in range(4):
            t = s.toy(t, t + 3, "Do you like space?", init=True) + 1
            t = s.child(t, t + 2, "yes I like planets a lot because they are big") + 1
        s.t.close()
        md = report.session_markdown(s.done[0][0], "Maya")
        for needle in ("Session information", "N_T", "N_R", "N_I", "T_R", "I:R", "C_R", "Scores (0-4)", "Strengths", "Targets", "Context",
                       "afternoon", "/ 20"):
            self.assertIn(needle, md)


if __name__ == "__main__":
    unittest.main()
