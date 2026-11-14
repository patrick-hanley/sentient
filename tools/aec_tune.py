#!/usr/bin/env python3
"""One-change-per-iteration tuning of the echo canceller on a recorded corpus (aec_replay). Keep a change only if ERLE rises >= 0.5 dB
and neither WER nor leakage gets worse; each kept change is written into the source and committed with its numbers. Stops after 4
rejected iterations in a row. One line per iteration in /tmp/aec-progress.log.   python tools/aec_tune.py CORPUS"""
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import aec_experiment as E  # noqa: E402
import aec_replay as R  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
# name -> (file, regex with one group around the value). Candidates are (name, value, what it changes).
SRC = {
    "AEC_PARTS": ("brain/config.py", r"^AEC_PARTS = ([0-9.]+)"),
    "AEC_MU": ("brain/config.py", r'^AEC_MU = float\(os.environ.get\("SENTIENT_AEC_MU", "([0-9.]+)"\)\)'),
    "AEC_DT_RATIO": ("brain/config.py", r"^AEC_DT_RATIO = ([0-9.]+)"),
    "AEC_MIN_RMS": ("brain/config.py", r"^AEC_MIN_RMS = ([0-9.]+)"),
    "PRE": ("brain/aec.py", r"^PRE = ([0-9]+)"),
    "PASSES": ("brain/aec.py", r"^PASSES = ([0-9]+)"),
}
CANDIDATES = [("AEC_PARTS", 12, "filter size"), ("PRE", 320, "delay slack before the main tap"), ("AEC_MU", 0.3, "step size"),
              ("AEC_MU", 0.8, "step size"), ("AEC_DT_RATIO", 1.5, "double-talk threshold"), ("PASSES", 10, "retrospective passes"),
              ("AEC_PARTS", 6, "filter size"), ("PRE", 80, "delay slack"), ("AEC_MIN_RMS", 150.0, "comfort floor for double talk"),
              ("AEC_DT_RATIO", 3.0, "double-talk threshold")]


def apply(name, value):
    f, pat = SRC[name]
    p = ROOT / f
    s = p.read_text()
    new = re.sub(pat, lambda m: m.group(0).replace(m.group(1), str(value)), s, count=1, flags=re.M)
    assert new != s or str(value) in s, name
    p.write_text(new)
    return f


def current(name):
    f, pat = SRC[name]
    return re.search(pat, (ROOT / f).read_text(), flags=re.M).group(1)


def main(corpus):
    base = R.score(corpus)
    best = base
    E.progress(0, "baseline", base["erle"], base["wer"], base["leak"], f"{best['erle']:.2f}", "baseline")
    print("baseline", {k: v for k, v in base.items() if k != "rows"}, flush=True)
    rejected = 0
    for it, (name, value, what) in enumerate(CANDIDATES, 1):
        if rejected >= 4:
            break
        old = current(name)
        if str(value) == old:
            continue
        r = R.score(corpus, {name: value})
        keep = r["erle"] >= best["erle"] + 0.5 and r["wer"] <= best["wer"] + 1e-9 and r["leak"] <= best["leak"] + 1e-9
        E.progress(it, f"{name}={value} ({what})", r["erle"], r["wer"], r["leak"], f"{(r['erle'] if keep else best['erle']):.2f}", "kept" if keep else "reverted")
        print(it, name, value, {k: round(v, 3) for k, v in r.items() if k not in ("rows", "n")}, "KEPT" if keep else "reverted", flush=True)
        if keep:
            f = apply(name, value)
            subprocess.run(["git", "-C", str(ROOT), "commit", "-qam",
                            f"AEC tuning: {name} {old} -> {value} ({what}); replay ERLE {best['erle']:.1f} -> {r['erle']:.1f} dB, WER {best['wer']:.2f} -> {r['wer']:.2f}, leak {best['leak']:.2f} -> {r['leak']:.2f}\n\nCo-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"], check=True)
            best, rejected = r, 0
        else:
            rejected += 1
    print("STOP" if rejected >= 4 else "candidates exhausted", {k: v for k, v in best.items() if k != "rows"})


if __name__ == "__main__":
    main(sys.argv[1])
