#!/usr/bin/env python3
"""One-change-per-iteration tuning of the echo canceller on a recorded corpus (aec_replay), warm start and residual suppressor.
Keep a change only if onset ERLE rises >= 1 dB or A-only ERLE >= 0.5 dB (the other not falling more than 0.3 dB), the A-only leak is no
worse (0.01 tolerance) and the child WER is no worse (a 0.01 tolerance: one word in a hundred, whisper's own noise). Each kept change is written
into brain/config.py and committed with its numbers. Stops after 4 rejected iterations in a row. One line per iteration in
/tmp/aec-progress.log.     python tools/aec_tune.py CORPUS [first-iteration-number]"""
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import aec_experiment as E  # noqa: E402
import aec_replay as R  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
# (config name, value, what it changes), in the order tried
CANDIDATES = [("AEC_MAG", 1, "stored per-pair echo-path magnitude drives the suppressor before the filter is trusted"),
              ("AEC_WARM", 1, "warm start (fixed: filter shifted to the best whole-sample alignment) on top of the magnitude mode"),
              ("AEC_MAG_ALPHA", 1.5, "magnitude mode over-subtraction"),
              ("AEC_RES_ONSET", 2.0, "stronger suppression in the first second"),
              ("AEC_RES_ALPHA", 3.5, "suppressor over-subtraction"),
              ("AEC_MAG_ALPHA", 0.7, "magnitude mode over-subtraction"),
              ("AEC_RES_FLOOR", 0.07, "suppressor floor")]


def apply(name, value):
    p = ROOT / "brain/config.py"
    s = p.read_text()
    new, n = re.subn(rf"^({name} = )([0-9.]+)", lambda m: m.group(1) + str(value), s, count=1, flags=re.M)
    assert n == 1, name
    p.write_text(new)


def current(name):
    return re.search(rf"^{name} = ([0-9.]+)", (ROOT / "brain/config.py").read_text(), flags=re.M).group(1)


def better(r, best):
    g_on, g_ao = r["onset_erle"] - best["onset_erle"], r["aonly_erle"] - best["aonly_erle"]
    gain = (g_on >= 1.0 and g_ao >= -0.3) or (g_ao >= 0.5 and g_on >= -0.3)     # onset is a primary metric: +1 dB counts
    return gain and r["aonly_leak"] <= best["aonly_leak"] + 0.01 and r["child_wer"] <= best["child_wer"] + 0.01


def main(corpus, first=0, only=None):
    best = R.score(corpus)
    E.progress_m(first, "baseline (current defaults)", best, best, "baseline")
    print("baseline", {k: v for k, v in best.items() if k != "rows"}, flush=True)
    rejected = 0
    for it, (name, value, what) in enumerate(CANDIDATES, first + 1):
        if rejected >= 4:
            break
        old = current(name)
        if only and it not in only:
            continue
        if str(value) == old:
            continue
        r = R.score(corpus, {name: value})
        keep = better(r, best)
        E.progress_m(it, f"{name}={value} ({what})", r, r if keep else best, "kept" if keep else "reverted")
        print(it, name, value, {k: (round(v, 3) if isinstance(v, float) else v) for k, v in r.items() if k != "rows"}, "KEPT" if keep else "reverted", flush=True)
        if keep:
            apply(name, value)
            setattr(R.config, name, type(getattr(R.config, name))(value))     # the running process must see it too
            f = lambda v: "n/a" if v is None else f"{v:.2f}"
            subprocess.run(["git", "-C", str(ROOT), "commit", "-qam",
                            f"AEC: {name} {old} -> {value} ({what}); replay onset ERLE {f(best['onset_erle'])} -> {f(r['onset_erle'])} dB, A-only ERLE "
                            f"{f(best['aonly_erle'])} -> {f(r['aonly_erle'])} dB, A-only leak {f(best['aonly_leak'])} -> {f(r['aonly_leak'])}, child WER "
                            f"{f(best['child_wer'])} -> {f(r['child_wer'])}\n\nCo-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"], check=True)
            best, rejected = r, 0
        else:
            rejected += 1
    print("STOP" if rejected >= 4 else "candidates exhausted", {k: v for k, v in best.items() if k != "rows"})


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 0)
