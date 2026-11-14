"""Non-speech vocalizations: never spelled out for a voice, never in a transcript; they become recorded sounds."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from brain import nonspeech, scripted  # noqa: E402
from brain.sfx import Sounds  # noqa: E402


class Fake(Sounds):
    def __init__(self):
        names = ["giggle", "yawn", "sigh", "penguin_honk", "dino_growl", "dino_roar", "snore_big", "snore_cat", "snore_dog"]
        self.pcm = {n: b"\0\0" for n in names}
        self.index = {"snore_big": {"toy": "dyno"}, "snore_cat": {"toy": "sage"}, "snore_dog": {"toy": "penny"},
                      "giggle": {}, "yawn": {}, "sigh": {}, "penguin_honk": {"toy": "penny"}}


S = Fake()
seg = lambda t, toy="penny": S.segments(t, toy)


class SoundsTests(unittest.TestCase):
    def test_spelled_laugh_yawn_honk_become_recordings(self):
        self.assertEqual(seg("Hee hee! Listen!"), [("sfx", "giggle"), ("say", "Listen!")])
        self.assertEqual(seg("ha ha ha"), [("sfx", "giggle")])
        self.assertEqual(seg("Yawn... so sleepy"), [("sfx", "yawn"), ("say", "so sleepy")])
        self.assertEqual(seg("Wheee, honk! Fly!"), [("say", "Wheee"), ("sfx", "penguin_honk"), ("say", "Fly!")])

    def test_hush_and_other_spelled_noises_are_brackets_never_spoken(self):
        self.assertEqual(seg("Shhh! Somebody's dreaming.", "dyno"), [("sfx", "snore_big"), ("say", "Somebody's dreaming.")])
        self.assertEqual(seg("[shhh]", "sage"), [("sfx", "snore_cat")])
        for t, rest in (("Psst! Over here.", "Over here."), ("Ahem. Attention.", "Attention."), ("Achoo! Bless me.", "Bless me."),
                        ("Tsk tsk, silly.", "silly."), ("[psst] hi", "hi"), ("(ahem) well", "well")):
            self.assertEqual(seg(t), [("say", rest)], t)   # no recording exists for these, so nothing is played or spoken
        self.assertEqual(seg("Choo choo train!"), [("say", "Choo choo train!")])
        self.assertEqual(S.display("Psst! Over here."), "{psst} Over here.")   # shown for the operator

    def test_zzz_and_snoring_use_the_speaking_toys_own_snore(self):
        self.assertEqual(seg("Mmm, zzz... zzz...", "dyno")[1], ("sfx", "snore_big"))
        self.assertEqual(seg("[snoring]", "sage"), [("sfx", "snore_cat")])
        self.assertEqual(seg("[Snore]", "penny"), [("sfx", "snore_dog")])

    def test_bracket_words_trigger_recordings_and_unknown_labels_are_not_read(self):
        self.assertEqual(seg("Great [laughs] job"), [("say", "Great"), ("sfx", "giggle"), ("say", "job")])
        self.assertEqual(seg("(sighs) okay"), [("sfx", "sigh"), ("say", "okay")])
        self.assertEqual(seg("*yawns* bedtime"), [("sfx", "yawn"), ("say", "bedtime")])
        self.assertEqual(seg("[cough] hello"), [("say", "hello")])   # no recording for a cough: silently dropped
        self.assertEqual(seg("[inaudible]"), [])

    def test_real_words_are_left_alone(self):
        for t in ("I can have a giggle!", "Four (4) apples", "the answer is (a)", "What about the highway, hon?",
                  "She said hello and left", "Hi, I am Hal"):
            self.assertFalse(S.affects(t), t)
            self.assertEqual(seg(t), [("say", t)])

    def test_affects_flags_text_that_needs_the_mixer(self):
        for t in ("Hee hee!", "zzz", "[snoring]", "Honk!", "Yawn... ok"):
            self.assertTrue(S.affects(t), t)

    def test_gemma_menu_hides_sleep_only_snores(self):
        s = Fake()
        s.index["knock"] = {}
        s.pcm["knock"] = b"\0\0"
        self.assertNotIn("snore", s.prompt_list())

    def test_shipped_lines_have_no_spelled_noises_left_unmapped(self):
        # every scripted line that spells a noise is now routed through the mixer
        for ev, per in scripted.IMU_LOCAL.items():
            for toy, text in per.items():
                if any(w in text.lower() for w in ("zzz", "hee hee", "yawn")):
                    self.assertTrue(S.affects(text), (ev, toy, text))


class TranscriptTests(unittest.TestCase):
    def test_nonspeech_is_dropped_and_labelled(self):
        for raw, label in (("(snoring)", "snoring"), ("[BLANK_AUDIO]", "blank audio"), ("*coughs*", "coughs"), ("zzz zzz", "snoring"),
                           ("[laughter]", "laughing"), ("(yawning)", "yawning"), ("heavy breathing", None)):
            text, labels = nonspeech.strip_annotations(raw)
            if label:
                self.assertEqual(text, "", raw)
                self.assertIn(label, labels, raw)

    def test_speech_survives_and_annotations_are_removed_from_it(self):
        self.assertEqual(nonspeech.strip_annotations("why is the sky blue")[0], "why is the sky blue")
        self.assertEqual(nonspeech.strip_annotations("[laughs] why is the sky blue (snoring)")[0], "why is the sky blue")
        self.assertEqual(nonspeech.strip_annotations("what is 4 (four) plus 4")[0], "what is 4 (four) plus 4")

    def test_hums_alone_are_not_words(self):
        for t in ("mmm", "hmm...", "uh", "ahh"):
            self.assertEqual(nonspeech.strip_annotations(t)[0], "", t)
        self.assertEqual(nonspeech.strip_annotations("hmm I think so")[0], "hmm I think so")


if __name__ == "__main__":
    unittest.main()
