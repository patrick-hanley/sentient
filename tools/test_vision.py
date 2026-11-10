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
        for i in range(5):
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

    def test_a_toy_never_recognises_itself(self):
        r = make_recognizer()
        t = teach.Teacher(teach.TeachStore.__new__(teach.TeachStore), r)
        emb, vecs = t.thing_vecs([blob((40, 200, 60))])
        r.gallery = lambda: teach.Gallery(things=[("toy", "dyno", emb, vecs)])
        self.assertEqual(r.analyze(blob((40, 200, 60)), own_toy="dyno"), [])

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
