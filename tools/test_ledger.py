import json, sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent)); sys.path.insert(0, str(Path(__file__).resolve().parent))
import grade_ledger as GL
import grade_toys as G


class Ledger(unittest.TestCase):
    def test_build_and_render_stub_run(self):
        run = G.run_batch("tune", G.StubToyLLM(), n_per=1, log=lambda *_: None)
        run["label"], run["model"], run["toytalk"] = "t", "stub", 0
        base = GL.build(run, "b", None, "x", "")
        rec = GL.build(run, "r", {"label": "b", "agg": base["agg"]}, "x", "n")
        self.assertEqual(rec["decision"].split(":")[0], "revert")           # identical run: no gain
        self.assertTrue(all(l["points"] >= 0 for s in rec["scenes"] for l in s["lines"]))
        md = GL.render_page(rec, base)
        self.assertIn("baseline (scene", md)
        json.dumps(rec)                                                     # serialisable, one JSONL line


if __name__ == "__main__":
    unittest.main()
