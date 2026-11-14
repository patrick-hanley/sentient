#!/usr/bin/env python3
"""Replay recorded trials (aec_corpus.py dumps) through the canceller offline, with config/module overrides, and score them:
ERLE (the brain's own per-clip number), WER of the canceller output against the child's true text, leakage of the talker's words.
  python tools/aec_replay.py CORPUS_DIR [NAME=VALUE ...]     names are brain.config.* or brain.aec.* attributes"""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import aec_wer  # noqa: E402
from brain import aec, config  # noqa: E402

FS, B = 16000, 320


def replay(path, overrides=None):
    """Returns (erle_db or None, canceller output frames as one int16 array, the dump)."""
    saved = {}
    for k, v in (overrides or {}).items():
        mod = aec if hasattr(aec, k) else config
        saved[(mod, k)] = getattr(mod, k)
        setattr(mod, k, v)
    try:
        z = np.load(path, allow_pickle=False)
        a_toy, b_toy = Path(path).name.split("_")[:2]
        ns, mic, ref = z["ns"], z["mic"], z["ref"]
        cap = z["cap"] if "cap" in z.files else np.full(len(ns), -1.0)
        t0, dispatch = float(z["t0"]), float(z["dispatch"])
        m = aec.AecManager()
        m.dump_dir = None
        m.begin(a_toy, ref, dispatch)
        playing = played = False
        outs, lines = [], []
        end = t0 + len(ref) / FS
        for i in range(len(ns)):
            t = cap[i] if cap[i] > 0 else z["arr"][i]
            if not playing and t0 > 0 and t >= t0:
                m.playing(a_toy, t0)
                playing = True
            if not played and t >= end:
                m.played(a_toy, end)
                played = True
            o = m.feed(b_toy, mic[i * B:(i + 1) * B], int(ns[i] // B) & 0xFFFF, float(z["arr"][i]), float(cap[i]) if cap[i] > 0 else None)
            outs.append(o.pcm if o.cancelling else mic[i * B:(i + 1) * B])
        lines = m.finish(a_toy)
        erle = None
        for ln in lines:
            if f"{a_toy}->{b_toy}" in ln and "ERLE" in ln:
                erle = float(ln.split("ERLE ")[1].split(" dB")[0])
        return erle, np.concatenate(outs).astype(np.int16), z
    finally:
        for (mod, k), v in saved.items():
            setattr(mod, k, v)


def score(corpus, overrides=None, model=aec_wer.DEFAULT_MODEL):
    erles, wers, leaks, rows = [], [], [], []
    for f in sorted(Path(corpus).glob("*.npz")):
        erle, out, z = replay(f, overrides)
        notes = json.loads(str(z["notes"]))
        arr = z["arr"]
        sel = np.where((arr >= notes["child_t"]) & (arr <= notes["child_t"] + notes["child_dur"] + 1.0))[0]
        if len(sel) < 10:
            continue
        hyp = aec_wer.transcribe(out[sel[0] * B:(sel[-1] + 1) * B], model)
        aw, hw = set(aec_wer.words(notes["atext"])) - set(aec_wer.words(notes["ctext"])), aec_wer.words(hyp)
        w = aec_wer.wer(notes["ctext"], hyp)
        lk = sum(x in aw for x in hw) / max(len(hw), 1)
        if erle is not None:
            erles.append(erle)
        wers.append(w)
        leaks.append(lk)
        rows.append((f.name[:20], erle, round(w, 2), round(lk, 2)))
    return dict(erle=float(np.mean(erles)) if erles else None, wer=float(np.mean(wers)), leak=float(np.mean(leaks)), n=len(wers), rows=rows)


if __name__ == "__main__":
    ov = {}
    for kv in sys.argv[2:]:
        k, v = kv.split("=")
        ov[k] = float(v) if "." in v or "e" in v else int(v)
    r = score(sys.argv[1], ov)
    for row in r["rows"]:
        print(row)
    print({k: (round(v, 3) if isinstance(v, float) else v) for k, v in r.items() if k != "rows"})
