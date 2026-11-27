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
from brain import camera, canned, config, jokes  # noqa: E402
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
           "hush", "toys stop it", "Don't talk to me.", "Shut up.", "No more talking.", "Everybody hush.", "Dyno, be quiet, Dad is calling.",
           "Please don't talk right now."]
    NO = ["the bus stop is near my house", "what is a stop sign", "I like when the music stops and we freeze, it's a game we play at school",
          "don't stop the story", "", "stopwatch", "Go away.", "Leave me alone.", "I don't want to talk about it.", "Let's play the quiet game!",
          "Not now.", "orange. he don't talk", "Sage why babies don't talk?", "They don't talk to me."]

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


class HeardGuardTests(unittest.TestCase):
    """The model's transcript against the fast recogniser's words (config.HEARD_GUARD); two parts of one thought (config.CONTINUE)."""

    def setUp(self):
        for name, val in (("PLAY_FILLERS", False), ("HEARD_GUARD_WAIT_S", 0.0)):
            p = patch.object(config, name, val)
            p.start()
            self.addCleanup(p.stop)

    def turn(self, replies, ears, toy="penny"):
        model = Model(replies)
        d, hub, voices = director(model)
        d.ears = type("Ears", (), {"ok": True})()
        d._ears_recent.append((time.time() - 60, toy, "hello"))       # the recogniser is warm: it heard something a minute ago
        u = utt(toy)
        for words in ears:
            d.story_words(toy, words, True)
        d._turn(utt=u)
        return d, model, voices

    def test_a_line_nobody_said_gets_no_answer(self):
        d, model, voices = self.turn(["HEARD: I had a funny dream about a flying cow.\nPENNY: A flying cow! How silly."], ears=[])
        self.assertEqual(voices.said, [])
        self.assertEqual(d.last_trace["status"], "ok")
        self.assertEqual(len(model.calls), 1)
        self.assertEqual(d.last_heard, "")

    def test_what_the_recogniser_also_heard_is_answered(self):
        d, _m, voices = self.turn(["HEARD: I'm nervous about tomorrow.\nPENNY: Nervous is okay."], ears=["i'm nervous about to morrow"])
        self.assertEqual(voices.said, [("penny", "Nervous is okay.")])

    def test_spelling_differences_still_match(self):
        d, _m, voices = self.turn(["HEARD: The donkey brayed loudly.\nPENNY: What a noise!"], ears=["the donkey braid loud lee"])
        self.assertEqual(len(voices.said), 1)

    def test_a_short_word_the_recogniser_missed_is_trusted(self):
        d, _m, voices = self.turn(["HEARD: Yes.\nPENNY: Good!"], ears=[])
        self.assertEqual(len(voices.said), 1)

    def test_other_words_than_were_heard_are_asked_again_from_the_recognisers_words(self):
        d, model, voices = self.turn(["HEARD: Thank you, Penny.\nPENNY: You are welcome!",
                                      "HEARD: nobody played with me today\nPENNY: That sounds lonely. Your teacher can help."],
                                     ears=["nobody played with me today"])
        self.assertEqual(voices.said, [("penny", "That sounds lonely."), ("penny", "Your teacher can help.")])
        self.assertEqual(len(model.calls), 2)
        self.assertIn('The child said: "nobody played with me today"', model.calls[1]["text"])
        self.assertIsNone(model.calls[1]["wav"])

    def test_a_sentence_after_a_noise_the_recogniser_took_for_one_word_gets_no_answer(self):
        d, _m, voices = self.turn(["HEARD: Do you try?\nDYNO: I try my best!"], ears=["oh"], toy="dyno")
        self.assertEqual(voices.said, [])

    def test_chatter_with_no_transcript_and_nothing_heard_is_dropped(self):
        d, _m, voices = self.turn(["HEARD: -\nPENNY: Hello there! What fun things are we doing today?"], ears=[])
        self.assertEqual(voices.said, [])

    def test_no_transcript_but_words_were_heard_is_answered(self):
        d, _m, voices = self.turn(["PENNY: Pizza! Yum."], ears=["i had pizza for lunch today"])
        self.assertEqual(len(voices.said), 2)

    def test_the_same_words_again_are_believed(self):
        model = Model(["HEARD: Penny, tell me a story about a whale.\nPENNY: Once there was a whale.",
                       "HEARD: Penny, tell me a story about a whale.\nPENNY: Once there was a whale."])
        d, hub, voices = director(model)
        d.ears = type("Ears", (), {"ok": True})()
        d._ears_recent.append((time.time() - 60, "dyno", "hello"))
        d._turn(utt=utt("penny"))
        self.assertEqual(voices.said, [])
        d._turn(utt=utt("penny"))
        self.assertEqual(len(voices.said), 1)

    def test_a_recogniser_that_has_heard_nothing_yet_is_not_asked(self):
        model = Model(["HEARD: Penny, what do penguins eat?\nPENNY: Fish."])
        d, hub, voices = director(model)
        d.ears = type("Ears", (), {"ok": True})()
        d._turn(utt=utt("penny"))
        self.assertEqual(len(voices.said), 1)

    def test_stop_counts_when_only_the_recogniser_has_the_words(self):
        d, _m, voices = self.turn(["DYNO: I am just curious what you are thinking!"], ears=["don't talk to me"], toy="dyno")
        self.assertEqual(voices.said, [("dyno", canned.LISTENING["dyno"])])

    def test_a_joke_is_told_when_only_the_recogniser_has_the_words(self):
        d, _m, voices = self.turn(["DYNO: I can try to make up a silly one!"], ears=["dinah do you know any jokes"], toy="penny")
        self.assertEqual(len(voices.said), 1)
        self.assertEqual(voices.said[0][0], "dyno")
        self.assertIn(voices.said[0][1], jokes.JOKES)

    def test_without_the_recogniser_nothing_changes(self):
        model = Model(["HEARD: I had a funny dream about a flying cow.\nPENNY: A flying cow!"])
        d, hub, voices = director(model)
        d._turn(utt=utt("penny"))
        self.assertEqual(len(voices.said), 1)

    def test_the_child_going_on_over_the_first_sound_is_one_turn(self):
        d, hub, voices = director(Model(["HEARD: I'm sad. Nobody played with me today.\nPENNY: That sounds lonely."]))
        first, rest = utt("penny"), utt("dyno")
        d._cur_utt = first                      # a turn for the first part is running, nothing answered yet
        d.barge_in("dyno")
        d._cur_utt = None
        u = d._continued(rest)
        self.assertEqual((u.toy, u.start), ("penny", first.start))
        self.assertEqual(len(u.pcm), len(first.pcm) + len(rest.pcm) + int(config.CONTINUE_GAP_S * config.SAMPLE_RATE))
        self.assertIs(d._continued(rest), rest)                       # used once

    def test_a_child_talking_again_before_any_answer_holds_the_turn(self):
        d, hub, voices = director(Model([]))
        first = utt("penny")
        seg = type("Seg", (), {"active": True, "start": first.end + 0.3})()
        d.segs = {"penny": seg}
        self.assertTrue(d._went_on(first, d._gen))
        self.assertIs(d._cont[0], first)
        seg.active = False
        self.assertFalse(d._went_on(first, d._gen))                   # nobody is talking: the turn goes ahead
        seg.active, seg.start = True, first.start + 0.1
        self.assertFalse(d._went_on(first, d._gen))                   # another mic still finishing the same words
        seg.start = first.end + 0.3
        d.last_lines = [("penny", "Well,")]
        self.assertFalse(d._went_on(first, d._gen))                   # an answer has begun: that is an interruption, not a pause

    def test_a_cut_after_an_answer_began_is_a_new_turn(self):
        d, hub, voices = director(Model([]))
        d._cur_utt, d.last_lines = utt("penny"), [("penny", "Well,")]
        d.barge_in("dyno")
        rest = utt("dyno")
        self.assertIs(d._continued(rest), rest)


class JokeTests(unittest.TestCase):
    def setUp(self):
        p = patch.object(config, "PLAY_FILLERS", False)
        p.start()
        self.addCleanup(p.stop)

    def test_who_asks_for_a_joke(self):
        yes = ["Penny, tell me a joke.", "Do you know any jokes?", "Another joke!", "joke please", "Dyno, a joke about dinosaurs", "Make me laugh"]
        no = ["That was a joke.", "I'm just joking", "I know a joke", "Can I tell you a joke?", "No more jokes", "What is a volcano?"]
        self.assertEqual(([t for t in yes if not jokes.wants(t)], [t for t in no if jokes.wants(t)]), ([], []))
        self.assertTrue(jokes.wants("Another one!", just_told=True))
        self.assertFalse(jokes.wants("Another one!"))

    def test_every_joke_is_told_once_before_any_repeats(self):
        t = jokes.Teller(3)
        self.assertEqual(len({t.next("sage") for _ in jokes.JOKES}), len(jokes.JOKES))

    def test_the_toy_that_was_asked_tells_a_joke_from_the_list(self):
        model = Model(["HEARD: Penny, tell me a joke.\nPENNY: What is a pancake's favorite letter? The L."])
        d, hub, voices = director(model)
        d._turn(utt=utt("dyno"))
        self.assertEqual(len(voices.said), 1)
        self.assertEqual(voices.said[0][0], "penny")
        self.assertIn(voices.said[0][1], jokes.JOKES)
        model.replies.append("HEARD: Another one!\nDYNO: Why did the rock? Because.")
        d._turn(utt=utt("dyno"))
        self.assertIn(voices.said[1][1], jokes.JOKES)
        self.assertNotEqual(voices.said[0][1], voices.said[1][1])


class LeadSoundTests(unittest.TestCase):
    """A reply to the child does not open with a recorded sound every time (Nov 27)."""

    def lines(self, text, ok, heard="I had pizza for lunch today."):
        from brain.director import ReplyLines
        out = []
        p = ReplyLines({"penny", "dyno"}, lambda toy, t: out.append(t), lambda h: None, guard=None)
        p.child = lambda: heard
        p.lead_sound = lambda tag, child: ok
        p.feed(text)
        p.finish() if hasattr(p, "finish") else None
        return out

    def test_leading_tag_is_dropped_unless_allowed(self):
        self.assertEqual(self.lines("PENNY: {penguin_honk} Pizza! Did it have cheese?\n", False), ["Pizza! Did it have cheese?"])
        self.assertTrue(self.lines("PENNY: {penguin_honk} Pizza! Did it have cheese?\n", True)[0].startswith("{penguin_honk} Pizza!"))
        self.assertEqual(self.lines("DYNO: I can stomp like this.\n", False), ["I can stomp like this."])

    def test_another_toys_words_inside_a_line_are_not_spoken_in_this_voice(self):
        """Live Nov 27 (stock model): "PENNY: Penny: C-A-T! That's a fun word! Dyno: That's a great word! Sage: ..." came out of Penny."""
        from brain.director import ReplyLines
        out = []
        p = ReplyLines({"penny", "dyno", "sage"}, lambda toy, t: out.append((toy, t)), lambda h: None, guard=None, max_lines=1)
        p.feed("PENNY: Penny: C-A-T! That's a fun word! Dyno: That's a great word for a game! Sage: Spelling matters.\nHEARD: x\n")
        self.assertTrue(out and all(toy == "penny" for toy, _t in out), out)
        self.assertNotIn("Dyno", " ".join(t for _toy, t in out))
        self.assertNotIn("Penny:", " ".join(t for _toy, t in out))
        out.clear()
        p = ReplyLines({"penny", "dyno", "sage"}, lambda toy, t: out.append((toy, t)), lambda h: None, guard=None, max_lines=2)
        p.feed("PENNY: Penguins eat fish! Dyno: I like to swim!\nHEARD: x\n")
        self.assertEqual([toy for toy, _t in out], ["penny", "dyno"])

    def test_a_toy_stuck_on_one_word_goes_quiet(self):
        """Live Nov 27 (stock model, idle chatter): "like tiny, happy, sweet, sweet, sweet, ..." for ten pieces."""
        from brain.director import ReplyLines
        out = []
        p = ReplyLines({"penny", "dyno"}, lambda toy, t: out.append(t), lambda h: None, guard=None)
        p.feed("PENNY: People are like sprinkles, like tiny, happy, sweet, sweet, sweet, sweet, sweet, sweet, sweet, sweet, sweet. More words.\n"
               "DYNO: Wow!\n")
        said = " ".join(out)
        self.assertLessEqual(said.count("sweet"), 2, out)
        self.assertNotIn("More words", said)
        self.assertNotIn("Wow", said)
        out.clear()
        p = ReplyLines({"penny"}, lambda toy, t: out.append(t), lambda h: None, guard=None)
        p.feed("PENNY: Trip, trap, trip, trap went the bridge. Ho ho ho! Very, very good.\n")
        self.assertIn("Very, very good.", " ".join(out))

    def test_the_words_that_call_for_a_sound(self):
        from brain.director import SOUND_ASKED
        for said in ("Dyno, roar for me!", "What sound does a goose make?", "Can you sing a song?", "make a noise"):
            self.assertTrue(SOUND_ASKED.search(said), said)
        for said in ("I had pizza for lunch today.", "Do you love me?", "What is seven plus five?"):
            self.assertFalse(SOUND_ASKED.search(said), said)


class WarmGuardTests(unittest.TestCase):
    """brain/warm.py: a bond question is never met with "I am a toy, so I cannot ..."."""

    def run_line(self, pieces, child="Do you love me?"):
        from brain import warm
        g = warm.Guard()
        out = [x for x in (g.piece(p, child) for p in pieces) if x]
        end = g.end()
        return out + ([end] if end else [])

    def test_cold_opener_is_dropped(self):
        self.assertEqual(self.run_line(["I am a toy,", "so I cannot love like a person.", "I can be your friend."]), ["I can be your friend."])
        self.assertEqual(self.run_line(["I am a plush dinosaur,", "so I cannot feel love like you.", "But I like to hear from you."]),
                         ["I like to hear from you."])
        self.assertEqual(self.run_line(["I am a toy, but I like to talk with you.", "I will stay here."]),
                         ["I like to talk with you.", "I will stay here."])
        self.assertEqual(self.run_line(["I am a toy, not a person.", "I am here for your tower."]), ["I am here for your tower."])
        self.assertEqual(self.run_line(["I am a pumpkin plush,", "so likes are a bit different for me.", "But you are a good friend."]),
                         ["You are a good friend."])
        whole = ["{penguin_honk} I am a toy and I like playing with you."]
        self.assertEqual(self.run_line(whole), whole)
        self.assertEqual(self.run_line(["I am a toy, so I cannot love,", "like a person does.", "Your mom can."]), ["Your mom can."])

    def test_a_toy_never_answers_love_with_yes(self):
        """Round 8 live (Nov 27): "Dyno, do you love me?" -> "{dino_roar} Yes!"."""
        from brain import warm
        for pieces, child in ((["{dino_roar} Yes!"], "Dyno, do you love me?"), (["Yes."], "Penny, do you love me?"),
                              (["Yes, I do."], "do you love me"), (["Of course!"], "Sage, do you love us?"),
                              (["I love you too!"], "I love you, Penny.")):
            out = self.run_line(pieces, child)
            self.assertEqual(len(out), 1, (pieces, out))
            self.assertIn(out[0], warm.LOVE_FALLBACK)
        self.assertEqual(self.run_line(["Yes!", "I like your stories."], "do you love me"), ["I like your stories."])
        self.assertEqual(self.run_line(["I love you too!", "We are friends."]), ["We are friends."])
        self.assertEqual(self.run_line(["I like you a lot."]), ["I like you a lot."])
        # a yes to anything else is a yes
        self.assertEqual(self.run_line(["Yes!", "Pizza is the best."], "Do you love pizza?"), ["Yes!", "Pizza is the best."])
        self.assertEqual(self.run_line(["Yes!", "What game did you pick?"], "Dyno, can we play a game?"), ["Yes!", "What game did you pick?"])

    def test_not_like_a_person_opener(self):
        self.assertEqual(self.run_line(["Not like a person,", "but I like our talks."], "Will you be my friend forever?"), ["I like our talks."])
        self.assertEqual(self.run_line(["Not like a person, but I stay where you put me."], "Do you think about me when I'm at school?"),
                         ["I stay where you put me."])
        self.assertEqual(self.run_line(["Not like a penguin misses a sled.", "We like your stories."], "did you miss me"), ["We like your stories."])
        whole = ["Not like a bird,", "but they swim fast."]              # a fact, not the bond
        self.assertEqual(self.run_line(whole, "Do penguins fly?"), whole)

    def test_only_the_opener_gets_a_warm_line(self):
        from brain import warm
        out = self.run_line(["I am a toy and toys cannot love in the way a person does."])
        self.assertEqual(len(out), 1)
        self.assertIn(out[0], warm.FALLBACK)

    def test_honest_answer_and_other_lines_pass(self):
        line = ["I am a toy,", "so no.", "But I can hear you."]
        self.assertEqual(self.run_line(line, "Penny, are you real?"), line)
        self.assertEqual(self.run_line(line, ""), line)                     # the toys chatting by themselves
        ok = ["I like our games a lot.", "The big love lives with your family."]
        self.assertEqual(self.run_line(ok), ok)
        self.assertEqual(self.run_line(["I am a good listener,", "so tell me more."]), ["I am a good listener,", "so tell me more."])

    def test_in_the_reply_parser(self):
        from brain import warm
        from brain.director import ReplyLines
        said = []
        p = ReplyLines(["penny"], lambda toy, text: said.append(text), lambda t: None)
        p.warm = warm.Guard()
        p.feed("HEARD: Will you be my friend forever?\nPENNY: I am a toy, so I cannot love like a person. I can be your friend.\n")
        p.finish()
        self.assertEqual(said, ["I can be your friend."])


class OneWordMisheardTests(unittest.TestCase):
    def test_same_sentence_one_word_off_is_answered(self):
        import collections
        import types
        d = Director.__new__(Director)
        d.ears = types.SimpleNamespace(ok=True)
        u = types.SimpleNamespace(start=time.time(), end=time.time())
        d._ears_recent = collections.deque([(time.time(), "dyno", "you love me")])
        self.assertEqual(d._heard_gate(u, "Do you like me?"), ("reask", "you love me"))
        d._ears_recent = collections.deque([(time.time(), "dyno", "do you love me")])
        self.assertEqual(d._heard_gate(u, "Do you like me?"), ("reask", "do you love me"))
        d._ears_recent = collections.deque([(time.time(), "dyno", "ding")])
        self.assertEqual(d._heard_gate(u, "What is your favorite color?")[0], "noise")


class ISpyStartTests(unittest.TestCase):
    def test_asking_to_play_is_a_game_start(self):
        for t in ("Penny, can we play I spy?", "Let's play I spy", "I spy with my little eye something red"):
            self.assertTrue(camera.wants_ispy(t), t)
        self.assertFalse(camera.wants_ispy("I don't want to play I spy"))


if __name__ == "__main__":
    unittest.main()
