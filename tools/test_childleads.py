"""The child leads (Nov 15): the child's subject comes first, questions about the parent's notes are answered, "stop" quiets the toys.
Fakes only (no model, no devices)."""
from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from brain import camera, canned, config  # noqa: E402
from brain.director import system_prompt  # noqa: E402
from test_vision import FakeHub, ISpyModel, Model, SpokenVoices, utt  # noqa: E402
from brain.director import Director  # noqa: E402
from brain.perception import Perceiver  # noqa: E402
from test_vision import FakeRec  # noqa: E402


def director(model, hub=None):
    hub = hub or FakeHub()
    voices = SpokenVoices()
    return Director(hub, voices, Perceiver(hub, FakeRec()), model, {}), hub, voices


class StopWordsTests(unittest.TestCase):
    YES = ["stop", "Stop talking!", "be quiet", "shh", "Okay stop", "Dyno, stop", "please stop", "can you stop", "that's enough", "quiet please",
           "hush", "toys stop it"]
    NO = ["the bus stop is near my house", "what is a stop sign", "I like when the music stops and we freeze, it's a game we play at school",
          "don't stop the story", "", "stopwatch"]

    def test_stop_commands(self):
        self.assertEqual([t for t in self.YES if not camera.wants_stop(t)], [])

    def test_not_stop_commands(self):
        self.assertEqual([t for t in self.NO if camera.wants_stop(t)], [])


class ChildLeadsTests(unittest.TestCase):
    def setUp(self):
        p = patch.object(config, "PLAY_FILLERS", False)
        p.start()
        self.addCleanup(p.stop)

    def test_the_prompt_puts_the_child_first(self):
        p = system_prompt()
        self.assertIn("THE CHILD LEADS", p)
        self.assertIn("answer from the notes like a friend who knows", p)
        self.assertIn("your whole reply is the one word STOP", p)
        self.assertNotIn("at most five words", p)                    # the old deflect-to-school rule is gone

    def test_audio_model_stop_plays_one_listening_line_and_quiets_the_toys(self):
        model = Model(["STOP\nHEARD: stop talking"])
        d, hub, voices = director(model)
        d._turn(utt=utt("dyno"))
        self.assertEqual(voices.said, [("dyno", canned.LISTENING["dyno"])])
        self.assertEqual(d.last_trace["status"], "ok")
        self.assertGreater(d._quiet_until, time.time() + config.STOP_QUIET_S - 5)
        d.last_activity = 0                                            # long silence: still no toy chat while quiet
        d._last_child_t = 0
        d.events.put = lambda ev: None
        called = []
        d._turn = lambda **k: called.append(k)
        d._maybe_event()
        self.assertEqual(called, [])

    def test_audio_model_that_ignores_stop_is_cut_when_heard_says_stop(self):
        model = Model(["DYNO: {dino_growl}\nSAGE: Hello there.\nHEARD: stop talking"])
        d, hub, voices = director(model)
        d._turn(utt=utt("dyno"))
        self.assertEqual(voices.said[-1], ("dyno", canned.LISTENING["dyno"]))
        self.assertGreater(d._quiet_until, time.time() + config.STOP_QUIET_S - 5)
        self.assertTrue(d.convlog.dump()["turns"][-1]["flags"]["stop"])

    def test_transcript_stop_needs_no_model_call(self):
        model = ISpyModel([], said=["Be quiet please"])
        d, hub, voices = director(model)
        d._turn(utt=utt("sage"))
        self.assertEqual(model.calls, [])
        self.assertEqual(voices.said, [("sage", canned.LISTENING["sage"])])

    def test_a_child_turn_gets_at_most_two_lines(self):
        model = ISpyModel(["DYNO: Pizza!\nSAGE: Pizza is round.\nPENNY: Cheesy circle!\nHEARD: x"], said=["What's my favorite food?"])
        d, hub, voices = director(model)
        d._turn(utt=utt("dyno"))
        self.assertEqual([w for w, _t in voices.said], ["dyno", "sage"])

    def test_a_child_turn_has_no_curriculum_block(self):
        model = ISpyModel(["SAGE: Your favorite food is pizza!"], said=["What is my favorite food?"])
        d, hub, voices = director(model)
        d._grade_topics = lambda: "[GRADE TOPICS: fractions]"
        d._turn(utt=utt("sage"))
        self.assertNotIn("[GRADE TOPICS", model.calls[0]["text"])

    def test_toy_chat_waits_after_the_child_spoke(self):
        d, hub, voices = director(Model([]))
        called = []
        d._turn = lambda **k: called.append(k)
        d.last_activity = 0
        d._last_child_t = time.time() - 30                            # the child spoke 30 s ago
        d._maybe_event()
        self.assertEqual(called, [])
        d._last_child_t = time.time() - config.IDLE_AFTER_CHILD_S - 1
        d._maybe_event()
        self.assertEqual(len(called), 1)


if __name__ == "__main__":
    unittest.main()
