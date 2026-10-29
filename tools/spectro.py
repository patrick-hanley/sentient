"""Spectrograms and band numbers for judging audio conversion. Mac side (needs matplotlib, scipy).

  python tools/spectro.py old.wav new.wav --labels old new --out cmp.png [--json cmp.json]
Stacks one spectrogram per file (same colour scale) with the 7.2 kHz anti-alias cutoff marked, and
prints the band table from brain/spectrum.py."""
import argparse
import json
import sys
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from brain.spectrum import BANDS, metrics  # noqa: E402


def read(path):
    with wave.open(str(path)) as w:
        sr, n = w.getframerate(), w.getnframes()
        x = np.frombuffer(w.readframes(n), "<i2")
    return x, sr


def plot(items, out, cutoff=7200, title=None):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from scipy.signal import spectrogram
    fig, axes = plt.subplots(len(items), 1, figsize=(11, 3.1 * len(items)), sharex=True, squeeze=False)
    for ax, (label, x, sr) in zip(axes[:, 0], items):
        f, t, S = spectrogram(x.astype(np.float32) / 32768, fs=sr, nperseg=512, noverlap=384, window="hann")
        im = ax.pcolormesh(t, f / 1000, 10 * np.log10(S + 1e-12), vmin=-110, vmax=-30, cmap="magma", shading="auto")
        ax.axhline(cutoff / 1000, color="cyan", lw=0.7, ls="--")
        ax.set_ylabel("kHz")
        ax.set_title(label, loc="left", fontsize=10)
        ax.set_ylim(0, sr / 2000)
    axes[-1, 0].set_xlabel("seconds")
    fig.colorbar(im, ax=axes[:, 0].tolist(), label="dB re full scale / bin", pad=0.01)
    if title:
        fig.suptitle(title)
    fig.savefig(out, dpi=110, bbox_inches="tight")
    plt.close(fig)


def table(rows):
    names = [r[0] for r in rows]
    lines = ["band Hz".ljust(12) + "".join(n[:16].rjust(17) for n in names)]
    for lo, hi in BANDS:
        k = f"{lo}-{hi}"
        lines.append(k.ljust(12) + "".join(f"{r[1]['bands_db'][k]:>17.1f}" for r in rows))
    for key, label in (("rms_dbfs", "rms dBFS"), ("peak", "peak"), ("clipped", "clipped smp"),
                       ("rolloff95_hz", "95% rolloff"), ("above_7k_share_pct", ">7k share %")):
        lines.append(label.ljust(12) + "".join(f"{r[1][key]:>17}" for r in rows))
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--labels", nargs="*")
    ap.add_argument("--out", default="spectro.png")
    ap.add_argument("--json")
    a = ap.parse_args()
    labels = a.labels or [Path(f).stem for f in a.files]
    items, rows = [], []
    for lab, path in zip(labels, a.files):
        x, sr = read(path)
        items.append((lab, x, sr))
        rows.append((lab, metrics(x)))
    plot(items, a.out)
    print(table(rows))
    if a.json:
        Path(a.json).write_text(json.dumps({lab: m for lab, m in rows}, indent=1))


if __name__ == "__main__":
    main()
