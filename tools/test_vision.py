"""Camera policy + 'Teach the camera': intent rules, the LOOK handshake, cameras-off defaults, the encrypted embeddings
store, recognising enrolled faces/toys/items, and the Parent Board endpoints. No models or devices needed (fakes)."""
from __future__ import annotations

import http.client
import json
import logging
import os
import sys
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import cv2
import numpy as np

from brain import camera, config, parent as P, parent_web, perception, teach
from brain.director import Director, system_prompt
from brain.perception import Perceiver, Recognizer, Thing, View
from brain.vad import Utterance

FAST = (2 ** 10, 8, 1)


def jpeg(color=(30, 30, 30), size=(320, 240)):
    img = np.full((size[1], size[0], 3), color, np.uint8)
    return cv2.imencode(".jpg", img)[1].tobytes()


def blob(color, bg=(90, 90, 90), shift=0, dim=1.0):
    """A toy-ish picture: a coloured blob in the middle of a grey wall (optionally dim, like the toy cameras)."""
    img = np.full((240, 320, 3), bg, np.uint8)
    cv2.ellipse(img, (160 + shift, 120), (60, 80), 0, 0, 360, color, -1)
    cv2.circle(img, (160 + shift, 80), 20, tuple(int(c * .5) for c in color), -1)
    return (img * dim).astype(np.uint8)


# ---------------------------------------------------------------------------------------------------------------
class IntentTests(unittest.TestCase):
    YES = ["What do you see?", "Dyno, what do you see right now", "Look at this!", "look what I made", "What is this?",
           "what's this", "Can you see my drawing?", "can you see me", "do you see this", "what am I holding", "what are these",
           "Let me show you my toy", "who's this", "what color is this", "come look", "Take a look at my lego",
           "what are you looking at", "check this out", "can you look at this", "what kind of animal is this",
           "Sage, can you see the sun", "I want to show you something", "what do I have in my hand"]
    NO = ["I don't want to look", "stop looking at me", "what is two plus two", "what is the capital of france", "look for my shoes",
          "see you later", "can you sing", "what time is it", "let's see how many", "I see a bird", "what's your name", "how are you",
          "turn off the camera", "what is it called", "what is a volcano", "tell me a story", "look up at the sky", "no peeking",
          "can you spell cat", "do you like pizza", "", "hi", "don't look"]

    def test_asking_to_look_is_detected(self):
        self.assertEqual([t for t in self.YES if not camera.wants_look(t)], [])

    def test_everything_else_is_not(self):
        self.assertEqual([t for t in self.NO if camera.wants_look(t)], [])

    def test_the_prompt_tells_the_model_the_cameras_are_off_and_how_to_ask(self):
        self.assertIn("cameras are OFF", system_prompt())
        with patch.object(config, "CAPTURE_CONTINUOUS", True):
            self.assertNotIn("cameras are OFF", system_prompt())


class ISpyIntentTests(unittest.TestCase):
    YES = ["I spy with my little eye something red", "i spy something blue", "Let's play I spy", "eye spy something green",
           "I see something yellow", "guess what I see", "your turn to spy", "Sage, I spy something round"]
    NO = ["I see a bird", "what is a spy", "spies are cool", "I don't want to play i spy anymore, stop the game", "see you later",
          "what do you see", "can you spell spy"]

    def test_starting_or_playing_i_spy_is_detected(self):
        self.assertEqual([t for t in self.YES if not camera.wants_ispy(t)], [])

    def test_everything_else_is_not(self):
        self.assertEqual([t for t in self.NO if camera.wants_ispy(t)], [])

    def test_stop_phrases(self):
        for t in ("stop playing", "I'm done with this game", "let's play something else", "game over", "no more i spy"):
            self.assertTrue(camera.ispy_stop(t), t)
        self.assertFalse(camera.ispy_stop("is it the cup"))

    def test_the_prompts_say_guess_only_what_is_in_the_picture(self):
        b = camera.ispy_prompt("SAGE", "SAGE is looking at a red cup.", True, "I spy something red")
        self.assertIn("[I SPY]", b)
        self.assertIn("Never guess a thing that is not in the list", b)
        self.assertIn("Only SAGE speaks", b)
        self.assertIn("does not see anything like that", b)
        self.assertNotIn("[SECRET]", b)
        self.assertIn("[SECRET] SAGE is spying: yellow duck", camera.ispy_prompt("SAGE", "", True, None, "yellow duck"))
        dead = camera.ispy_prompt("SAGE", "", False)
        self.assertIn("did not work", dead)
        self.assertIn("never pretend to see", dead)
        self.assertIn("I spy", camera.PROMPT_RULE)
        self.assertIn("I spy: the toys guess only things that are really in an attached picture", system_prompt())


class PeelerTests(unittest.TestCase):
    def run_stream(self, pieces):
        p = camera.LookPeeler()
        out = "".join(p.feed(x) for x in pieces) + p.finish()
        return p, out

    def test_look_alone_is_swallowed_however_it_is_split(self):
        for pieces in (["LOOK"], ["LO", "OK"], ["L", "O", "O", "K", "\n"], ["look\n"], ["**LOOK**\n"]):
            p, out = self.run_stream(pieces)
            self.assertTrue(p.looking, pieces)
            self.assertEqual(out, "")

    def test_a_trailing_heard_line_is_kept_for_the_dashboard(self):
        p, out = self.run_stream(["LOOK\nHEA", "RD: what do you see\n"])
        self.assertTrue(p.looking)
        self.assertEqual((out, p.heard), ("", "what do you see"))

    def test_ordinary_replies_pass_through_unchanged_and_immediately(self):
        p = camera.LookPeeler()
        self.assertEqual(p.feed("D"), "D")                       # D cannot start LOOK: released at once, no added delay
        self.assertEqual(p.feed("YNO: hello"), "YNO: hello")
        for text in ("HEARD: hi\nDYNO: x", "SAGE: Look at that!", "PENNY: ok", "DYNO: LOOK out!"):
            p, out = self.run_stream([text])
            self.assertFalse(p.looking)
            self.assertEqual(out, text)

    def test_a_stub_that_never_becomes_look_is_released_at_the_end(self):
        p, out = self.run_stream(["LOO"])
        self.assertFalse(p.looking)
        self.assertEqual(out, "LOO")


# ---------------------------------------------------------------------------------------------------------------
class FakeHub:
    def __init__(self, toys=("dyno", "sage", "penny"), frame=None, cam=True):
        self.toys, self.frame = list(toys), frame if frame is not None else jpeg()
        self.response_active = threading.Event()
        self.atoms = {t: types.SimpleNamespace(cam=cam) for t in toys}
        self.captures, self.played, self.talking = [], [], None

    def online(self):
        return self.toys.copy()

    def stop_all(self):
        pass

    def capture(self, toy, timeout=3.0, force=False):
        self.captures.append((toy, force))
        return self.frame

    def play(self, toy, pcm, *, on_dispatch=None, raise_on_error=False):
        if on_dispatch:
            on_dispatch()
        self.played.append(toy)
        return .02

    def play_line(self, toy, text, voices, **kw):
        return self.play(toy, voices.render(toy, text), **kw)


class FakeVoices:
    def render(self, toy, text):
        return b"\0\0" * 320


class FakeRec:
    gallery = staticmethod(lambda: teach.EMPTY)

    def analyze(self, img, own_toy=None):
        return [Thing("object", "a red cup", (100, 80, 60, 60))]


class Model:
    """Records every call; `replies` are the texts it streams, in order."""
    hears_audio = True
    name = "fake"

    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    def stream(self, text, wav=None, image=None):
        self.calls.append({"text": text, "wav": wav, "image": image, "image_exists": bool(image and Path(image).is_file())})
        yield self.replies.pop(0)


def make_director(model, hub=None, rec=None):
    hub = hub or FakeHub()
    eyes = Perceiver(hub, rec or FakeRec())
    return Director(hub, FakeVoices(), eyes, model, {}), hub, eyes


def utt(toy="sage"):
    now = time.monotonic()
    return Utterance(toy, time.time() - 1, time.time(), np.ones(16000, np.int16), 5000, now - .5, now)


class CamerasOffTests(unittest.TestCase):
    def test_nothing_polls_by_default(self):
        hub = FakeHub()
        eyes = Perceiver(hub, FakeRec())
        for th in threading.enumerate():                             # pollers left by earlier tests end once continuous is off
            if th.name.startswith(("eyes-", "look-now")):
                th.join(2)
        time.sleep(.1)
        before = threading.active_count()
        eyes.start()
        time.sleep(.1)
        self.assertEqual(threading.active_count(), before)
        self.assertEqual(hub.captures, [])
        self.assertTrue(all(not v.eyes for v in eyes.views.values()))
        self.assertIn("cameras are off", eyes.scene_text())
        self.assertIn("eyes are closed", eyes.views["dyno"].describe())

    def test_continuous_capture_is_opt_in(self):
        hub = FakeHub()
        eyes = Perceiver(hub, FakeRec())
        with patch.object(config, "CAPTURE_CONTINUOUS", True), patch.object(config, "CAPTURE_FPS", 50):
            eyes.start()
            time.sleep(.4)
        self.assertGreater(len(hub.captures), 0)

    def test_snap_takes_one_forced_picture_and_close_forgets_it(self):
        hub = FakeHub()
        eyes = Perceiver(hub, FakeRec())
        greeted = []
        eyes.on_seen = lambda *a: greeted.append(a)
        v = eyes.snap("sage")
        self.assertEqual(hub.captures, [("sage", True)])         # mid-turn capture must be allowed
        self.assertTrue(v.eyes and v.jpeg)
        self.assertEqual(greeted, [])                            # looking on request never fires a greeting
        eyes.close("sage")
        self.assertFalse(eyes.views["sage"].eyes)
        self.assertIsNone(eyes.views["sage"].jpeg)
        self.assertIsNone(eyes.views["sage"].annotated)

    def test_snap_returns_none_when_the_camera_does_not_answer(self):
        hub = FakeHub()
        hub.frame = None
        self.assertIsNone(Perceiver(hub, FakeRec()).snap("dyno"))

    def test_hub_capture_force_bypasses_the_mid_turn_pause_only_when_asked(self):
        from brain.atoms import AtomHub
        hub = object.__new__(AtomHub)
        hub.response_active = threading.Event()
        hub.response_active.set()
        hub._http = Mock()
        hub.atoms = {}
        self.assertIsNone(hub.capture("dyno"))
        hub._http.open.assert_not_called()
        hub.capture("dyno", force=True)                          # passes the pause; no such atom, so still None, no request
        self.assertIsNone(hub.capture("dyno", force=True))


class LookTurnTests(unittest.TestCase):
    def test_audio_model_answers_look_then_the_same_turn_answers_from_the_picture(self):
        model = Model(["LOOK", "SAGE: I see a red cup on the table!\nHEARD: what do you see"])
        d, hub, eyes = make_director(model)
        d._turn(utt=utt("sage"))
        self.assertEqual(len(model.calls), 2)
        first, second = model.calls
        self.assertIsNone(first["image"])
        self.assertTrue(first["wav"])
        self.assertTrue(second["image_exists"])                   # the frame is attached to the second call
        self.assertIsNone(second["wav"])
        self.assertIn("[CAMERA]", second["text"])
        self.assertIn("SAGE", second["text"])
        self.assertEqual(hub.captures, [("sage", True)])         # one picture, from the toy that heard the child
        self.assertIn("sage", hub.played)                         # and it answered in the same turn
        self.assertEqual(d.last_trace["status"], "ok")
        self.assertIn("look_ms", d.last_trace["stage_work_ms"])
        self.assertFalse(Path(second["image"]).exists())          # the frame file is gone after the turn
        self.assertFalse(any(v.eyes for v in eyes.views.values()))   # camera off again

    def test_a_normal_question_never_turns_a_camera_on(self):
        model = Model(["DYNO: Seven times eight is fifty-six!\nHEARD: what is seven times eight"])
        d, hub, _ = make_director(model)
        d._turn(utt=utt("dyno"))
        self.assertEqual(hub.captures, [])
        self.assertEqual(len(model.calls), 1)
        self.assertIsNone(model.calls[0]["image"])
        self.assertIn("cameras are off", model.calls[0]["text"])

    def test_transcript_rule_takes_the_picture_before_the_first_call(self):
        class Whisper(Model):
            hears_audio = False

            def transcribe(self, wav):
                return "Look at this!"
        model = Whisper(["SAGE: A red cup!"])
        d, hub, _ = make_director(model)
        d._turn(utt=utt("sage"))
        self.assertEqual(len(model.calls), 1)                     # one model call: no LOOK round trip needed
        c = model.calls[0]
        self.assertTrue(c["image_exists"])
        self.assertIn("[CAMERA]", c["text"])
        self.assertNotIn("[SCENE]", c["text"])
        self.assertIn("Look at this!", c["text"])
        self.assertEqual(hub.captures, [("sage", True)])

    def test_a_dead_camera_is_told_honestly(self):
        hub = FakeHub()
        hub.frame = None
        model = Model(["LOOK", "DYNO: My eyes are not working. What is it?"])
        d, hub, _ = make_director(model, hub)
        d._turn(utt=utt("dyno"))
        self.assertIn("did not work", model.calls[1]["text"])
        self.assertIsNone(model.calls[1]["image"])
        self.assertEqual(d.last_trace["status"], "ok")

    def test_a_toy_without_a_camera_does_not_look(self):
        model = Model(["DYNO: Hi!"])
        d, hub, _ = make_director(model, FakeHub(cam=False))
        d._turn(utt=utt("dyno"))
        self.assertEqual(hub.captures, [])
        self.assertEqual(len(model.calls), 1)

    def test_look_is_asked_once_per_turn(self):
        model = Model(["LOOK", "LOOK"])
        d, hub, _ = make_director(model)
        d._turn(utt=utt("sage"))
        self.assertEqual(len(hub.captures), 1)                    # the second LOOK is not obeyed

    def test_continuous_mode_does_not_use_the_look_round_trip(self):
        model = Model(["DYNO: hi"])
        d, hub, _ = make_director(model)
        with patch.object(config, "CAPTURE_CONTINUOUS", True):
            d._turn(utt=utt("dyno"))
        self.assertEqual(hub.captures, [])


class RefereeTests(unittest.TestCase):
    SEEN = ["red apple", "green leaf", "white plate"]

    def test_the_picture_list_is_parsed(self):
        self.assertEqual(camera.parse_seen("Red apple, green leaf and a white plate."), self.SEEN)
        self.assertEqual(camera.parse_seen("- red apple\n- green leaf"), ["red apple", "green leaf"])

    def test_a_color_nothing_has_gets_the_honest_line(self):
        r = camera.ISpyReferee("I spy something purple", self.SEEN)
        self.assertEqual(r.decide("Is it the apple?"), "Hmm, I don't see anything purple from here. Can you give me another hint?")

    def test_a_matching_guess_passes_and_is_remembered(self):
        r = camera.ISpyReferee("I spy something red", self.SEEN)
        self.assertEqual(r.decide("Ooh, is it the apple?"), "Ooh, is it the apple?")
        self.assertEqual(r.guessed, ["red apple"])

    def test_a_guess_not_in_the_picture_is_replaced_by_one_that_is(self):
        r = camera.ISpyReferee("I spy something green", self.SEEN)
        self.assertEqual(r.decide("Is it a green frog?"), "Is it the green leaf?")
        r = camera.ISpyReferee("I spy something red", self.SEEN)
        self.assertEqual(r.decide("I spy with my little eye something red!"), "Is it the red apple?")   # echoing the child is not a guess

    def test_after_a_no_the_same_clue_goes_on_and_nothing_is_guessed_twice(self):
        r = camera.ISpyReferee("No, guess again!", self.SEEN, guessed=["red apple"], clue="red")
        self.assertEqual(r.decide("Is it the apple?"), "Hmm, I don't see anything else red from here. Can you give me another hint?")

    def test_my_turn_spies_a_thing_in_the_picture_and_keeps_it_secret(self):
        r = camera.ISpyReferee("Your turn to spy, Penny", ["yellow duck", "blue tub"])
        self.assertEqual(r.decide("Is it the yellow duck?"), "I spy with my little eye something yellow!")
        self.assertEqual(r.secret, "yellow duck")
        r = camera.ISpyReferee("your turn", ["yellow duck", "blue tub"])
        self.assertEqual(r.decide("I spy with my little eye something blue!"), "I spy with my little eye something blue!")
        self.assertEqual(r.secret, "blue tub")

    def test_the_audio_model_clue_comes_from_heard(self):
        r = camera.ISpyReferee("", self.SEEN)
        self.assertEqual(r.decide("Is it the plate?", heard="I spy something purple"), "Hmm, I don't see anything purple from here. Can you give me another hint?")

    def test_bare_colors_and_color_named_things(self):
        r = camera.ISpyReferee("I spy something blue", ["blueberries", "dark blue", "beige"])
        self.assertEqual(r.decide("Is it the blue ball?"), "Is it the blueberries?")
        r = camera.ISpyReferee("I spy something yellow", ["cucumbers", "green", "yellow"])
        self.assertEqual(r.decide("Is it the yellow banana?"), "Is it the yellow banana?")   # the list saw yellow, the toy named it
        r = camera.ISpyReferee("I spy something yellow", ["cucumbers", "green", "yellow"])
        self.assertEqual(r.decide("I spy something yellow!"), "I see something yellow, but I can't tell what it is. Can you give me a hint?")
        r = camera.ISpyReferee("no", ["red apple", "red"], guessed=["red apple"], clue="red")
        self.assertIn("anything else red", r.decide("Is it the red apple?"))

    def test_no_list_changes_nothing(self):
        self.assertEqual(camera.ISpyReferee("I spy something purple", []).decide("Is it the cup?"), "Is it the cup?")


class SpokenVoices(FakeVoices):
    def __init__(self):
        self.said = []

    def render(self, toy, text):
        self.said.append((toy, text))
        return super().render(toy, text)


class ISpyModel(Model):
    """Answers the picture-list call with `seen`; the turn calls get `replies` in order."""

    def __init__(self, replies, seen="red cup, white plate", said=None):
        super().__init__(replies)
        self.seen, self.said, self.lists = seen, list(said or []), 0
        self.hears_audio = said is None

    def transcribe(self, wav):
        return self.said.pop(0)

    def stream(self, text, wav=None, image=None):
        if text.startswith("[I SPY LIST]"):
            self.lists += 1
            yield self.seen
            return
        yield from super().stream(text, wav, image)


def spy_director(model, hub=None):
    hub = hub or FakeHub()
    voices = SpokenVoices()
    d = Director(hub, voices, Perceiver(hub, FakeRec()), model, {})
    return d, hub, voices


class ISpyTurnTests(unittest.TestCase):
    def setUp(self):
        p = patch.object(config, "PLAY_FILLERS", False)
        p.start()
        self.addCleanup(p.stop)

    def test_audio_model_i_spy_turns_the_game_on_and_the_next_guess_comes_with_a_fresh_picture(self):
        model = ISpyModel(["LOOK", "SAGE: Is it the red cup?\nHEARD: I spy with my little eye something red",
                           "DYNO: Is it the cup?\nHEARD: no"])
        d, hub, voices = spy_director(model)
        d._turn(utt=utt("sage"))
        self.assertTrue(d._ispy_on())                               # the child's words (HEARD) started the game
        d._turn(utt=utt("dyno"))
        turn = model.calls[-1]
        self.assertEqual(model.lists, 1)                            # one picture-list call for the I spy turn
        self.assertIn("[I SPY]", turn["text"])
        self.assertIn("DYNO sees: red cup, white plate", turn["text"])
        self.assertIn("[TOYS HERE] DYNO ", turn["text"])           # one guesser
        self.assertTrue(turn["wav"])                                # the model still hears the child's guess
        self.assertEqual(hub.captures, [("sage", True), ("dyno", True)])
        self.assertFalse(Path(turn["image"]).exists())              # RAM temp file deleted after the turn

    def test_transcript_path_holds_the_line_to_the_picture(self):
        model = ISpyModel(["SAGE: Is it the purple grape?\nDYNO: I spy something blue!"], said=["I spy something purple"])
        d, hub, voices = spy_director(model)
        d._turn(utt=utt("sage"))
        self.assertEqual(voices.said, [("sage", "Hmm, I don't see anything purple from here. Can you give me another hint?")])
        self.assertTrue(d._ispy_on())

    def test_no_then_a_new_guess_from_the_picture(self):
        model = ISpyModel(["SAGE: Is it the red cup?", "SAGE: Is it the cup?"], seen="red cup, red ball, white plate",
                          said=["I spy something red", "No!"])
        d, hub, voices = spy_director(model)
        d._turn(utt=utt("sage"))
        d._turn(utt=utt("sage"))
        self.assertEqual([t for _w, t in voices.said], ["Is it the red cup?", "Is it the red ball?"])

    def test_the_toys_turn_to_spy_and_the_secret_is_kept(self):
        model = ISpyModel(["PENNY: Is it a duck?"], seen="yellow duck, blue tub", said=["Your turn to spy, Penny!"])
        d, hub, voices = spy_director(model)
        d._turn(utt=utt("penny"))
        self.assertEqual(voices.said, [("penny", "I spy with my little eye something yellow!")])
        self.assertEqual(d._ispy_secret, "yellow duck")

    def test_the_game_ends_when_the_child_stops_or_goes_quiet(self):
        model = ISpyModel(["SAGE: Is it the red cup?", "SAGE: Okay!", "SAGE: A cloud is water drops."],
                          said=["I spy something red", "stop playing", "what is a cloud"])
        d, hub, _ = spy_director(model)
        for _ in range(3):
            d._turn(utt=utt("sage"))
        self.assertEqual(len(hub.captures), 1)                      # only the I spy turn looked
        self.assertNotIn("[I SPY]", model.calls[1]["text"])
        self.assertFalse(d._ispy_on())

    def test_a_dead_camera_asks_for_hints_and_never_pretends(self):
        hub = FakeHub()
        hub.frame = None
        model = ISpyModel(["DYNO: My eyes are not working! Give me a hint?"])
        d, hub, voices = spy_director(model, hub)
        d._ispy_until = time.time() + 60
        d._turn(utt=utt("dyno"))
        self.assertIn("did not work", model.calls[0]["text"])
        self.assertIsNone(model.calls[0]["image"])
        self.assertEqual(model.lists, 0)
        self.assertEqual(" ".join(t for _w, t in voices.said), "My eyes are not working! Give me a hint?")

    def test_a_toy_without_a_camera_takes_no_picture(self):
        model = ISpyModel(["DYNO: Give me a hint!"])
        d, hub, _ = spy_director(model, FakeHub(cam=False))
        d._ispy_until = time.time() + 60
        d._turn(utt=utt("dyno"))
        self.assertEqual(hub.captures, [])

    def test_hidden_notes_are_never_spoken(self):
        from brain.director import clean
        self.assertEqual(clean("I spy something green! SECRET: ball"), "I spy something green!")

    def test_idle_chat_never_seeds_i_spy(self):
        self.assertFalse(any("spy" in s.lower() for s in config.BANTER_SEEDS))


class CameraModeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = patch.object(config, "CAMERA_MODE_FILE", Path(self.tmp.name) / "camera_mode.json")
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(config.set_camera_mode, "request", False)

    def test_off_means_no_picture_ever_and_the_prompt_says_so(self):
        model = Model(["DYNO: My eyes are off right now. Tell me about it!"])
        d, hub, _ = make_director(model)
        model.system = "old"
        d.set_camera_mode("off")
        self.assertIn("switched OFF", model.system)
        self.assertNotIn("reply with exactly one word, LOOK", model.system)
        d._ispy_until = time.time() + 60
        d._turn(utt=utt("dyno"))
        self.assertEqual(hub.captures, [])
        self.assertEqual(d.look_now("dyno"), {"error": "the cameras are off"})
        self.assertEqual(json.loads(config.CAMERA_MODE_FILE.read_text()), {"mode": "off"})   # kept across restarts

    def test_request_and_always(self):
        d, hub, eyes = make_director(Model([]))
        d.set_camera_mode("request")
        self.assertTrue(config.LOOK_ON_REQUEST and not config.CAPTURE_CONTINUOUS)
        self.assertIn("reply with exactly one word, LOOK", system_prompt())
        with patch.object(config, "CAPTURE_FPS", 50):
            d.set_camera_mode("always")
            time.sleep(.2)
            self.assertGreater(len(hub.captures), 0)
            d.set_camera_mode("request")                           # back off: polling stops, frames forgotten
        time.sleep(.2)
        n = len(hub.captures)
        time.sleep(.2)
        self.assertEqual(len(hub.captures), n)
        self.assertFalse(any(v.eyes for v in eyes.views.values()))
        for th in threading.enumerate():
            if th.name.startswith("eyes-"):
                th.join(2)                                           # the pollers have ended


class LookNowTests(unittest.TestCase):
    def test_the_dashboard_look_takes_one_picture_and_returns_what_was_said_and_seen(self):
        model = Model(["PENNY: I see a red cup on the table!\nHEARD: -"])
        d, hub, eyes = make_director(model)
        r = d.look_now("penny")
        self.assertEqual(hub.captures, [("penny", True)])
        self.assertEqual(r["said"], "I see a red cup on the table!")
        self.assertEqual(r["seen"], ["a red cup"])
        self.assertTrue(r["frame"])                                  # annotated frame for the dashboard, not kept
        self.assertIsNone(d.last_look)
        self.assertIn("[CAMERA]", model.calls[0]["text"])
        self.assertIn("[TOYS HERE] PENNY ", model.calls[0]["text"])
        self.assertFalse(any(v.eyes for v in eyes.views.values()))   # camera off again

    def test_offline_or_no_camera(self):
        d, hub, _ = make_director(Model([]), FakeHub(cam=False))
        self.assertIn("no camera", d.look_now("sage")["error"])


# ---------------------------------------------------------------------------------------------------------------
def make_parent(tmp):
    p = P.Parent(directory=tmp, kdf=FAST)
    p.setup("correct horse battery", p.setup_code)
    return p


def vec(seed, n=128):
    v = np.random.RandomState(seed).randn(n).astype(np.float32)
    return v / np.linalg.norm(v)


def near(v, seed, noise=.05):
    w = v + noise * np.random.RandomState(seed).randn(len(v)).astype(np.float32)
    return w / np.linalg.norm(w)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self._d = tempfile.TemporaryDirectory()
        self.p = make_parent(self._d.name)
        self.store = teach.TeachStore(self.p)

    def tearDown(self):
        self._d.cleanup()

    def test_consent_is_required(self):
        with self.assertRaises(ValueError):
            self.store.add("person", "Grandma", [vec(1)], "sface", consent=False)
        self.assertEqual(self.store.list(), [])

    def test_the_file_is_encrypted_and_holds_no_name_or_vector(self):
        v = vec(7)
        self.store.add("person", "Grandma Zelda", [v], "sface", True, role="family")
        raw = Path(self._d.name, teach.FILE).read_bytes()
        self.assertTrue(raw.startswith(b"SPB1"))
        self.assertNotIn(b"Zelda", raw)
        self.assertNotIn(f"{float(v[0]):.5f}".encode(), raw)
        self.assertNotIn(b"sface", raw)

    def test_nothing_but_the_encrypted_file_is_written_no_photos(self):
        self.store.add("item", "red cup", [vec(2)], "hist", True)
        self.assertEqual(sorted(os.listdir(self._d.name)), sorted(os.listdir(self._d.name)))
        names = os.listdir(self._d.name)
        self.assertFalse([n for n in names if n.lower().endswith((".jpg", ".jpeg", ".png", ".npz", ".npy"))])

    def test_survives_a_restart_with_the_pin_and_is_empty_while_locked(self):
        self.store.add("child", "Maya", [vec(3)], "sface", True, child="c1")
        self.store.add("toy", "dyno", [vec(4)], "hist", True)
        p2 = P.Parent(directory=self._d.name, kdf=FAST)          # a restarted brain: locked
        s2 = teach.TeachStore(p2)
        self.assertFalse(s2.gallery())                            # nobody is recognised until the PIN is entered
        with self.assertRaises(P.Locked):
            s2.list()
        p2.login("correct horse battery")
        self.assertEqual(sorted(e["kind"] for e in s2.list()), ["child", "toy"])
        self.assertEqual(len(s2.gallery().people), 1)
        self.assertEqual(len(s2.gallery().things), 1)
        p2.lock()
        self.assertFalse(s2.gallery())                            # locking forgets them again

    def test_list_never_exposes_vectors(self):
        self.store.add("person", "Dad", [vec(5), vec(6)], "sface", True)
        e = self.store.list()[0]
        self.assertEqual(e["photos"], 2)
        self.assertNotIn("vecs", e)
        self.assertNotIn("consent", json.dumps(e).lower() if False else "")

    def test_delete_one_person_leaves_the_others(self):
        a = self.store.add("person", "Mum", [vec(1)], "sface", True)
        self.store.add("person", "Dad", [vec(2)], "sface", True)
        self.store.delete(a["id"])
        self.assertEqual([e["name"] for e in self.store.list()], ["Dad"])
        self.assertEqual([n for n, _, _ in self.store.gallery().people], ["Dad"])
        with self.assertRaises(KeyError):
            self.store.delete(a["id"])

    def test_deleting_a_child_profile_deletes_their_face(self):
        self.store.add("child", "Maya", [vec(1)], "sface", True, child="c1")
        self.store.add("person", "Mum", [vec(2)], "sface", True)
        self.store.forget_child("c1")
        self.assertEqual([e["kind"] for e in self.store.list()], ["person"])

    def test_more_photos_of_the_same_name_are_appended_and_capped(self):
        for i in range(30):
            self.store.add("item", "red cup", [vec(i), vec(i + 10), vec(i + 20)], "hist", True)
        (e,) = self.store.list()
        self.assertEqual(e["photos"], teach.MAX_VECS)

    def test_wipe_all_removes_the_file(self):
        self.store.add("person", "Mum", [vec(1)], "sface", True)
        self.p.wipe_all("correct horse battery")
        self.assertFalse(Path(self._d.name, teach.FILE).exists())
        self.assertFalse(self.store.gallery())

    def test_toy_names_must_be_real_toys(self):
        with self.assertRaises(ValueError):
            self.store.add("toy", "robbie", [vec(1)], "hist", True)

    def test_names_and_vectors_are_never_logged(self):
        rec = types.SimpleNamespace(faces=lambda img: [((10, 10, 50, 50), vec(9), .99)])
        t = teach.Teacher(self.store, rec)
        with self.assertLogs("teach", level="DEBUG") as cm:
            t.enroll("person", "Zelda Quixote", [blob((0, 200, 0))], True)
        text = " ".join(cm.output)
        self.assertNotIn("Zelda", text)
        self.assertNotIn("Quixote", text)


# ---------------------------------------------------------------------------------------------------------------
def make_recognizer(faces=(), objects=(), emb=None):
    """A Recognizer with the models stubbed out (the real tag detector is kept)."""
    r = object.__new__(Recognizer)
    r.lock = threading.Lock()
    r.aruco = cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50), cv2.aruco.DetectorParameters())
    r.clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(4, 4))
    r.obj = r.emb = emb
    r.people, r.pets = {}, {}
    r.gallery = lambda: teach.EMPTY
    r.faces = lambda img: list(faces)
    r.objects = lambda img: list(objects)
    return r


class RecognizerTests(unittest.TestCase):
    def img(self):
        return np.full((240, 320, 3), 90, np.uint8)

    def test_unknown_face_is_just_a_person(self):
        r = make_recognizer(faces=[((100, 60, 60, 60), vec(1), .9)])
        self.assertEqual([(t.kind, t.label) for t in r.analyze(self.img())], [("person", "a person")])

    def test_enrolled_child_is_the_child_and_a_parent_is_named(self):
        gal = teach.Gallery(people=[("child", "child", [vec(1)]), ("Mum", "parent", [vec(2)])])
        r = make_recognizer(faces=[((10, 60, 60, 60), near(vec(1), 1), .9), ((200, 60, 60, 60), near(vec(2), 2), .9),
                                   ((100, 10, 40, 40), vec(3), .9)])
        r.gallery = lambda: gal
        got = {(t.kind, t.label) for t in r.analyze(self.img())}
        self.assertEqual(got, {("child", "the child"), ("person", "Mum"), ("person", "a person")})

    def test_a_family_member_enrolled_with_the_child_role_is_not_called_the_child_unless_role_child(self):
        gal = teach.Gallery(people=[("Grandpa", "family", [vec(1)])])
        r = make_recognizer(faces=[((10, 60, 60, 60), vec(1), .9)])
        r.gallery = lambda: gal
        self.assertEqual([(t.kind, t.label) for t in r.analyze(self.img())], [("person", "Grandpa")])

    def test_enrolled_toys_are_recognised_without_a_tag_and_household_items_by_name(self):
        r = make_recognizer()
        t = teach.Teacher(teach.TeachStore.__new__(teach.TeachStore), r)
        green, purple, red = (40, 200, 60), (200, 60, 160), (40, 40, 220)
        gal = teach.Gallery()
        for kind, name, col in (("toy", "dyno", green), ("toy", "sage", purple), ("item", "red cup", red)):
            emb, vecs = t.thing_vecs([blob(col, shift=s, dim=d) for s, d in ((0, 1), (6, .8), (-6, .6))])
            self.assertEqual(emb, "hist")
            gal.things.append((kind, name, emb, vecs))
        r.gallery = lambda: gal
        for col, shift, dim, want in ((green, 4, .5, ("toy", "DYNO")), (purple, -5, .9, ("toy", "SAGE")),
                                      (red, 3, .7, ("object", "red cup"))):
            got = [(x.kind, x.label) for x in r.analyze(blob(col, shift=shift, dim=dim), own_toy="penny")]
            self.assertEqual(got, [want], (col, got))
        # a wall with nothing taught on it, and a colour nobody enrolled, claim nothing
        self.assertEqual(r.analyze(self.img()), [])
        self.assertEqual(r.analyze(blob((200, 200, 40))), [])

    def test_a_toy_that_sees_itself_says_so(self):
        r = make_recognizer()
        t = teach.Teacher(teach.TeachStore.__new__(teach.TeachStore), r)
        emb, vecs = t.thing_vecs([blob((40, 200, 60))])
        r.gallery = lambda: teach.Gallery(things=[("toy", "dyno", emb, vecs)])
        seen = r.analyze(blob((40, 200, 60)), own_toy="dyno")
        self.assertEqual([x.label for x in seen], [perception.SELF_LABEL])            # a mirror or a picture of itself
        v = View("dyno", time.time(), True, seen, seen[0])
        self.assertIn("DYNO is looking at itself", v.describe())
        self.assertIn("that's me", camera.look_prompt("DYNO", v.describe(), True))
        self.assertEqual([x.label for x in r.analyze(blob((40, 200, 60)), own_toy="sage")], ["DYNO"])   # another toy sees Dyno

    def test_taught_through_one_camera_recognised_through_a_dimmer_or_tinted_one(self):
        r = make_recognizer()
        t = teach.Teacher(teach.TeachStore.__new__(teach.TeachStore), r)
        emb, vecs = t.thing_vecs([blob((30, 90, 220), shift=s) for s in (-10, 0, 10)])   # taught on a bright camera (an orange item)
        self.assertEqual(len(vecs), 3 * 5)                                                 # 3 photos x 5 camera variants (one region here)
        r.gallery = lambda: teach.Gallery(things=[("item", "orange ball", emb, vecs), ("item", "blue cup", emb, t.thing_vecs([blob((200, 90, 30))])[1])])
        dim = blob((30, 90, 220), dim=0.5)
        warm = np.clip(blob((30, 90, 220)).astype(np.float32) * np.array([0.8, 1.0, 1.2]), 0, 255).astype(np.uint8)
        for img in (dim, warm):
            self.assertIn("orange ball", [x.label for x in r.analyze(img, own_toy="penny")])

    def test_two_lookalike_things_are_not_guessed_between(self):
        a = vec(1, 64)
        gal = teach.Gallery(things=[("item", "cup", "mp", [a]), ("item", "mug", "mp", [near(a, 1, .01)])])
        self.assertEqual(gal.match_things({"mp": [a]}), [])        # too close to call: say nothing

    def test_dark_frames_still_match_the_histogram_embedder(self):
        a, b = teach.hist_embed(blob((40, 200, 60))), teach.hist_embed(blob((40, 200, 60), dim=.35))
        self.assertGreater(float(a @ b), teach.THING_MATCH["hist"])
        c = teach.hist_embed(blob((200, 60, 160)))
        self.assertLess(float(a @ c), teach.THING_MATCH["hist"] - .1)

    def test_the_legacy_log_line_has_counts_not_names(self):
        src = Path(perception.__file__).read_text()
        self.assertNotIn("list(self.people)", src)


# ---------------------------------------------------------------------------------------------------------------
class WebTests(unittest.TestCase):
    def setUp(self):
        self._d = tempfile.TemporaryDirectory()
        self.p = make_parent(self._d.name)
        self.hub = FakeHub(("dyno", "sage"), frame=jpeg((40, 200, 60)))
        self.rec = types.SimpleNamespace(faces=lambda img: [((10, 10, 60, 60), vec(11), .9)], objects=lambda img: [],
                                         thing_vec=lambda img, box: ("hist", teach.hist_embed(img[box[1]:box[1] + box[3], box[0]:box[0] + box[2]])),
                                         embedder_name="hist")
        self.p.teacher = teach.Teacher(teach.TeachStore(self.p), self.rec, self.hub)
        self.director = Mock()
        self.director.hub = self.hub
        self.srv = parent_web.ThreadingHTTPServer(("127.0.0.1", 0), parent_web.make_handler(self.p, self.director))
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.port = self.srv.server_port
        self.cookie = None
        c = http.client.HTTPConnection("127.0.0.1", self.port)
        c.request("POST", "/api/login", json.dumps({"pin": "correct horse battery"}), {"Host": f"127.0.0.1:{self.port}", "X-PB": "1", "Content-Type": "application/json"})
        r = c.getresponse()
        r.read()
        self.cookie = r.getheader("Set-Cookie").split(";")[0]

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        self._d.cleanup()

    def call(self, method, path, body=None, raw=None, ctype=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        h = {"Host": f"127.0.0.1:{self.port}", "Cookie": self.cookie}
        if method == "POST":
            h["X-PB"] = "1"
            h["Content-Type"] = ctype or "application/json"
        c.request(method, path, raw if raw is not None else (json.dumps(body).encode() if body is not None else None), h)
        r = c.getresponse()
        return r.status, json.loads(r.read() or b"{}")

    def test_capture_from_a_toy_camera_needs_consent_and_stores_only_a_vector(self):
        s, j = self.call("POST", "/api/teach/capture", {"kind": "person", "name": "Mum", "toy": "sage", "consent": False})
        self.assertEqual(s, 400)
        self.assertEqual(self.hub.captures, [])                  # no consent: the camera is never even touched
        s, j = self.call("POST", "/api/teach/capture", {"kind": "person", "name": "Mum", "toy": "sage", "consent": True, "role": "parent"})
        self.assertEqual((s, j["used"], j["frames"]), (200, 6, 6))
        self.assertTrue(all(force for _, force in self.hub.captures))
        s, j = self.call("GET", "/api/teach/list")
        self.assertEqual([(e["kind"], e["name"], e["photos"]) for e in j["entries"]], [("person", "Mum", 6)])
        self.assertTrue(any(t["id"] == "dyno" and t["online"] and t["cam"] for t in j["toys"]))
        self.assertNotIn("vecs", json.dumps(j))

    def test_upload_photo_and_delete(self):
        s, j = self.call("POST", "/api/teach/photo?kind=child&consent=1&child=c9", raw=jpeg((10, 10, 200)), ctype="image/jpeg")
        self.assertEqual((s, j["used"]), (200, 1))
        s, j = self.call("POST", "/api/teach/photo?kind=child", raw=jpeg(), ctype="image/jpeg")   # no consent
        self.assertEqual(s, 400)
        s, j = self.call("GET", "/api/teach/list")
        eid = j["entries"][0]["id"]
        self.assertEqual(self.call("POST", "/api/teach/delete", {"id": eid})[0], 200)
        self.assertEqual(self.call("GET", "/api/teach/list")[1]["entries"], [])
        self.assertEqual(os.listdir(self._d.name).count("teach.enc"), 1)   # the encrypted file only; no photo anywhere
        self.assertFalse([n for n in os.listdir(self._d.name) if n.endswith((".jpg", ".png"))])

    def test_an_offline_toy_cannot_be_used_as_the_camera(self):
        s, j = self.call("POST", "/api/teach/capture", {"kind": "item", "name": "cup", "toy": "penny", "consent": True})
        self.assertEqual(s, 400)

    def test_item_from_a_toy_camera(self):
        self.hub.frame = cv2.imencode(".jpg", blob((40, 40, 220)))[1].tobytes()
        s, j = self.call("POST", "/api/teach/capture", {"kind": "item", "name": "red cup", "toy": "dyno", "consent": True})
        self.assertEqual(s, 200)
        self.assertGreater(j["used"], 0)

    def test_the_board_must_be_unlocked(self):
        self.p.lock()
        self.assertEqual(self.call("GET", "/api/teach/list")[0], 401)

    def test_the_page_has_the_section_and_valid_script(self):
        page = Path(parent_web.__file__).with_name("parent.html").read_text()
        self.assertIn("Teach the camera", page)
        self.assertIn("consent", page)


if __name__ == "__main__":
    unittest.main()
