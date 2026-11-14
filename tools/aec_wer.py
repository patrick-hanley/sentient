#!/usr/bin/env python3
"""Score an /aec_trial dump (SENTIENT_AEC_DUMP): does listener B hear the child (toy C) through toy A's voice?

  (on the Mac, after scp from the Jetson)  python tools/aec_wer.py aec_dyno_sage_*.npz [--model DIR]

Window = frames arriving while the child clip plays. Transcribes the raw mic and the canceller's output with faster-whisper and
prints WER against the true child text, plus how many of A's words leak into the transcript. Needs the notes the /aec_trial
endpoint stores. RAM only: nothing is written."""
import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MODEL = "/Users/patrickhanley/Downloads/sentient/offline/faster-whisper-base.en"
_model = None
BEAM = 1                      # decoding beam; 5 is a cross-check that a WER difference is not a one-word decoding flip


def words(t):
    return re.findall(r"[a-z0-9']+", t.lower())


def wer(ref, hyp):
    r, h = words(ref), words(hyp)
    d = list(range(len(h) + 1))
    for i in range(1, len(r) + 1):
        prev, d[0] = d[0], i
        for j in range(1, len(h) + 1):
            cur = min(d[j] + 1, d[j - 1] + 1, prev + (r[i - 1] != h[j - 1]))
            prev, d[j] = d[j], cur
    return d[len(h)] / max(len(r), 1)


def transcribe(pcm, model_dir):
    global _model
    if _model is None:
        from faster_whisper import WhisperModel
        _model = WhisperModel(model_dir, device="cpu", compute_type="int8")
    x = pcm.astype(np.float32) / 32768.0
    segs, _ = _model.transcribe(x, language="en", beam_size=BEAM, vad_filter=False, condition_on_previous_text=False)
    return " ".join(s.text.strip() for s in segs)


def score(path, model_dir):
    z = np.load(path, allow_pickle=False)
    notes = json.loads(str(z["notes"]))
    if "child_t" not in notes:
        return None
    arr, mic = z["arr"], z["mic"]
    out = z["out"] if "out" in z.files else mic
    t0, t1 = notes["child_t"], notes["child_t"] + notes["child_dur"] + 1.0
    sel = np.where((arr >= t0) & (arr <= t1))[0]
    if len(sel) < 10:
        return dict(error="window has too few frames", frames=len(sel))
    a, b = sel[0] * 320, (sel[-1] + 1) * 320
    res = {}
    for name, sig in (("raw mic", mic[a:b]), ("canceller out", out[a:b])):
        hyp = transcribe(sig, model_dir)
        aw, hw = set(words(notes["atext"])) - set(words(notes["ctext"])), words(hyp)
        res[name] = dict(wer=round(wer(notes["ctext"], hyp), 2), leak=round(sum(w in aw for w in hw) / max(len(hw), 1), 2),
                         rms=int(np.sqrt(np.mean(sig.astype(float) ** 2))), heard=hyp)
    res["pair"] = f"{notes['a']} talks, {Path(path).stem.split('_')[2]} listens, {notes['c']} is the child"
    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    a = ap.parse_args()
    for f in a.files:
        r = score(f, a.model)
        print(json.dumps(r) if r else f"{f}: no child notes")
