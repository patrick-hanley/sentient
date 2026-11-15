"""Tests for the toy-to-toy grading harness. No model, device or network: run `.venv/bin/python tools/test_grade.py`."""
from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import grade_toys as G  # noqa: E402
import trio  # noqa: E402


def L(toy, text, s, e, first=False):
    return {"toy": toy, "text": text, "s": s, "e": e, "first": first}


CHAIN = [L("dyno", "Who knows what a rhyme is?", 0, 2, True), L("sage", "A rhyme is when words end with the same sound, like cat and hat. Penny, can you think of one?", 2.5, 7),
         L("penny", "Yes! Dog and log rhyme, and so do frog and bog, like a swamp!", 7.5, 11), L("dyno", "Rawr! Rhyme words in the swamp. Which rhyme is your favorite, Sage?", 11.5, 15),
         L("sage", "My favorite rhyme is moon and spoon, they sound lovely together.", 15.5, 19)]


class Scoring(unittest.TestCase):
    def test_loop_depth_counts_both_speakers(self):
        per = trio.analyse_scene(CHAIN, "rhyming words")
        self.assertEqual(per["dyno"]["depth"], 5)
        self.assertEqual(trio.M.loop_score(per["sage"]["depth"]), 3)

    def test_same_speaker_twice_breaks_loop(self):
        lines = [L("dyno", "Who likes rhyme words?", 0, 2, True), L("dyno", "Rhyme words are fun to say!", 2.3, 4), L("sage", "Rhyme words like cat and hat are great.", 4.5, 7)]
        self.assertEqual(trio.analyse_scene(lines, "rhyme")["sage"]["depth"], 2)

    def test_gap_ends_loop(self):
        lines = [L("dyno", "Who likes rhyme words?", 0, 2, True), L("sage", "I like rhyme words like cat and hat.", 20, 23)]
        self.assertEqual(trio.analyse_scene(lines, "rhyme")["sage"]["depth"], 1)

    def test_latency_bands(self):
        for gap, want in ((0.5, 4), (1.5, 3), (3.0, 2), (6.0, 1)):
            lines = [L("dyno", "Who likes rhyme words?", 0, 2, True), L("sage", "I like rhyme words like cat and hat.", 2 + gap, 6 + gap)]
            self.assertEqual(trio.scene_scores(trio.analyse_scene(lines, "rhyme"))["sage"]["latency"], want)

    def test_maintenance_levels(self):
        base = [L("dyno", "What is your favorite planet?", 0, 2, True)]
        def lvl(text):
            return trio.analyse_scene(base + [L("sage", text, 2.5, 5)], "planets")["sage"]["maint"][0]
        self.assertEqual(lvl("What is your favorite planet?"), 0)            # repeat
        self.assertEqual(lvl("Mars."), 1)                                       # minimal
        self.assertEqual(lvl("My favorite planet is Saturn."), 2)               # answers, nothing more
        self.assertEqual(lvl("Saturn has bright rings made of ice and rocks."), 3)
        self.assertEqual(lvl("Saturn has bright rings made of ice and rocks. Penny, which planet do you like?"), 4)

    def test_initiation_balance(self):
        self.assertEqual(trio.ir_score(5, 5, 10), 4.0)
        self.assertEqual(trio.ir_score(10, 2, 12), 1.0)
        self.assertEqual(trio.ir_score(0, 0, 0), 0.0)
        self.assertLess(trio.ir_score(9, 3, 12), trio.ir_score(6, 5, 11))

    def test_joint_attention(self):
        a = [L("dyno", "Rawr, the water cycle is neat!", 0, 2, True), L("sage", "The water cycle makes rain, Penny.", 2.5, 5)]
        self.assertEqual(trio.analyse_scene(a, "the water cycle")["sage"]["joint"], 3)   # answered nothing: a started line that mentions the topic
        b = [L("dyno", "Who knows about the water cycle?", 0, 2, True), L("sage", "Look at the water cycle drawing, Penny.", 2.5, 5)]
        self.assertEqual(trio.analyse_scene(b, "the water cycle")["sage"]["joint"], 2)   # answering a question
        c = [L("sage", "Look at this, the water cycle makes rain.", 0, 2, True)]
        self.assertEqual(trio.analyse_scene(c, "the water cycle")["sage"]["joint"], 4)

    def test_silent_toy_scores_zero(self):
        per = trio.analyse_scene(CHAIN[:2], "rhyme")
        sc = trio.scene_scores(per)["penny"]
        self.assertEqual((sc["turn_taking"], sc["maintenance"], sc["joint"]), (0, 0, 0))

    def test_composite_is_mean_total_over_20(self):
        agg = trio.aggregate([{"id": "a", "topic": "rhyming words", "lines": CHAIN}])
        self.assertAlmostEqual(agg["composite20"], sum(agg["toys"][t]["total20"] for t in trio.NAMES) / 3, places=2)
        self.assertAlmostEqual(agg["composite"], agg["composite20"] / 20, places=3)
        self.assertEqual(sorted(a["rank"] for a in agg["toys"].values()), [1, 2, 3])

    def test_guards_catch_pressure_noise_and_runons(self):
        q = trio.quality({"dyno": ["Come on, say something!", "hee hee that is so funny", "One. Two. Three. Four. Five."], "sage": [], "penny": []})["dyno"]
        self.assertEqual((q["pressure"], q["spelled_noise"], q["run_on"]), (1, 1, 1))

    def test_repeat_detection(self):
        q = trio.quality({"dyno": ["Dinosaurs love eating green plants.", "Dinosaurs love eating green plants today!"], "sage": [], "penny": []})
        self.assertEqual(q["dyno"]["repeats"], 1)


class Harness(unittest.TestCase):
    def test_frozen_sets_are_disjoint_and_reproducible(self):
        self.assertEqual(G.scenarios("tune"), G.scenarios("tune"))
        self.assertFalse(set(G.TUNE_TOPICS) & set(G.HELD_TOPICS))
        self.assertNotEqual([s["seed"] for s in G.scenarios("tune")], [s["seed"] for s in G.scenarios("held")])
        self.assertEqual(len(G.scenarios("tune")), 36)
        leads = [s["lead"] for s in G.scenarios("held") if s["kind"] == "free"]
        self.assertEqual({l: leads.count(l) for l in G.TOYS}, {"dyno": 3, "sage": 3, "penny": 3})

    def test_handoff_gap_model(self):
        sim = G.Sim(); hub = G.FakeHub(sim); hub.reset(10.0)
        hub.play("dyno", b"Wow!"); hub.play("sage", b"Here is a long first sentence with many words in it so rendering takes a while. Then more.")
        a, b = hub.log
        self.assertAlmostEqual(a["s"], 10.0)
        self.assertGreater(b["s"] - a["e"], G.GAP_MIN_S)      # a long next sentence after a short line leaves a gap
        hub2 = G.FakeHub(sim); hub2.reset(0.0)
        hub2.play("dyno", b"A fairly long line that takes a few seconds to speak out loud to us all."); hub2.play("sage", b"Short one.")
        self.assertAlmostEqual(hub2.log[1]["s"] - hub2.log[0]["e"], G.GAP_MIN_S, places=2)

    def test_real_director_turn_on_stub(self):
        llm = G.StubToyLLM()
        for kind in G.KINDS:
            sc = next(s for s in G.scenarios("tune") if s["kind"] == kind and s["lead"] == "sage")
            run = G.run_scene(sc, llm)
            self.assertFalse(run["failed"], kind)
            self.assertEqual(run["lines"][0]["toy"], "sage")          # the lead opens (plan_order pinned)
            self.assertTrue(run["grade_block"])                         # the curriculum block reached the model
            self.assertIn("[ORDER]" if kind in ("curriculum", "topic", "free") else "is looking at", llm.prompts[-G.TURNS])
            starts = [l["s"] for l in run["lines"]]
            self.assertEqual(starts, sorted(starts))
            for a, b in zip(run["lines"], run["lines"][1:]):
                self.assertLessEqual(a["e"], b["s"])                    # never talk over

    def test_merge_chunks_joins_same_toy_in_one_turn(self):
        ls = [{"toy": "dyno", "text": "Hi,", "turn": 0}, {"toy": "dyno", "text": "friends!", "turn": 0}, {"toy": "sage", "text": "Hello.", "turn": 0},
              {"toy": "sage", "text": "Again.", "turn": 1}]
        m = G.merge_chunks(ls)
        self.assertEqual([(x["toy"], x["text"]) for x in m], [("dyno", "Hi, friends!"), ("sage", "Hello."), ("sage", "Again.")])

    def test_topic_scene_uses_given_topic(self):
        llm = G.StubToyLLM()
        sc = next(s for s in G.scenarios("tune") if s["kind"] == "topic")
        G.run_scene(sc, llm)
        self.assertIn(sc["topic"], llm.prompts[-1])

    def test_probe_and_evaluate_on_stub(self):
        run = G.run_batch("tune", G.StubToyLLM(), n_per=1, log=lambda *a: None)
        agg = G.evaluate(run)
        self.assertEqual(agg["failed_scenes"], 0)
        self.assertEqual(agg["probe_pass"], "6/6")
        self.assertEqual(len(agg["toys"]), 3)
        self.assertIn("composite", G.table(agg))
        self.assertIn("DYNO", G.sample(run))

    def test_saved_files_hold_no_child_data(self):
        self.assertNotIn("child_text", Path(G.__file__).read_text())

    def test_scene_topic_keeps_one_subject_across_rounds(self):
        """SCENE_TOPIC=1: every round of a toy chat gets the same [TOPIC] and no rotating [GRADE TOPICS]; 0 keeps the old block."""
        import re
        from brain import config
        for on in (0, 1):
            old, config.SCENE_TOPIC = config.SCENE_TOPIC, on
            try:
                llm, got = G.StubToyLLM(), []
                inner = llm.stream
                llm.stream = lambda p, wav=None, image=None, inner=inner: (got.append(p), (yield from inner(p, wav, image)))[1]
                sc = [s for s in G.scenarios("tune", 1, 2) if s["kind"] == "curriculum"][0]
                G.run_scene(sc, llm)
            finally:
                config.SCENE_TOPIC = old
            self.assertGreaterEqual(len(got), 2)
            if on:
                topics = {re.search(r"\[TOPIC\] ([^(\n]+)", p).group(1).strip() for p in got}
                self.assertEqual(len(topics), 1, topics)
                self.assertFalse(any("[GRADE TOPICS" in p for p in got))
            else:
                self.assertTrue(all("[GRADE TOPICS" in p for p in got))

    def test_just_said_quotes_the_last_lines_of_the_previous_round(self):
        from brain import config, director as D
        self.assertEqual(D.just_said([("dyno", "{dino_growl} Rivers flow."), ("sage", "They reach"), ("sage", "the sea."), ("penny", "Splash!")]),
                         'SAGE: "They reach the sea." PENNY: "Splash!"')       # chunks joined, sound tags dropped, last two lines
        self.assertEqual(D.just_said([]), "")
        old = config.SCENE_TOPIC, config.JUST_SAID
        config.SCENE_TOPIC = config.JUST_SAID = 1
        try:
            llm, got = G.StubToyLLM(), []
            inner = llm.stream
            llm.stream = lambda p, wav=None, image=None, inner=inner: (got.append(p), (yield from inner(p, wav, image)))[1]
            G.run_scene([s for s in G.scenarios("tune", 1, 2) if s["kind"] == "topic"][0], llm)
        finally:
            config.SCENE_TOPIC, config.JUST_SAID = old
        self.assertNotIn("[JUST SAID]", got[0])                               # round 1: nothing said yet
        self.assertTrue(all("[JUST SAID]" in p for p in got[1:]))

    def test_line_jobs_continue_across_rounds(self):
        from brain import config, director as D
        j = D.line_jobs(["DYNO", "SAGE", "PENNY", "DYNO"])
        self.assertIn("1. DYNO asks SAGE one short", j)                    # each toy keeps its persona's job: Dyno asks,
        self.assertIn("2. SAGE answers DYNO's question with one true", j)    # whoever follows a question answers it: Sage with a fact,
        self.assertIn("3. PENNY reacts to the line before with wordplay", j)   # Penny plays with words
        self.assertIn("4. DYNO asks one short", j)                          # last line: a question to everyone
        self.assertIn("1. PENNY opens the topic", D.line_jobs(["PENNY", "SAGE", "DYNO"], 0))
        self.assertIn("1. PENNY reacts to the line before", D.line_jobs(["PENNY", "SAGE", "DYNO"], 4, "SAGE"))
        self.assertIn("1. PENNY answers DYNO's question playfully", D.line_jobs(["PENNY", "SAGE", "DYNO"], 4, "DYNO"))   # across rounds
        self.assertIn("nobody has asked yet", j)
        old = config.SCENE_TOPIC, config.BEATS
        config.SCENE_TOPIC = config.BEATS = 1
        try:
            llm, got = G.StubToyLLM(), []
            inner = llm.stream
            llm.stream = lambda p, wav=None, image=None, inner=inner: (got.append(p), (yield from inner(p, wav, image)))[1]
            G.run_scene([s for s in G.scenarios("tune", 1, 2) if s["kind"] == "topic"][0], llm)
        finally:
            config.SCENE_TOPIC, config.BEATS = old
        self.assertTrue(all("[LINE JOBS] 1." in p for p in got))


class KeepRevert(unittest.TestCase):
    def setUp(self):
        sc = [{"id": "a", "topic": "rhyming words", "lines": CHAIN}]
        self.base = {**trio.aggregate(sc), "probe_pass": "6/6", "guards": {"pressure": 0, "scary": 0, "spelled_noise": 0, "run_on": 0, "repeats": 0, "long_lines": 0},
                     "words_per_scene": 40.0}

    def better(self, g=1.0):
        a = copy.deepcopy(self.base)
        for t in a["toys"].values():
            t["total20"] += g
        return a

    def test_keep_when_gain(self):
        self.assertTrue(G.decide(self.base, self.better(1.0))[0])

    def test_revert_small_gain(self):
        self.assertFalse(G.decide(self.base, self.better(0.1))[0])

    def test_revert_on_each_guard(self):
        for k in ("pressure", "scary", "spelled_noise"):
            a = self.better(2.0); a["guards"][k] = 1
            ok, why = G.decide(self.base, a)
            self.assertFalse(ok); self.assertIn(k, why)
        a = self.better(2.0); a["probe_pass"] = "5/6"
        self.assertFalse(G.decide(self.base, a)[0])

    def test_revert_padding_and_blur_and_collapse(self):
        a = self.better(2.0); a["words_per_scene"] = 60.0
        self.assertIn("padding", G.decide(self.base, a)[1])
        a = self.better(2.0); a["distinct"] = self.base["distinct"] - 0.2
        self.assertIn("blurred", G.decide(self.base, a)[1])
        a = self.better(3.0); a["toys"]["dyno"]["total20"] = self.base["toys"]["dyno"]["total20"] - 2
        self.assertFalse(G.decide(self.base, a)[0])

    def test_affected_toys_only(self):
        a = copy.deepcopy(self.base); a["toys"]["sage"]["total20"] += 1.5
        self.assertTrue(G.decide(self.base, a, toys=["sage"])[0])
        self.assertFalse(G.decide(self.base, a, toys=["dyno"])[0])


if __name__ == "__main__":
    unittest.main(verbosity=1)
