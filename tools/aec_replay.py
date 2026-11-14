#!/usr/bin/env python3
"""Replay recorded trials (aec_corpus.py dumps) through the canceller offline, with config/module overrides, and score them.

A corpus holds sequences: two consecutive clips of the same talker heard by the same listener (files A_B_C_TAG_0.npz, _1.npz).
A sequence is replayed through ONE AecManager, so the second clip starts with the filter the first one left (warm start). The
silence between the clips (the dumps only hold frames while a clip plays) is filled with the first clip-free frames of the file.

Metrics per clip (all on what the canceller hands on, `out`; "raw" is the mic itself):
  onset ERLE    first 1.0 s of A's speech at the mic: 10 log10(sum mic^2 / sum out^2)   (cold = first clip, warm = second)
  A-only ERLE   the rest of A's clip while the child is silent
  A-only leak   share of A's words (what whisper hears in the clean reference over the same stretch) that whisper still hears in
                the output when the child is silent. Target 0.
  child WER     whisper on the output while the child speaks, against the child's true text. Must not get worse.
  python tools/aec_replay.py CORPUS_DIR [NAME=VALUE ...]     names are brain.config.* or brain.aec.* attributes"""
import collections
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import aec_wer  # noqa: E402
from brain import aec, config  # noqa: E402

FS, B = 16000, 320


def sequences(corpus):
    """{(a, b, c, tag): [files in clip order]}"""
    seq = collections.defaultdict(list)
    for f in sorted(Path(corpus).glob("*.npz")):
        a, b, c, tag, k = f.stem.split("_")
        seq[(a, b, c, tag)].append(f)
    return seq


def replay_seq(files, overrides=None):
    """Returns one dict per clip: mic, out (int16 arrays over that file's frames), z (the dump), k."""
    saved = {}
    for k, v in (overrides or {}).items():
        mod = aec if hasattr(aec, k) else config
        saved[(mod, k)] = getattr(mod, k)
        setattr(mod, k, v)
    try:
        a_toy, b_toy = Path(files[0]).name.split("_")[:2]
        m = aec.AecManager()
        m.dump_dir = None
        res, fill = [], None
        last_n = None
        for k, path in enumerate(files):
            z = np.load(path, allow_pickle=False)
            ns, mic, ref = z["ns"], z["mic"], z["ref"]
            cap = z["cap"] if "cap" in z.files else np.full(len(ns), -1.0)
            arr = z["arr"]
            t0, dispatch = float(z["t0"]), float(z["dispatch"])
            if fill is None:
                fill = mic[:15 * B]                                   # ambient frames from before the clip
            if last_n is not None:                                    # bridge the silent stretch between the clips
                gap = int(ns[0] // B) - int(last_n // B) - 1
                for j in range(max(gap, 0)):
                    m.feed(b_toy, fill[(j % 15) * B:(j % 15 + 1) * B], (int(last_n // B) + 1 + j) & 0xFFFF, float(arr[0]) - (gap - j) * 0.02,
                           float(cap[0]) - (gap - j) * 0.02 if cap[0] > 0 else None)
            m.begin(a_toy, ref, dispatch)
            playing = played = False
            outs = []
            end = t0 + len(ref) / FS
            for i in range(len(ns)):
                t = cap[i] if cap[i] > 0 else arr[i]
                if not playing and t0 > 0 and t >= t0:
                    m.playing(a_toy, t0)
                    playing = True
                if not played and t >= end:
                    m.played(a_toy, end)
                    played = True
                fr = mic[i * B:(i + 1) * B]
                o = m.feed(b_toy, fr, int(ns[i] // B) & 0xFFFF, float(arr[i]), float(cap[i]) if cap[i] > 0 else None)
                outs.append(o.pcm if (o.cancelling or o.mag) else fr)
            last_n = ns[-1]
            m.finish(a_toy)
            res.append(dict(k=k, mic=mic, out=np.concatenate(outs).astype(np.int16), z=z, a=a_toy, b=b_toy, m=m))
        return res
    finally:
        for (mod, k), v in saved.items():
            setattr(mod, k, v)


def _db(num, den):
    return float(10 * np.log10(max(num, 1e-3) / max(den, 1e-3)))


def _frames(arr, cap, lo, hi):
    t = np.where(cap > 0, cap, arr)
    sel = np.where((t >= lo) & (t < hi))[0]
    return sel


_refcache: dict = {}


def clip_metrics(r, model=aec_wer.DEFAULT_MODEL, key=""):
    """Metrics of one replayed clip (dict); None where the clip has no usable window."""
    z, mic, out = r["z"], r["mic"], r["out"]
    notes = json.loads(str(z["notes"]))
    if "child_t" not in notes:
        return None
    arr = z["arr"]
    cap = z["cap"] if "cap" in z.files else np.full(len(arr), -1.0)
    t = np.where(cap > 0, cap, arr)
    t0, ref = float(z["t0"]), z["ref"].astype(np.float32)
    lag = _lag(r, key)
    on_lo, on_hi = t0 + lag, t0 + lag + 1.0
    end = t0 + lag + len(ref) / FS
    ct0, ct1 = notes["child_t"], notes["child_t"] + notes["child_dur"]
    d = {}

    def erle(sel):
        if len(sel) < 10:
            return None
        sl = np.concatenate([np.arange(i * B, (i + 1) * B) for i in sel])
        return _db(float(np.sum(mic[sl].astype(np.float64) ** 2)), float(np.sum(out[sl].astype(np.float64) ** 2)))

    d["onset_erle"] = erle(_frames(arr, cap, on_lo, on_hi))
    segs = [(on_hi, ct0 - 0.15), (ct1 + 0.5, end - 0.1)]               # A talks, the child does not
    aonly = np.concatenate([_frames(arr, cap, lo, hi) for lo, hi in segs if hi - lo > 0.3] or [np.array([], int)])
    d["aonly_erle"] = erle(aonly)
    # leak: A's words heard in the output over the A-only stretches, against what the clean reference says there
    got = tot = 0
    for lo, hi in segs:
        if hi - lo < 0.8:
            continue
        sel = _frames(arr, cap, lo, hi)
        if len(sel) < 30:
            continue
        a, b = int(sel[0]), int(sel[-1]) + 1
        rs, re_ = int((t[a] - t0 - lag) * FS), int((t[b - 1] + 0.02 - t0 - lag) * FS)
        ck = (key, round(lo, 2))
        if ck not in _refcache:
            _refcache[ck] = aec_wer.words(aec_wer.transcribe(ref[max(rs, 0):re_], model))
        want = collections.Counter(_refcache[ck])
        heard = collections.Counter(aec_wer.words(aec_wer.transcribe(out[a * B:b * B], model)))
        got += sum((want & heard).values())
        tot += sum(want.values())
    d["aonly_leak"] = got / tot if tot else None
    sel = _frames(arr, cap, ct0, ct1 + 1.0)
    d["child_wer"] = aec_wer.wer(notes["ctext"], aec_wer.transcribe(out[int(sel[0]) * B:(int(sel[-1]) + 1) * B], model)) if len(sel) >= 10 else None
    d["rep"] = int(notes.get("rep", r["k"]))
    return d


_lagcache: dict = {}


def _lag(r, key):
    """Echo lag (s) of the clip at this mic, from the raw mic and the reference only (independent of the canceller)."""
    if key not in _lagcache:
        z = r["z"]
        t0 = float(z["t0"])
        arr = z["arr"]
        cap = z["cap"] if "cap" in z.files else np.full(len(arr), -1.0)
        t = np.where(cap > 0, cap, arr)
        c0 = t[0]
        mic = r["mic"].astype(np.float32)
        ref = z["ref"].astype(np.float32)
        n = min(len(mic), int((t[-1] - c0 + 0.02) * FS))
        r_al = np.zeros(len(mic), np.float32)
        s = int((t0 - c0) * FS)
        seg = ref[: max(0, len(mic) - s)]
        if s >= 0 and len(seg):
            r_al[s:s + len(seg)] = seg
        lag, _, _ = aec.gcc_phat(mic, r_al, 0, int(0.5 * FS))
        _lagcache[key] = lag / FS
    return _lagcache[key]


def score(corpus, overrides=None, model=aec_wer.DEFAULT_MODEL, verbose=False):
    rows, acc = [], collections.defaultdict(list)
    for (a, b, c, tag), files in sequences(corpus).items():
        for r in replay_seq(files, overrides):
            m = clip_metrics(r, model, key=str(files[r["k"]]))
            if not m:
                continue
            rows.append((f"{a}>{b}<{c}:{tag}.{r['k']}", {k: (None if v is None else round(v, 2)) for k, v in m.items()}))
            for k, v in m.items():
                if v is not None and k != "rep":
                    acc[k].append(v)
                    if k == "onset_erle":
                        acc["onset_erle_" + ("cold" if m["rep"] == 0 else "warm")].append(v)
    mean = lambda k: float(np.mean(acc[k])) if acc[k] else None
    out = {k: mean(k) for k in ("onset_erle", "onset_erle_cold", "onset_erle_warm", "aonly_erle", "aonly_leak", "child_wer")}
    out["n"] = len(rows)
    out["rows"] = rows
    return out


def raw_baseline(corpus, model=aec_wer.DEFAULT_MODEL):
    """The same metrics with no canceller: out = mic (the leak and WER an un-cancelled listener would see)."""
    acc = collections.defaultdict(list)
    for (a, b, c, tag), files in sequences(corpus).items():
        for k, f in enumerate(files):
            z = np.load(f, allow_pickle=False)
            r = dict(k=k, mic=z["mic"], out=z["mic"], z=z, a=a, b=b)
            m = clip_metrics(r, model, key=str(f))
            for kk, v in (m or {}).items():
                if v is not None and kk != "rep":
                    acc[kk].append(v)
    return {k: float(np.mean(v)) for k, v in acc.items()}


if __name__ == "__main__":
    ov = {}
    for kv in sys.argv[2:]:
        k, v = kv.split("=")
        ov[k] = float(v) if "." in v or "e" in v else int(v)
    r = score(sys.argv[1], ov)
    for row in r["rows"]:
        print(row)
    print({k: (round(v, 3) if isinstance(v, float) else v) for k, v in r.items() if k != "rows"})
