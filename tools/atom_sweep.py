"""Measure each Atom speaker's frequency response with the other Atoms' mics, and design a speaker EQ.

  python tools/atom_sweep.py gen   runs/sweep/ref            # sweep WAVs to play
  python tools/atom_sweep.py solve runs/sweep/rec brain/speaker_eq.json
rec files are <speaker>/sweep_<level>_r<rep>_<mic>.wav (from tools/atom_ab_pi.py). Log sweep, deconvolved and
smoothed to 1/3 octave. Speaker and mic terms are split by least squares in dB, so a toy's EQ is not tuned to
the mic that happened to listen. The shared (average) mic response stays in the result and is flattened too."""
import json
import sys
import wave
from pathlib import Path

import numpy as np

SR = 16000
F0, F1, DUR = 120.0, 7800.0, 6.0
CENTERS = [160, 200, 250, 315, 400, 500, 630, 800, 1000, 1250, 1600, 2000, 2500, 3150, 4000, 5000, 6300, 7500]


def sweep(level):
    t = np.arange(int(DUR * SR)) / SR
    k = np.log(F1 / F0)
    x = np.sin(2 * np.pi * F0 * DUR / k * (np.exp(t / DUR * k) - 1))
    fade = int(0.05 * SR)
    x[:fade] *= np.linspace(0, 1, fade); x[-fade:] *= np.linspace(1, 0, fade)
    return (x * level * 32767).astype("<i2")


def write(path, x):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes(x.tobytes())


def read(path):
    with wave.open(str(path)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(np.float64) / 32768


def third_octave_db(f, mag):
    out = []
    for c in CENTERS:
        sel = (f >= c / 2 ** (1 / 6)) & (f < c * 2 ** (1 / 6))
        out.append(10 * np.log10(np.mean(mag[sel] ** 2) + 1e-20))
    return np.array(out)


def response(rec, ref):
    """dB response in the 1/3-octave bands, from a recording that contains one sweep somewhere inside it."""
    n = len(ref)
    corr = np.fft.irfft(np.fft.rfft(rec, len(rec) + n) * np.conj(np.fft.rfft(ref, len(rec) + n)))
    lag = int(np.argmax(np.abs(corr[:len(rec)])))
    seg = rec[lag:lag + n]
    if len(seg) < n:
        seg = np.pad(seg, (0, n - len(seg)))
    f = np.fft.rfftfreq(n, 1 / SR)
    X, R = np.fft.rfft(ref), np.fft.rfft(seg)
    H = R * np.conj(X) / (np.abs(X) ** 2 + 1e-9 * np.abs(X).max() ** 2)
    return third_octave_db(f, np.abs(H))


def design(solved, boost=5.0):
    """Gain curve flattening each speaker toward its own flat region (mean level 1.25-3.15 kHz): boost <= +5 dB,
    cut <= -6 dB (boost <= +`boost` dB, 5 by default), steep high-pass under 200 Hz (the little driver cannot move air there), no boost above 6.3 kHz."""
    c = np.array(CENTERS, float)
    out = {}
    for toy, s in solved.items():
        ref = np.mean(s[(c >= 1250) & (c <= 3150)])
        g = np.clip(ref - s, -6.0, boost)
        g[c < 200] = np.minimum(g[c < 200], -9.0)
        g[c >= 6300] = np.minimum(g[c >= 6300], 0.0)
        # light smoothing so the FIR stays gentle
        g = np.convolve(np.pad(g, 1, mode="edge"), [0.25, 0.5, 0.25], mode="valid")
        out[toy] = {"hz": [100] + CENTERS + [8000], "db": [-18.0] + [round(float(x), 1) for x in g] + [round(float(g[-1]), 1)]}
        resp = np.clip(s - ref, -45.0, 6.0)   # the speaker's own response re its flat region: used to keep ACOUSTIC loudness
        out[toy]["resp_hz"], out[toy]["resp_db"] = CENTERS, [round(float(x), 1) for x in resp]
    return out


def solve(rec_dir, out_json, boost=5.0):
    rec_dir = Path(rec_dir)
    ref = {lv: read(rec_dir.parent / "ref" / f"sweep_{lv}.wav") for lv in ("lo", "hi")}
    rows = {}   # (speaker, mic) -> dB curve averaged over levels/reps
    for sp in sorted(p.name for p in rec_dir.iterdir() if p.is_dir()):
        for f in sorted((rec_dir / sp).glob("sweep_*_r*_*.wav")):
            lv, mic = f.stem.split("_")[1], f.stem.split("_")[-1]
            rows.setdefault((sp, mic), []).append(response(read(f), ref[lv]))
    pairs = {k: np.mean(v, axis=0) for k, v in rows.items()}
    # a speaker that produced nothing (recordings near the noise floor) cannot be measured: leave it out and
    # give it the average of the others, flagged, until it is fixed and re-measured
    mid = {sp: np.mean([p[(np.array(CENTERS) >= 500) & (np.array(CENTERS) <= 3000)].mean() for (s_, m), p in pairs.items() if s_ == sp]) for sp in {k[0] for k in pairs}}
    best = max(mid.values())
    silent = [sp for sp, v in mid.items() if v < best - 25]
    pairs = {k: v for k, v in pairs.items() if k[0] not in silent}
    toys = sorted({k[0] for k in pairs} | {k[1] for k in pairs})
    A = np.zeros((len(pairs), 2 * len(toys)))
    for r, (sp, mic) in enumerate(pairs):
        A[r, toys.index(sp)] = 1
        A[r, len(toys) + toys.index(mic)] = 1
    Y = np.array(list(pairs.values()))
    sol = np.linalg.lstsq(A, Y, rcond=None)[0]
    mic_mean = sol[len(toys):].mean(axis=0)
    spk = {t: sol[i] + mic_mean for i, t in enumerate(toys)}
    for sp in silent:
        print(f"WARNING: {sp}'s speaker was silent ({mid[sp]:.0f} dB vs {best:.0f} dB); using the average of the others")
        spk[sp] = np.mean([v for t, v in spk.items() if t not in silent], axis=0)
    curves = design(spk, boost)
    for sp in silent:
        curves[sp]["measured"] = False
    Path(out_json).write_text(json.dumps(curves, indent=1))
    Path(out_json).with_suffix(".measured.json").write_text(json.dumps(
        {"centers": CENTERS, "speaker_db": {t: [round(float(x), 1) for x in v] for t, v in spk.items()},
         "pairs": {f"{s}->{m}": [round(float(x), 1) for x in v] for (s, m), v in pairs.items()}}, indent=1))
    for t in toys:
        print(t, "measured (dB, 1/3 oct):", " ".join(f"{x:.0f}" for x in spk[t]))
    print("centers:", CENTERS)


if __name__ == "__main__":
    if sys.argv[1] == "gen":
        d = Path(sys.argv[2]); d.mkdir(parents=True, exist_ok=True)
        write(d / "sweep_lo.wav", sweep(0.08)); write(d / "sweep_hi.wav", sweep(0.30))
    else:
        solve(sys.argv[2], sys.argv[3], float(sys.argv[4]) if len(sys.argv) > 4 else 5.0)
