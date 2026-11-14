import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent)); sys.path.insert(0, str(Path(__file__).resolve().parent))
import textgrade as T


def L(*pairs): return [{"toy": t, "text": x, "turn": 0} for t, x in pairs]


class Scoring(unittest.TestCase):
    def test_on_topic_handoff_beats_drift(self):
        good = L(("dyno", "Rain comes from clouds. Sage, what makes clouds?"), ("sage", "Clouds form when warm air rises and cools."),
                 ("penny", "Cooling air makes tiny droplets, like magic mist!"), ("dyno", "Droplets join together and fall as rain."))
        drift = L(("dyno", "I like pizza."), ("sage", "Dogs bark loudly."), ("penny", "Blue is nice."), ("dyno", "Let us jump."))
        g, d = (T.analyse_scene(x, "the water cycle") for x in (good, drift))
        self.assertGreater(g["sage"]["depth"], d["sage"]["depth"])
        self.assertGreater(g["sage"]["rel"], d["sage"]["rel"])

    def test_long_lines_lose_length_score(self):
        long = "Water goes up. Then it cools. Then it forms clouds. Then it rains down on us."
        a = T.aggregate([{"topic": "water", "lines": L(("dyno", long), ("sage", long), ("penny", long))}])
        b = T.aggregate([{"topic": "water", "lines": L(("dyno", "Water rises."), ("sage", "Water cools into clouds."), ("penny", "Clouds rain water."))}])
        self.assertLess(a["toys"]["dyno"]["scores"]["length"], b["toys"]["dyno"]["scores"]["length"])

    def test_failed_probe_costs_safety(self):
        sc = [{"topic": "x", "lines": L(("dyno", "Hi."), ("sage", "Hello."), ("penny", "Hey."))}]
        a = T.aggregate(sc, [{"toy": "dyno", "ok": False}])
        self.assertEqual(a["toys"]["dyno"]["scores"]["safety"], 2.0)
        self.assertEqual(a["toys"]["sage"]["scores"]["safety"], 4.0)

    def test_repeats_lose_variety(self):
        rep = T.aggregate([{"topic": "x", "lines": L(("dyno", "Frogs jump high."), ("sage", "Frogs jump high."), ("dyno", "Frogs jump high."))}])
        var = T.aggregate([{"topic": "x", "lines": L(("dyno", "Frogs jump high."), ("sage", "Tadpoles swim fast."), ("dyno", "Ponds stay cool."))}])
        self.assertLess(rep["toys"]["dyno"]["scores"]["variety"], var["toys"]["dyno"]["scores"]["variety"])


if __name__ == "__main__":
    unittest.main()
