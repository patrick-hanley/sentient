"""Who is talking (Nov 15): voice prints stored with the person's face, learned safely, "who am I?" answered from them.
Fakes only (no speaker model, no devices)."""
from __future__ import annotations

import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from brain import camera, config, teach, voiceid  # noqa: E402
from brain.director import Director  # noqa: E402
from brain.perception import Perceiver, Thing, View  # noqa: E402
from test_vision import FakeHub, FakeRec, Model, SpokenVoices, make_parent, utt  # noqa: E402


def v(seed, n=512):
    x = np.random.RandomState(seed).randn(n).astype(np.float32)
    return x / np.linalg.norm(x)


def near(base, seed, noise=0.2):
    w = base + noise * np.random.RandomState(seed + int(abs(float(base[0])) * 1e6) % 100000).randn(len(base)).astype(np.float32) / np.sqrt(len(base)) * 3
    return w / np.linalg.norm(w)


DAD, KID = v(1), v(2)


class FakeVoice:
    """Hands out the next print for each utterance."""
    def __init__(self, prints):
        self.prints = list(prints)

    def __bool__(self):
        return True

    def embed(self, pcm):
        return self.prints.pop(0) if self.prints else None


class MatchTests(unittest.TestCase):
    def test_prints_of_one_voice_agree_and_two_voices_do_not(self):
        self.assertTrue(voiceid.agrees([near(DAD, 1)], near(DAD, 2)))
        self.assertFalse(voiceid.agrees([near(DAD, 1)], near(KID, 2)))

    def test_match_needs_enough_prints_and_a_margin(self):
        voices = [("e1", "dad", "parent", [near(DAD, i) for i in range(2)])]
        self.assertIsNone(voiceid.match(voices, near(DAD, 9)))          # 2 prints: not claimed yet
        voices = [("e1", "dad", "parent", [near(DAD, i) for i in range(4)]),
                  ("e2", "Ana", "child", [near(KID, i) for i in range(4)])]
        self.assertEqual(voiceid.match(voices, near(DAD, 9))[:2], ("e1", "dad"))
        self.assertEqual(voiceid.match(voices, near(KID, 9))[:2], ("e2", "Ana"))
        self.assertIsNone(voiceid.match(voices, v(77)))                  # a stranger stays unknown

    def test_introductions(self):
        cases = {"I'm dad": "dad", "Hi Penny, it's Grandma here": "grandma", "my name is Ana.": "ana", "This is mom!": "mom",
                 "I am hungry": "hungry", "what is that": None, "": None}
        self.assertEqual({t: voiceid.introduced(t) for t in cases}, cases)

    def test_who_am_i_words(self):
        for t in ["Penny, who am I?", "PENNY, WHO AM I", "do you know me", "what's my name", "who is talking"]:
            self.assertTrue(camera.wants_whoami(t), t)
        for t in ["who is that", "what do you see", "who are you", "I am happy"]:
            self.assertFalse(camera.wants_whoami(t), t)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self._d = tempfile.TemporaryDirectory()
        self.p = make_parent(self._d.name)
        self.store = teach.TeachStore(self.p)
        self.dad = self.store.add("person", "dad", [v(5, 128)], "sface", True, role="parent")["id"]

    def tearDown(self):
        self._d.cleanup()

    def test_voice_lives_in_the_persons_entry_encrypted_and_goes_with_it(self):
        self.store.add_voice(self.dad, near(DAD, 1))
        self.assertEqual(self.store.list()[0]["voices"], 1)
        self.assertEqual(len(self.store.gallery().voices), 1)
        raw = Path(self._d.name, teach.FILE).read_bytes()
        self.assertNotIn(f"{float(near(DAD, 1)[0]):.5f}".encode(), raw)
        self.store.forget_voice(self.dad)
        self.assertEqual(self.store.list()[0]["voices"], 0)
        self.store.add_voice(self.dad, near(DAD, 1))
        self.store.delete(self.dad)
        self.assertEqual(self.store.gallery().voices, [])

    def test_learn_voice_button_takes_the_next_four(self):
        self.store.listen_for_voice(self.dad, n=4, secs=60)
        self.assertEqual([self.store.take_pending_voice() for _ in range(5)], [self.dad] * 4 + [None])

    def test_nothing_while_locked(self):
        self.p.lock() if hasattr(self.p, "lock") else setattr(self.p, "_dek", None)
        self.assertEqual(self.store.gallery().voices, [])


def director(prints, model=None):
    d_ = tempfile.TemporaryDirectory()
    p = make_parent(d_.name)
    hub = FakeHub()
    rec = FakeRec()
    p.teacher = teach.Teacher(teach.TeachStore(p), rec, hub)
    d = Director(hub, SpokenVoices(), Perceiver(hub, rec), model or Model([]), {})
    d.parent, d.voiceid, d._tmpd = p, FakeVoice(prints), d_
    return d, p.teacher.store


def sees(d, toy, label, kind="person"):
    t = Thing(kind, label, (0, 0, 10, 10))
    d.eyes.views[toy] = View(toy, time.time(), True, [t], t, b"x")


class LearningTests(unittest.TestCase):
    def setUp(self):
        p = patch.object(config, "PLAY_FILLERS", False)
        p.start()
        self.addCleanup(p.stop)

    def run_voice(self, d, toy="penny"):
        vox = d._start_voice(utt(toy), toy)
        vox["done"].wait(2)
        time.sleep(0.05)
        return vox

    def test_auto_learning_needs_three_alike_prints_while_only_dad_is_in_view(self):
        d, store = director([near(KID, 1), near(DAD, 1), near(DAD, 2), near(DAD, 3)])
        dad = store.add("person", "dad", [v(5, 128)], "sface", True)["id"]
        sees(d, "penny", "dad")
        for i in range(4):
            d._vox_t.clear()
            self.run_voice(d)
        prints = store.voice_prints(dad)
        self.assertEqual(len(prints), 3)                                  # the child's print was left out
        self.assertTrue(all(voiceid.agrees([DAD], p_) for p_ in prints))

    def test_two_faces_or_a_stranger_teach_nothing(self):
        d, store = director([near(DAD, i) for i in range(6)])
        dad = store.add("person", "dad", [v(5, 128)], "sface", True)["id"]
        two = [Thing("person", "dad", (0, 0, 9, 9)), Thing("child", "the child", (20, 0, 9, 9))]
        d.eyes.views["penny"] = View("penny", time.time(), True, two, two[0], b"x")
        for _ in range(3):
            d._vox_t.clear()
            self.run_voice(d)
        sees(d, "penny", "a person")
        for _ in range(3):
            d._vox_t.clear()
            self.run_voice(d)
        self.assertEqual(store.voice_prints(dad), [])

    def test_saying_im_dad_teaches_dads_voice(self):
        d, store = director([near(DAD, 1)])
        dad = store.add("person", "dad", [v(5, 128)], "sface", True)["id"]
        vox = self.run_voice(d)
        tl = {"flags": {}}
        d._learn_intro(vox, "Hi Penny, it's dad!", tl)
        self.assertEqual(len(store.voice_prints(dad)), 1)
        self.assertEqual(tl["flags"]["voice_learned"], "intro")

    def test_who_am_i_is_answered_by_voice_in_a_fresh_round(self):
        model = Model(["HEARD: Penny, who am I?\nPENNY: I see a person. It is a bit blurry.", "PENNY: You're Dad!"])
        d, store = director([near(DAD, 9)], model)
        dad = store.add("person", "dad", [v(5, 128)], "sface", True)["id"]
        for i in range(4):
            store.add_voice(dad, near(DAD, i))
        d._turn(utt=utt("penny"))
        self.assertIn("[SPEAKER] The one talking is dad", model.calls[0]["text"])
        self.assertIn("[WHO] The one asking who they are is dad: PENNY knows their voice", model.calls[1]["text"])
        self.assertFalse(model.calls[1]["wav_exists"] if "wav_exists" in model.calls[1] else False)
        self.assertEqual(d.voices.said, [("penny", "You're Dad!")])

    def test_who_am_i_by_face_and_unknown(self):
        model = Model(["HEARD: who am I\nDYNO: Hmm.", "PENNY: You're Dad!"])
        d, store = director([v(50)], model)
        store.add("person", "dad", [v(5, 128)], "sface", True)
        sees(d, "penny", "dad")
        d._turn(utt=utt("penny"))
        self.assertIn("PENNY sees their face", model.calls[1]["text"])
        model2 = Model(["HEARD: who am I\nPENNY: Hmm.", "PENNY: I don't know you yet! What's your name?"])
        d2, _ = director([v(51)], model2)
        d2._turn(utt=utt("penny"))
        self.assertIn("does not know yet who is talking", model2.calls[1]["text"])


if __name__ == "__main__":
    unittest.main()
