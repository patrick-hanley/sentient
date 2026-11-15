"""I spy with the real Gemma (LiteRT) and toy-camera-quality photos (tools/vision_set): do the toys guess from what is in the picture,
say honestly when nothing matches, and play their own turn from the picture? Runs on the Jetson (needs litert_lm and the model):

    PYTHONPATH=. python tools/ispy_check.py [--out /tmp/ispy.json]

The Director runs for real (prompts, camera policy, parser, fact guard); only the hub (camera = a file), voices and the transcript are
fakes. Nothing is recorded or stored except the result file (the toys' lines, no audio, no camera frames).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import threading
import time
import types
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from brain import config, teach  # noqa: E402

SET = HERE / "vision_set"
HONEST = re.compile(r"\b(?:don'?t|do not|can'?t|cannot|didn'?t)\s+(?:see|spot|find)\b|\bnothing\b|\bno\s+\w+\s+(?:things?|here)\b|\bhint\b|\bclue\b|\bcloser\b", re.I)


class Hub:
    def __init__(self, frame: bytes | None):
        self.frame, self.captures, self.talking = frame, [], None
        self.response_active = threading.Event()
        self.atoms = {t: types.SimpleNamespace(cam=True) for t in config.TOY_ORDER}

    def online(self): return list(config.TOY_ORDER)
    def capture(self, toy, timeout=3.0, force=False):
        self.captures.append(toy)
        return self.frame
    def play(self, toy, pcm, *, on_dispatch=None, raise_on_error=False):
        if on_dispatch:
            on_dispatch()
        return .01
    def play_line(self, toy, text, voices, **kw): return self.play(toy, voices.render(toy, text), **kw)


class Voices:
    def __init__(self): self.said = []
    def render(self, toy, text):
        self.said.append((toy, text))
        return b"\0\0" * 160


class Rec:
    gallery = staticmethod(lambda: teach.EMPTY)
    def analyze(self, img, own_toy=None): return []


class Gemma:
    """Text in (the transcript), picture attached, text out; keeps the raw reply so the SECRET line can be checked."""
    hears_audio, name = False, "litert"

    def __init__(self):
        from brain import llm
        from brain.director import system_prompt
        self.be, self.said, self.raw = llm.LiteRTBackend(system_prompt()), "", ""

    def transcribe(self, wav): return self.said

    def complete(self, prompt, system, image=None, max_tokens=200):
        out = self.be.complete(prompt, system, image=image, max_tokens=max_tokens)
        self.raw += f"[list: {out.strip()}] "
        return out
    def reset_conversation(self): self.be.reset_conversation()
    def maybe_warm(self): pass

    def stream(self, prompt, wav=None, image=None):
        for d in self.be.stream(prompt, image=image):
            self.raw += d
            yield d


def turn(d, voices, model, toy, said):
    from brain.vad import Utterance
    model.said, model.raw = said, ""
    n = len(voices.said)
    now = time.monotonic()
    d._turn(utt=Utterance(toy, time.time() - 1, time.time(), np.ones(16000, np.int16), 5000, now - .5, now))
    return " ".join(t for _w, t in voices.said[n:]), model.raw


CASES = [  # (name, image file or None, toy, child turns, check)
    ("red -> apple", "00_apple.jpg", "sage", ["I spy with my little eye something red"], "guess:apple"),
    ("yellow -> banana", "02_banana.jpg", "dyno", ["I spy something yellow"], "guess:banana"),
    ("blue -> blueberries", "03_blueberries.jpg", "penny", ["I spy something blue"], "guess:berr"),
    ("orange -> orange", "17_orange.jpg", "sage", ["I spy with my little eye something orange"], "guess:orange"),
    ("yellow -> duck", "22_rubber_duck.jpg", "penny", ["I spy something yellow"], "guess:duck"),
    ("purple, not there", "00_apple.jpg", "dyno", ["I spy something purple"], "honest"),
    ("blue, not there", "02_banana.jpg", "sage", ["I spy with my little eye something blue"], "honest"),
    ("dead camera", None, "dyno", ["I spy something red"], "honest"),
    ("no -> no repeat", "00_apple.jpg", "sage", ["I spy something red", "No, guess again!"], "norepeat:apple"),
    ("toy's turn", "22_rubber_duck.jpg", "penny", ["Let's play I spy! Your turn to spy, Penny."], "secret:duck"),
]


def check(kind: str, said: list[str], raw: list[str], secret: str | None = None) -> tuple[bool, str]:
    k, _, arg = kind.partition(":")
    last = said[-1].lower()
    if k == "guess":
        ok = arg in last and "?" in last and not HONEST.search(last)
        return ok, f"guessed {'the ' + arg if ok else 'something else'}"
    if k == "honest":
        claims = re.search(r"\bis it (?:the |a |an )?\w+", last)
        return bool(HONEST.search(last)), "said honestly it can't see one / asked for a hint" if HONEST.search(last) else f"no honest no ({claims.group(0) if claims else 'no guess'})"
    if k == "norepeat":
        first_hit = arg in said[0].lower()
        repeated = any(arg in q.lower() for q in re.findall(r"[^.!?]*\?", last))     # a question (= a guess) naming the same thing again
        return first_hit and not repeated, ("repeated the first guess" if repeated else "second guess did not repeat the first") if first_hit else "first guess missed"
    if k == "secret":
        sec = secret or ""
        return bool(arg in sec.lower() and "i spy" in last and "secret" not in last), f"spied {sec or 'nothing'}"
    return False, "?"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/tmp/ispy.json")
    ap.add_argument("--reps", type=int, default=1)
    a = ap.parse_args(argv)
    from brain import director as D
    from brain.perception import Perceiver
    config.PLAY_FILLERS = False
    model = Gemma()
    results = []
    for rep in range(a.reps):
        for name, img, toy, turns, kind in CASES:
            frame = (SET / img).read_bytes() if img else None
            hub, voices = Hub(frame), Voices()
            d = D.Director(hub, voices, Perceiver(hub, Rec()), model, {})
            d.turn_log = types.SimpleNamespace(add=lambda x: x)
            model.reset_conversation()
            said, raw = [], []
            secs = []
            for t in turns:
                t0 = time.time()
                s, r = turn(d, voices, model, toy, t)
                secs.append(round(time.time() - t0, 1))
                said.append(s)
                raw.append(r)
            ok, why = check(kind, said, raw, d._ispy_secret)
            results.append({"case": name, "rep": rep, "image": img, "child": turns, "toys": said, "raw": raw, "ok": ok, "why": why, "pictures": len(hub.captures), "turn_s": secs})
            print(f"{'PASS' if ok else 'FAIL'}  {name:22} pictures {len(hub.captures)} turn {secs} s  {why}\n      child: {' / '.join(turns)}\n      toys:  {' / '.join(said)}\n      raw:   {' / '.join(r.replace(chr(10), ' | ') for r in raw)}",
                  flush=True)
    n = sum(r["ok"] for r in results)
    print(f"\n{n}/{len(results)} passed")
    Path(a.out).write_text(json.dumps({"passed": n, "total": len(results), "results": results}, indent=1))


if __name__ == "__main__":
    main()
