#!/usr/bin/env python3
"""Record real trials (all six rotations, `reps` each) into a corpus dir of dump files for offline replay (aec_replay.py).
  python tools/aec_corpus.py DIR [reps]     hardware guard on every trial; appends to /tmp/aec-progress.log"""
import itertools
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import aec_experiment as E  # noqa: E402

VOL_TALK = {"dyno": 70, "penny": 70, "sage": 120}
VOL_CHILD = {"dyno": 100, "penny": 100, "sage": 120}
out, reps = sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 2
for a, c in [p for _ in range(reps) for p in itertools.permutations(("dyno", "sage", "penny"), 2)]:
    b = ({"dyno", "sage", "penny"} - {a, c}).pop()
    try:
        log, res = E.trial(a, c, b, VOL_TALK[a], VOL_CHILD[c], keep_dir=out)
    except E.HardwareIssue as e:
        E.progress(0, f"corpus {a}>{b}<{c}", None, None, None, "-", f"HARDWARE ISSUE STOP: {e}")
        print("HARDWARE ISSUE, stopping:", e)
        break
    erle = float(log[0].split("ERLE ")[1].split(" dB")[0]) if log and "ERLE" in log[0] else None
    o = (res or {}).get("canceller out", {})
    E.progress(0, f"hw {a}>{b}<{c}", erle, o.get("wer"), o.get("leak"), "-", "corpus")
    print(a, b, c, erle, o.get("wer"), o.get("leak"), flush=True)
