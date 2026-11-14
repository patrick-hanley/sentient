#!/usr/bin/env python3
"""All six (A talks, C child) rotations with B listening, at given volumes. python tools/aec_sweep.py [vol_a vol_c]"""
import itertools
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import aec_experiment as E  # noqa: E402

# Sage's speaker needs more volume (reseated Nov 14, audible at 160-200); the others stay modest. Arg: reps per rotation.
VOL_TALK = {"dyno": 70, "penny": 70, "sage": 160}
VOL_CHILD = {"dyno": 100, "penny": 100, "sage": 160}
reps = int(sys.argv[1]) if len(sys.argv) > 1 else 1
rows = []
for a, c in [p for p in itertools.permutations(("dyno", "sage", "penny"), 2) for _ in range(reps)]:
    b = ({"dyno", "sage", "penny"} - {a, c}).pop()
    va, vc = VOL_TALK[a], VOL_CHILD[c]
    try:
        log, res = E.trial(a, c, b, va, vc)
    except E.HardwareIssue as e:
        print("HARDWARE ISSUE, stopping:", e, flush=True)
        break
    erle = log[0].split("ERLE ")[1].split(" dB")[0] if log and "ERLE" in log[0] else "?"
    barges = log[0].split("barges ")[1].split(",")[0] if log and "barges" in log[0] else "?"
    r = res or {}
    raw, out = r.get("raw mic", {}), r.get("canceller out", {})
    print(f"{a:5} talks {b:5} listens {c:5} child vol {va}/{vc}: ERLE {erle:>5} dB barges {barges}  WER raw {raw.get('wer')} out {out.get('wer')}  "
          f"leak raw {raw.get('leak')} out {out.get('leak')}  heard(out): {out.get('heard')!r}", flush=True)
