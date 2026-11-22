"""Barge-in detector: a voice clearly louder than the talking toy's leakage cuts in; leakage alone never does."""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from brain.barge import BargeDetector  # noqa: E402


def frame(rms, rng):
    x = rng.normal(0, 1, 320)
    return (x / x.std() * rms).astype("<i2")


class BargeTests(unittest.TestCase):
    def setUp(self):
        self.d = BargeDetector()
        self.d.vad.is_speech = lambda *a, **k: True    # the energy logic is under test, not webrtcvad
        self.rng = np.random.default_rng(1)

    def run_seq(self, levels):
        for i, lv in enumerate(levels):
            r = self.d.feed("sage", frame(lv, self.rng), 1)
            if r:
                return i, r
        return None, None

    def test_leakage_alone_never_triggers(self):
        lv = [120] * 50 + [200] * 50 + [90] * 50 + [250] * 100   # a toy's own syllables leaking into the next mic
        i, _ = self.run_seq(lv)
        self.assertIsNone(i)

    def test_child_over_leakage_triggers_within_a_fraction_of_a_second(self):
        lv = [150] * 60 + [1500] * 60
        i, frames = self.run_seq(lv)
        self.assertIsNotNone(i)
        self.assertLess((i - 60) * 0.02, 0.3)
        self.assertEqual(len(frames), 50)    # the start of the speech (1 s) is kept in RAM for the segmenter

    def test_short_bump_does_not_trigger(self):
        i, _ = self.run_seq([150] * 60 + [1500] * 4 + [150] * 60)
        self.assertIsNone(i)

    def test_toys_own_first_words_after_a_quiet_start_do_not_cut_it(self):
        # 0.4 s of nothing (network, speaker start-up, Sage's lead-in silence), then the toy's own speech in the next mic
        for quiet in (5, 12, 20, 30, 45):
            self.setUp()
            i, _ = self.run_seq([10] * quiet + [600] * 200)
            self.assertIsNone(i, f"cut itself after {quiet * 20} ms of quiet")

    def test_child_still_cuts_in_after_a_quiet_start(self):
        i, _ = self.run_seq([10] * 20 + [600] * 60 + [2400] * 40)
        self.assertIsNotNone(i)
        self.assertLess((i - 80) * 0.02, 0.3)

    def test_child_over_a_far_quiet_toy_still_cuts_in(self):
        i, _ = self.run_seq([15] * 20 + [45] * 80 + [900] * 40)     # the toy never rises above the onset level
        self.assertIsNotNone(i)
        self.assertLess((i - 100) * 0.02, 0.3)

    def test_quiet_voice_below_floor_ignored(self):
        i, _ = self.run_seq([20] * 60 + [200] * 60)
        self.assertIsNone(i)


if __name__ == "__main__":
    unittest.main()
