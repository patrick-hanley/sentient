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


class NamesTests(unittest.TestCase):
    def test_who_is_addressed(self):
        cases = {"Penny, what's your favorite animal?": "penny", "hey dino": "dyno", "Sage can you help me": "sage",
                 "what do you all think": None, "I like Sage and Penny": None, "what is two plus two": None, "": None}
        self.assertEqual({t: camera.addressed(t) for t in cases}, cases)


class ChildLeadsTests(unittest.TestCase):
    def setUp(self):
        p = patch.object(config, "PLAY_FILLERS", False)
        p.start()
        self.addCleanup(p.stop)

    def test_the_prompt_puts_the_child_first(self):
        p = system_prompt()
        self.assertIn("THE CHILD LEADS", p)
        self.assertIn("answer from the notes like a friend who knows", p)
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

    def test_heard_first_only_the_named_toy_answers(self):
        model = Model(["HEARD: Penny, what's your favorite animal?\nDYNO: Dinosaurs!\nPENNY: Penguins, of course!\nSAGE: Owls."])
        d, hub, voices = director(model)
        d._turn(utt=utt("dyno"))
        self.assertEqual(voices.said, [("penny", "Penguins, of course!")])
        self.assertEqual(d.convlog.dump()["turns"][-1]["flags"].get("named"), "penny")

    def test_heard_first_stop_says_only_im_listening(self):
        model = Model(["HEARD: stop talking\nDYNO: Okay we will!\nSAGE: Shh."])
        d, hub, voices = director(model)
        d._turn(utt=utt("dyno"))
        self.assertEqual(voices.said, [("dyno", canned.LISTENING["dyno"])])
        self.assertGreater(d._quiet_until, time.time() + config.STOP_QUIET_S - 5)

    def test_transcript_named_toy_only(self):
        model = ISpyModel(["SAGE: Owls!\nPENNY: Penguins!"], said=["Sage, what is your favorite bird?"])
        d, hub, voices = director(model)
        d._turn(utt=utt("dyno"))
        self.assertIn("[TOYS HERE] SAGE ", model.calls[0]["text"])
        self.assertEqual(voices.said, [("sage", "Owls!")])

    def test_the_prompt_asks_for_heard_first(self):
        p = system_prompt()
        self.assertIn("The HEARD line comes FIRST", p)
        self.assertIn("ONLY that toy answers", p)

    def test_a_toy_that_sees_itself_says_thats_me(self):
        from brain.perception import SELF_LABEL, Thing
        model = Model(["DYNO: What a cute green dinosaur!"])
        d, hub, voices = director(model)
        d.on_seen("dyno", Thing("toy", SELF_LABEL, (0, 0, 10, 10)))
        ev = d.events.get_nowait()
        self.assertIn("ITSELF", ev["text"])
        d._turn(event=ev)
        self.assertEqual(voices.said, [("dyno", "Hey, that's me! What a cute green dinosaur!")])

    def test_shirt_color_asks_for_a_picture_also_with_cameras_always_on(self):
        self.assertTrue(camera.wants_look("Dyno, what color shirt am I wearing?"))
        model = Model(["HEARD: Dyno, what color shirt am I wearing?\nLOOK", "DYNO: Your shirt is blue!"])
        d, hub, voices = director(model)
        with patch.object(config, "CAPTURE_CONTINUOUS", True):
            self.assertIn("reply with exactly one word, LOOK", system_prompt())
            d._turn(utt=utt("dyno"))
        self.assertEqual(hub.captures, [("dyno", True)])
        self.assertTrue(model.calls[1]["image_exists"])
        self.assertEqual(voices.said, [("dyno", "Your shirt is blue!")])

    def test_who_do_you_see_takes_a_picture_with_the_named_toys_camera(self):
        model = Model(["HEARD: Penny, who do you see?\nPENNY: I see you!", "PENNY: I see Dyno, my green dinosaur friend!"])
        d, hub, voices = director(model)
        with patch.object(config, "CAPTURE_CONTINUOUS", True):
            d._turn(utt=utt("dyno"))                                   # Dyno's mic heard it, Penny was asked
        self.assertEqual(hub.captures, [("penny", True)])
        self.assertIn("DYNO is a little green dinosaur plush", model.calls[1]["text"])
        self.assertTrue(model.calls[1]["image_exists"])
        self.assertEqual(" ".join(t for w, t in voices.said if w == "penny"), "I see Dyno, my green dinosaur friend!")   # from the picture only
        self.assertEqual({w for w, _t in voices.said}, {"penny"})

    def test_an_event_turn_never_takes_a_heard_line_as_the_child(self):
        model = Model(["HEARD: What color shirt?\nDYNO: Hello!"])
        d, hub, voices = director(model)
        d._turn(event="Nobody has talked for a while.")
        self.assertEqual(d.last_heard, "")
        self.assertEqual(d.convlog.dump()["turns"][-1]["heard"], "")

    def test_no_greeting_cuts_into_a_conversation(self):
        from brain.perception import Thing
        d, hub, voices = director(Model([]))
        d._last_child_t = time.time() - 10
        d.on_seen("penny", Thing("pet", "a dog", (0, 0, 1, 1)))
        self.assertTrue(d.events.empty())
        d._last_child_t = 0
        d.on_seen("penny", Thing("pet", "a dog", (0, 0, 1, 1)))
        self.assertFalse(d.events.empty())

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


class EarlyStopTests(unittest.TestCase):
    """Nov 15 crash: reading stopped mid-answer ("who do you see?" forced look), the next message went out while the engine
    still generated, and the brain died (SEGV/SIGILL). An early stop must cancel and drain before the lock is let go."""

    def test_an_early_stop_cancels_and_drains_the_engine(self):
        from brain.llm import LiteRTBackend
        log = []

        class Conv:
            def send_message_async(self, msg):
                def gen():
                    for i in range(5):
                        if "cancel" in log:
                            log.append("drained")
                            return
                        log.append(f"chunk{i}")
                        yield {"content": [{"type": "text", "text": f"w{i} "}]}
                return gen()

            def cancel_process(self):
                log.append("cancel")

        b = LiteRTBackend.__new__(LiteRTBackend)
        b.conv, b.turns, b.lm = Conv(), 0, None
        b.new_conversation = lambda: log.append("new")
        s = b.stream("hi")
        next(s)
        s.close()
        self.assertEqual(log, ["chunk0", "cancel", "drained", "new"])
        self.assertTrue(LiteRTBackend._lock.acquire(blocking=False))   # released
        LiteRTBackend._lock.release()
        log.clear()
        self.assertEqual(b.ask("hi").split(), ["w0", "w1", "w2", "w3", "w4"])   # a full read never cancels
        self.assertNotIn("cancel", log)


class PetTests(unittest.TestCase):
    """Nov 15: the detector called the parent "a cat" and the toys greeted "cat" by name."""

    def perceiver(self, objs, faces=()):
        import numpy as np
        from brain import teach
        from brain.perception import Recognizer
        p = Recognizer.__new__(Recognizer)
        p.gallery = lambda: teach.EMPTY
        p.faces = lambda img: [(b, np.zeros(4), 0.9) for b in faces]
        p.who = lambda feat: (None, 0.0)
        p._tags = lambda img: ([], None)
        p.objects = lambda img: objs
        p.which_pet = lambda cls, vec: None
        p.embed = lambda img, box: None
        return p

    def test_a_cat_over_a_person_or_a_face_is_not_a_pet(self):
        img = None
        self.assertEqual(self.perceiver([("cat", (0, 0, 100, 200), 0.9), ("person", (5, 0, 95, 200), 0.8)]).analyze(img), [])
        things = self.perceiver([("cat", (0, 0, 100, 200), 0.9)], faces=[(30, 10, 30, 30)]).analyze(img)
        self.assertEqual([t.label for t in things], ["a person"])

    def test_a_weak_cat_is_dropped_and_a_clear_one_kept(self):
        self.assertEqual(self.perceiver([("cat", (0, 0, 50, 50), 0.45)]).analyze(None), [])
        self.assertEqual([t.label for t in self.perceiver([("cat", (0, 0, 50, 50), 0.8)]).analyze(None)], ["a cat"])

    def test_an_unknown_person_is_greeted_without_a_name(self):
        from brain.perception import Thing
        d, hub, voices = director(Model([]))
        d.on_seen("penny", Thing("person", "a person", (0, 0, 1, 1)))
        ev = d.events.get_nowait()
        self.assertIn("without guessing a name", ev)
        self.assertNotIn("by name", ev)
        d.on_seen("penny", Thing("person", "dad", (0, 0, 1, 1)))
        self.assertIn("greets dad warmly by name", d.events.get_nowait())


if __name__ == "__main__":
    unittest.main()
