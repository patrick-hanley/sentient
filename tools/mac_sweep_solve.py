"""Analyse tools/mac_sweep.py recordings: speaker response (Mac mic), lo->hi step, and compare with the Atom-mic curves.
  .venv/bin/python tools/mac_sweep_solve.py runs/sweep/mac runs/sweep/ref brain/speaker_eq.json"""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import atom_sweep as A  # noqa: E402

d, ref, eqf = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
eq = json.load(open(eqf))
out = {}
for toy in ("dyno", "sage", "penny"):
    r = {}
    for lvl in ("lo", "hi"):
        x = A.read(d / f"{toy}_{lvl}.wav"); s = A.read(ref / f"sweep_{lvl}.wav")
        n = len(s); corr = np.fft.irfft(np.fft.rfft(x, len(x) + n) * np.conj(np.fft.rfft(s, len(x) + n)))
        peak = np.abs(corr[:len(x)]); q = peak.max() / (np.median(peak) + 1e-12)
        lag = int(np.argmax(peak)); seg = x[lag:lag + n]; seg = np.pad(seg, (0, max(0, n - len(seg))))
        fr = np.fft.rfftfreq(n, 1 / A.SR); band = (fr >= 400) & (fr <= 3150)
        r[lvl] = (A.response(x, s), q, 10 * np.log10(np.mean(np.abs(np.fft.rfft(seg))[band] ** 2) + 1e-20))
    lo, hi = r["lo"][0], r["hi"][0]
    step = float(r['hi'][2] - r['lo'][2])
    mac = (lo + hi) / 2
    mac_n = mac - np.mean(mac[(np.array(A.CENTERS) >= 400) & (np.array(A.CENTERS) <= 3150)])
    atom = np.interp(A.CENTERS, eq[toy]["resp_hz"], eq[toy]["resp_db"])
    atom_n = atom - np.mean(atom[(np.array(A.CENTERS) >= 400) & (np.array(A.CENTERS) <= 3150)])
    print(f"\n{toy}: lo->hi step {step:.1f} dB (drive step 11.5), sweep detect quality lo {r['lo'][1]:.0f} hi {r['hi'][1]:.0f}")
    print("  Hz    Mac-mic  Atom-mic  diff")
    for c, m, a in zip(A.CENTERS, mac_n, atom_n):
        print(f"  {c:5d} {m:7.1f} {a:8.1f} {m - a:6.1f}")
    out[toy] = {"step_db": step, "hz": A.CENTERS, "mac_db": [round(float(v), 1) for v in mac_n], "atom_db": [round(float(v), 1) for v in atom_n]}
json.dump(out, open(d / "mac_result.json", "w"), indent=1)
