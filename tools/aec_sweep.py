#!/usr/bin/env python3
"""All six (A talks, C child) rotations with B listening, at given volumes. python tools/aec_sweep.py [vol_a vol_c]"""
import itertools
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import aec_experiment as E  # noqa: E402

va, vc = (int(x) for x in sys.argv[1:3]) if len(sys.argv) >= 3 else (90, 130)
rows = []
for a, c in itertools.permutations(("dyno", "sage", "penny"), 2):
    b = ({"dyno", "sage", "penny"} - {a, c}).pop()
    log, res = E.trial(a, c, b, va, vc)
    erle = log[0].split("ERLE ")[1].split(" dB")[0] if log and "ERLE" in log[0] else "?"
    barges = log[0].split("barges ")[1].split(",")[0] if log and "barges" in log[0] else "?"
    r = res or {}
    raw, out = r.get("raw mic", {}), r.get("canceller out", {})
    print(f"{a:5} talks {b:5} listens {c:5} child vol {va}/{vc}: ERLE {erle:>5} dB barges {barges}  WER raw {raw.get('wer')} out {out.get('wer')}  "
          f"leak raw {raw.get('leak')} out {out.get('leak')}  heard(out): {out.get('heard')!r}", flush=True)
