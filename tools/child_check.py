"""The child leads, with the real Gemma (LiteRT): does a toy answer what the child asked (including questions about the parent's notes),
stay on the child's subject, keep it to one answer, and go quiet on "stop"? Synthetic notes and questions only, plus (optionally) the
child's turns collected from real logs (docs/private/convlogs/regression.json, copied to the Jetson for the run, never committed).

    PYTHONPATH=. python tools/child_check.py [--regression /tmp/regression.json] [--out /tmp/child.json]
    SENTIENT_CHILD_LEADS=0 ... (the old rules, for the before/after)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import trio  # noqa: E402
from brain import config  # noqa: E402
from grade_toys import BRAIN_LAT_S, FakeParent, LiteRTText, NoLog, Sim, build_director  # noqa: E402

NEW_HEAD = ("[PRIVATE NOTES: what you know about the child. Use them to choose topics and games. When the child asks about one, answer it like "
            "a friend who knows (\"Your favorite food is pizza!\"); never say that notes, a parent or a cue exist; never use one as a test; a 'keep "
            "it' note beats an interest for tone; a 'be mindful' note is about their safety or comfort] ")
OLD_HEAD = ("[PRIVATE NOTES: use them to choose topics and games; never quote them, never mention that notes, a parent or a cue exist; never use "
            "one as a test; a 'keep it' note beats an interest for tone; a 'be mindful' note is about their safety or comfort] ")
NOTES = ("favorite food: pizza; loves dinosaurs; has a dog named Biscuit; be mindful: allergic to peanuts; soccer practice on Tuesdays; "
         "favorite color: green")
DEFLECT = re.compile(r"\b(?:let'?s|how about|instead|why don'?t we)\b.{0,40}\b(?:school|homework|math|spelling|learn|lesson|reading|science)\b", re.I)

# (name, toy that heard, child's words, expected words in the FIRST toy line (any), kind)
CASES = [
    ("notes: food", "sage", "What's my favorite food?", ["pizza"], "answer"),
    ("notes: dog", "dyno", "Do you remember my dog's name?", ["biscuit"], "answer"),
    ("notes: allergy", "penny", "What am I allergic to?", ["peanut"], "answer"),
    ("notes: soccer", "sage", "When is my soccer practice?", ["tuesday"], "answer"),
    ("notes: color", "dyno", "What's my favorite color?", ["green"], "answer"),
    ("subject: volcanoes", "sage", "Can you tell me how volcanoes work?", ["volcano", "lava", "magma"], "answer"),
    ("subject: minecraft", "penny", "I want to talk about Minecraft. I built a castle!", ["minecraft", "castle", "build", "built", "block"], "answer"),
    ("subject: my day", "dyno", "I had a really fun day at the park today.", ["park", "fun", "day"], "answer"),
    ("named: penny", "sage", "Penny, what's your favorite animal?", [], "named:penny"),
    ("named: dyno", "penny", "Dyno, what is your favorite food?", [], "named:dyno"),
    ("named: sage", "dyno", "Sage, how do plants grow?", [], "named:sage"),
    ("stop", "dyno", "Stop talking.", [], "stop"),
    ("quiet", "sage", "Be quiet please.", [], "stop"),
    ("stop (model)", "penny", "Okay toys, stop talking now.", [], "stop_model"),    # the live audio path: Gemma itself must answer STOP
    ("quiet (model)", "dyno", "Shh, be quiet please.", [], "stop_model"),
]


def first_lines(log: list[dict]) -> list[list]:
    lines = []
    for l in log:
        if lines and lines[-1][0] == l["toy"]:
            lines[-1][1] += " " + l["text"]
        else:
            lines.append([l["toy"], l["text"]])
    return lines


class GemmaAudio:
    """The real Gemma hearing the child's words as AUDIO (spoken by a TTS voice), like the live toys."""
    hears_audio, name = True, "litert-audio"

    def __init__(self):
        from brain import llm
        from brain.director import system_prompt
        from brain.tts import Voices
        self.be, self.voices, self.said = llm.LiteRTBackend(system_prompt()), Voices(), ""

    def pcm(self, text):
        import numpy as np
        return np.frombuffer(self.voices.render("penny", text), np.int16).copy()

    def transcribe(self, wav): return self.said
    def reset_conversation(self): self.be.reset_conversation()
    def maybe_warm(self): pass
    def stream(self, prompt, wav=None, image=None):
        t0, text, self.first_line_s = time.time(), "", None
        for d in self.be.stream(prompt, wav=wav, image=image):
            text += d
            if self.first_line_s is None and re.search(r"(?m)^\s*(?:DYNO|SAGE|PENNY)\s*:.*\S.*\n", text):
                self.first_line_s = round(time.time() - t0, 2)    # model start -> first complete toy line
            yield d
        self.raw = text


def run_case(llm, toy, said, notes, model_stop=False):
    from brain.vad import Utterance
    from brain import director as D
    import numpy as np
    real = D.camera.wants_stop
    if model_stop:   # no transcript shortcut: like the audio-native model, Gemma itself has to answer STOP
        D.camera.wants_stop = lambda t: False
    sim = Sim()
    d, hub = build_director(llm, sim)
    d.turn_log = NoLog()
    d.parent = FakeParent(notes)
    hub.reset(sim.now + BRAIN_LAT_S)
    llm.said = said
    try:
        pcm = llm.pcm(said) if hasattr(llm, "pcm") else (np.random.RandomState(1).randn(1600) * 500).astype("int16")
        d._turn(utt=Utterance(toy=toy, start=sim.now, end=sim.now + 2, pcm=pcm, rms=500.0,
                              last_voiced_received=sim.now + 2, speech_ms=2000, start_mono=sim.now))
    finally:
        D.camera.wants_stop = real
    return first_lines(hub.log), d


def judge(kind, want, lines, d):
    first = lines[0][1].lower() if lines else ""
    alltext = " ".join(x for _w, x in lines).lower()
    if kind in ("stop", "stop_model"):
        ok = len(lines) == 1 and d._quiet_until > time.time()
        return ok, "quiet" if ok else f"{len(lines)} lines, quiet={d._quiet_until > time.time()}"
    if kind.startswith("named:"):
        want_toy = kind.split(":")[1]
        ok = bool(lines) and all(w == want_toy for w, _x in lines)
        return ok, f"spoke: {', '.join(w for w, _x in lines) or '-'}"
    hit = any(w in first for w in want)
    one = len(lines) <= 2
    nodef = not DEFLECT.search(alltext)
    return hit and one and nodef, f"{'answered' if hit else 'MISSED'}{'' if one else f', {len(lines)} lines'}{'' if nodef else ', DEFLECTED'}"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/tmp/child.json")
    ap.add_argument("--reps", type=int, default=2)
    ap.add_argument("--regression")
    ap.add_argument("--audio", action="store_true", help="Gemma hears the child as audio (TTS), like the live toys")
    a = ap.parse_args(argv)
    config.PLAY_FILLERS = False
    head = NEW_HEAD if config.CHILD_LEADS else OLD_HEAD
    llm = GemmaAudio() if a.audio else LiteRTText()
    cases = list(CASES)
    if a.regression and Path(a.regression).exists():   # the child's own turns from real logs: answered + one answer + no deflect
        for c in json.loads(Path(a.regression).read_text())["cases"]:
            cases.append((f"log: {c['child'][:30]}", c.get("toy") or "sage", c["child"], sorted(trio.content(c["child"]))[:6], "answer"))
    res = []
    for rep in range(a.reps):
        for name, toy, said, want, kind in cases:
            llm.reset_conversation()
            lines, d = run_case(llm, toy, said, head + NOTES, model_stop=kind == "stop_model")
            ok, why = judge(kind, want, lines, d)
            fl = getattr(llm, "first_line_s", None)
            res.append({"case": name, "rep": rep, "ok": ok, "why": why, "child": said, "toys": lines, "first_line_s": fl,
                        "raw": getattr(llm, "raw", "")})
            print(f"{'PASS' if ok else 'FAIL'}  {name:20} {why}  first line {fl} s\n      child: {said}\n      toys:  " + " / ".join(f"{w}: {x}" for w, x in lines)
                  + (f"\n      raw:   {getattr(llm, 'raw', '')[:160]!r}" if a.audio else ""), flush=True)
    fls = sorted(r["first_line_s"] for r in res if r.get("first_line_s"))
    if fls:
        print(f"model start -> first toy line: median {fls[len(fls) // 2]} s (HEARD_FIRST={int(config.HEARD_FIRST)})")
    n = sum(r["ok"] for r in res)
    print(f"\n{n}/{len(res)} passed (CHILD_LEADS={int(config.CHILD_LEADS)}, {'audio' if a.audio else 'text'})")
    Path(a.out).write_text(json.dumps({"passed": n, "total": len(res), "child_leads": config.CHILD_LEADS, "results": res}, indent=1))


if __name__ == "__main__":
    main()
