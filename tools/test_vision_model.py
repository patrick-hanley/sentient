"""Vision backends: factory, lazy imports, failure -> "" (no models, no network: fakes)."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from brain import vision_model as vm  # noqa: E402
sys.path.insert(0, str(ROOT / "tools"))
import vision_bench as vb  # noqa: E402


class FakeResp:
    def __init__(self, text): self.data = json.dumps({"choices": [{"message": {"content": "  " + text + " \n"}}]}).encode()
    def read(self, *a): d, self.data = self.data, b""; return d
    def __enter__(self): return self
    def __exit__(self, *a): pass


class Factory(unittest.TestCase):
    def test_gemma_and_off_mean_no_separate_model(self):
        for k in ("gemma", "GEMMA", "none", "off", "", "no-such-model"):
            self.assertIsNone(vm.make_vision(k), k)

    def test_default_comes_from_config(self):
        from brain import config
        with mock.patch.object(config, "VISION_MODEL", "llamacpp"):
            self.assertIsInstance(vm.make_vision(None), vm.LlamaCppVision)
        self.assertEqual(config.VISION_MODEL, "gemma")

    def test_backends_construct_without_heavy_deps(self):
        self.assertIsInstance(vm.make_vision("llamacpp"), vm.VisionModel)
        f = vm.make_vision("florence")
        self.assertIsInstance(f, vm.FlorenceVision)
        self.assertIsNone(f._m)  # nothing loaded until the first describe()


class LlamaCpp(unittest.TestCase):
    def test_posts_image_and_default_question(self):
        with mock.patch("urllib.request.urlopen", return_value=FakeResp("A red cup.")) as op:
            out = vm.LlamaCppVision("http://x:1/").describe(b"\xff\xd8jpeg")
        self.assertEqual(out, "A red cup.")
        req = op.call_args.args[0]
        self.assertEqual(req.full_url, "http://x:1/v1/chat/completions")
        parts = json.loads(req.data)["messages"][0]["content"]
        self.assertTrue(parts[0]["image_url"]["url"].startswith("data:image/jpeg;base64,"))
        self.assertEqual(parts[1]["text"], vm.DEFAULT_QUESTION)

    def test_custom_question_and_server_down(self):
        with mock.patch("urllib.request.urlopen", return_value=FakeResp("x")) as op:
            vm.LlamaCppVision().describe(b"j", "What colour?")
        self.assertEqual(json.loads(op.call_args.args[0].data)["messages"][0]["content"][1]["text"], "What colour?")
        with mock.patch("urllib.request.urlopen", side_effect=OSError("down")):
            self.assertEqual(vm.LlamaCppVision().describe(b"j"), "")

    def test_florence_missing_deps_returns_empty(self):
        with mock.patch.dict(sys.modules, {"torch": None}):
            self.assertEqual(vm.FlorenceVision().describe(b"j"), "")


class Scoring(unittest.TestCase):
    def test_hit_matching(self):
        e = {"label": "mug", "synonyms": ["mug", "cup"]}
        self.assertTrue(vb.hit("It is a white Cup!", e))
        self.assertTrue(vb.hit("A mug.", e))
        self.assertFalse(vb.hit("A mugwort plant", {"label": "bug", "synonyms": []}))
        self.assertFalse(vb.hit("A bowl.", e))

    def test_manifest_is_complete(self):
        m = json.load(open(ROOT / "tools/vision_set/manifest.json"))["images"]
        self.assertGreaterEqual(len(m), 32)
        for i in m:
            self.assertTrue((ROOT / "tools/vision_set" / i["file"]).exists())
            self.assertTrue(i["label"] and i["synonyms"] and i["source"].startswith("http") and i["license"])

    def test_run_model_with_fake_runner(self):
        class R:
            def describe(self, jpeg, p): return "A banana." if b"" == b"" else ""
            def peak_rss(self): return 5 * 2**20
            def close(self): pass
        args = mock.Mock(prompt="q")
        spec = {"kind": "gguf", "label": "fake", "params": "1B"}
        with mock.patch.dict(vb.MODELS, {"fake": spec}), mock.patch.object(vb, "GgufRunner", return_value=R()):
            ent = json.load(open(ROOT / "tools/vision_set/manifest.json"))["images"][:3]
            r = vb.run_model("fake", ent, args)
        self.assertEqual(r["n"], 3)
        self.assertEqual(r["peak_rss_mb"], 5)
        self.assertIn("| fake |", vb.table([r], "test"))


if __name__ == "__main__":
    unittest.main()
