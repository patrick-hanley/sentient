#!/usr/bin/env python3
"""Run /aec_trial on the Jetson (SENTIENT_AEC=1, SENTIENT_AEC_DUMP=/dev/shm, mics muted) and score it on the Mac.

  python tools/aec_experiment.py A C [--listener B] [--vol-a 70 --vol-c 70] [--delay 2.5]

A talks through the normal path (echo canceller engaged), C plays the "child" straight to its speaker `delay` s later, B listens.
Prints WER against the child's true text for the raw mic and for the canceller's output. Sound plays: modest volumes only."""
import argparse
import glob
import json
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import aec_wer  # noqa: E402

HOST = "sentient@sentient-jetson.local"
A_TEXT = "The quick brown fox jumps over the lazy dog while the sun is shining brightly today and everyone is happy."
C_TEXT = "Please stop and tell me about the big red dinosaur."
REMOTE = r'''
A=$1; C=$2
curl -s -X POST "localhost:8080/speaker?toy=$A&vol=$3" >/dev/null; curl -s -X POST "localhost:8080/speaker?toy=$C&vol=$4" >/dev/null
rm -rf /dev/shm/aec_*.npz; sleep 1
curl -s -X POST -G localhost:8080/aec_trial --data-urlencode "a=$A" --data-urlencode "c=$C" --data-urlencode "atext=$5" --data-urlencode "ctext=$6" --data-urlencode "delay=$7" >/dev/null
sleep $8
journalctl -u sentient-brain --since "-$(( $8 + 3 ))s" --no-pager | grep -E " aec |Traceback|failed" | sed 's/.*atoms *//' | cut -c1-170
'''


def trial(a, c, b, vol_a=70, vol_c=70, delay=2.5, atext=A_TEXT, ctext=C_TEXT, wait=17, model=None):
    args = [a, c, str(vol_a), str(vol_c), atext, ctext, str(delay), str(wait)]
    r = subprocess.run(["ssh", HOST, "bash -s -- " + " ".join(shlex.quote(x) for x in args)], input=REMOTE, capture_output=True, text=True)
    log = [ln for ln in r.stdout.splitlines() if f"{a}->{b}" in ln or "Traceback" in ln]
    d = tempfile.mkdtemp()
    subprocess.run(["scp", "-q", f"{HOST}:/dev/shm/aec_{a}_{b}_*.npz", d], capture_output=True)
    files = glob.glob(d + "/*.npz")
    res = aec_wer.score(files[0], model or aec_wer.DEFAULT_MODEL) if files else None
    return log, res


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("a"); ap.add_argument("c")
    ap.add_argument("--listener")
    ap.add_argument("--vol-a", type=int, default=70); ap.add_argument("--vol-c", type=int, default=70)
    ap.add_argument("--delay", type=float, default=2.5)
    ns = ap.parse_args()
    b = ns.listener or ({"dyno", "sage", "penny"} - {ns.a, ns.c}).pop()
    log, res = trial(ns.a, ns.c, b, ns.vol_a, ns.vol_c, ns.delay)
    print("\n".join(log)); print(json.dumps(res, indent=1))
