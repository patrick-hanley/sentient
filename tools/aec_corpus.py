#!/usr/bin/env python3
"""Record real trials into a corpus dir of dump files for offline replay (aec_replay.py): every rotation (A talks, B listens,
C is the child), `reps` times, two back-to-back clips of A each (the second starts with a warm filter).
  python tools/aec_corpus.py DIR [reps]     hardware guard on every trial; appends to /tmp/aec-progress.log"""
import itertools
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import aec_experiment as E  # noqa: E402

VOL_TALK = {"dyno": 70, "penny": 70, "sage": 120}
VOL_CHILD = {"dyno": 100, "penny": 100, "sage": 120}
if __name__ == "__main__":
    out, reps = sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 2
    for i, (a, c) in enumerate(p for _ in range(reps) for p in itertools.permutations(("dyno", "sage", "penny"), 2)):
        b = ({"dyno", "sage", "penny"} - {a, c}).pop()
        try:
            txt, saved = E.trial_seq(a, c, b, VOL_TALK[a], VOL_CHILD[c], out, f"{i:02d}")
        except E.HardwareIssue as e:
            E.progress(0, f"corpus {a}>{b}<{c}", None, None, None, "-", f"HARDWARE ISSUE STOP: {e}")
            print("HARDWARE ISSUE, stopping:", e)
            break
        E.progress(0, f"corpus {a}>{b}<{c}", None, None, None, "-", f"recorded {len(saved)} clips")
        print(a, b, c, len(saved), flush=True)
