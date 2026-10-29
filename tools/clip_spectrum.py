#!/usr/bin/env python3
"""Quantify a voice clip: spectrum, band energies, clipping, and A/B filter test.

Usage (on the Pi, or anywhere with numpy; matplotlib is optional):
  python3 spectrum.py clip.wav
  python3 spectrum.py clip.wav --filter --out filtered.wav --plot spectrum.png
  python3 spectrum.py brain/data/tts-cache/<hash>.pcm --pcm --sr 16000

What it prints, for the input (and, with --filter, for the filtered version):
  - duration, RMS and peak in dBFS, % of samples pinned at full scale
  - spectral centroid (the 'brightness' centre of mass, Hz)
  - energy share in bands: 0-4 kHz, 4-6 kHz, 6-8 kHz, and (if sr > 16000)
    8-11 kHz -- the band that folds down into 6-8 kHz when downsampled
    to 16 kHz without a lowpass filter (the aliasing suspect in Piper)
  - with --plot: an FFT spectrum (dB vs log frequency) and a spectrogram

The filter is the same one in piper_filter_patch.diff: a 101-tap
windowed-sinc FIR lowpass at 7.2 kHz (for a 16 kHz target) before
downsampling, plus a soft limiter that only bends peaks above ~0.95
of full scale. No scipy needed -- numpy only for the audio math.
"""
import argparse
import sys
import wave

import numpy as np


def read_audio(path, pcm=False, sr_hint=16000):
    if pcm:
        x = np.fromfile(path, dtype="<i2").astype(np.float32) / 32768.0
        return x, sr_hint
    with wave.open(path, "rb") as w:
        n, sr, ch, sw = w.getnframes(), w.getframerate(), w.getnchannels(), w.getsampwidth()
        raw = w.readframes(n)
    if sw == 2:
        x = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    elif sw == 4:
        x = np.frombuffer(raw, dtype="<i4").astype(np.float32) / 2147483648.0
    else:
        raise SystemExit(f"unsupported sample width {sw} (need 16- or 32-bit WAV)")
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    return x, sr


def write_wav(path, x, sr):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(np.clip(x, -1.0, 1.0).astype("<i2").tobytes() if False else
                      (np.clip(x, -32768, 32767).astype("<i2").tobytes() if x.dtype != np.float32 else
                       np.clip(x * 32768.0, -32768, 32767).astype("<i2").tobytes()))


def lowpass_fir(x, fs, cutoff=7200.0, taps=101):
    """Windowed-sinc FIR lowpass, numpy only. Returns same-length signal."""
    if cutoff >= fs / 2:
        return x
    m = (taps - 1) // 2
    n = np.arange(taps) - m
    h = 2 * cutoff / fs * np.sinc(2 * cutoff * n / fs)
    h *= np.hamming(taps)
    h /= h.sum()
    return np.convolve(x, h, mode="same")


def soft_limit(x, knee=0.95):
    """Soft limiter: ~transparent below the knee, bends peaks above it.

    y = x / (1 + (|x|/knee)**8)**(1/8). At x=0.5, y=0.499; at x=1.0, y=0.89.
    No flat tops, unlike a hard clip at 32767.
    """
    return x / (1.0 + (np.abs(x) / knee) ** 8) ** (1.0 / 8.0)


def analyse(x, sr, label):
    x = np.asarray(x, dtype=np.float64)
    peak = np.abs(x).max() if len(x) else 0.0
    rms = np.sqrt(np.mean(x ** 2)) if len(x) else 0.0
    clip_pct = 100.0 * np.mean(np.abs(x) >= 32760 / 32768.0) if len(x) else 0.0
    # FFT on a Hann window, whole clip (use a 1 s middle slice if very long)
    seg = x[len(x) // 4: 3 * len(x) // 4] if len(x) > sr else x
    seg = seg * np.hanning(len(seg))
    spec = np.abs(np.fft.rfft(seg))
    freqs = np.fft.rfftfreq(len(seg), 1.0 / sr)
    power = spec ** 2
    centroid = float(np.sum(freqs * power) / np.sum(power)) if power.sum() else 0.0
    bands = [(0, 4000), (4000, 6000), (6000, 8000), (8000, 11025)]
    shares = {}
    for lo, hi in bands:
        if hi > sr / 2:
            continue
        m = (freqs >= lo) & (freqs < hi)
        shares[f"{lo // 1000}-{hi // 1000}k"] = 100.0 * power[m].sum() / power.sum() if power.sum() else 0.0
    print(f"\n--- {label} (sr={sr} Hz, {len(x) / sr:.2f} s) ---")
    print(f"peak: {20 * np.log10(peak + 1e-12):6.1f} dBFS   RMS: {20 * np.log10(rms + 1e-12):6.1f} dBFS   "
          f"clipped samples: {clip_pct:.3f}%")
    print(f"spectral centroid: {centroid:7.0f} Hz   (higher = brighter/harsher)")
    print("band energy share: " + "   ".join(f"{k}: {v:5.1f}%" for k, v in shares.items()))
    return freqs, spec


def plot(freqs, spec, freqs_f, spec_f, path, sr):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib not installed: skipping plot, numbers above are the result.")
        return
    fig, axes = plt.subplots(2, 1, figsize=(10, 6))
    db = 20 * np.log10(spec + 1e-9)
    db -= db.max()
    axes[0].semilogx(freqs, db)
    axes[0].set_xlim(100, sr / 2)
    axes[0].set_ylim(-80, 5)
    axes[0].set_xlabel("frequency (Hz, log)")
    axes[0].set_ylabel("dB (relative to peak)")
    axes[0].set_title("FFT spectrum — before filter")
    axes[0].grid(True, which="both", alpha=0.3)
    if spec_f is not None:
        dbf = 20 * np.log10(spec_f + 1e-9)
        dbf -= dbf.max()
        axes[1].semilogx(freqs_f, dbf)
        axes[1].set_xlim(100, 8000)
        axes[1].set_ylim(-80, 5)
        axes[1].set_xlabel("frequency (Hz, log)")
        axes[1].set_ylabel("dB (relative to peak)")
        axes[1].set_title("FFT spectrum — after filter")
        axes[1].grid(True, which="both", alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    print(f"plot saved: {path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input", help="WAV file, or .pcm with --pcm")
    ap.add_argument("--pcm", action="store_true", help="input is raw int16 mono PCM")
    ap.add_argument("--sr", type=int, default=16000, help="sample rate for --pcm input")
    ap.add_argument("--filter", action="store_true", help="also analyse a filtered version")
    ap.add_argument("--out", help="write filtered audio as WAV (with --filter)")
    ap.add_argument("--plot", help="write spectrum PNG (with --filter, else before-only)")
    ap.add_argument("--cutoff", type=float, default=7200.0, help="lowpass cutoff in Hz")
    args = ap.parse_args()

    x, sr = read_audio(args.input, pcm=args.pcm, sr_hint=args.sr)
    freqs, spec = analyse(x, sr, "before filter")

    freqs_f = spec_f = None
    if args.filter:
        # Filter at the source rate, then downsample to 16 kHz if needed
        # (mirrors the patch: lowpass BEFORE the rate change).
        y = lowpass_fir(x, sr, cutoff=args.cutoff) if sr > 16000 else lowpass_fir(x, sr, cutoff=args.cutoff)
        y = soft_limit(y)
        if sr > 16000:
            n = int(round(len(y) * 16000 / sr))
            y16 = np.interp(np.linspace(0, len(y) - 1, n), np.arange(len(y)), y)
            freqs_f, spec_f = analyse(y16, 16000, "after filter (16 kHz)")
        else:
            freqs_f, spec_f = analyse(y, sr, "after filter")
        if args.out:
            out_sr = 16000 if sr > 16000 else sr
            out_x = y16 if sr > 16000 else y
            write_wav(args.out, out_x, out_sr)
            print(f"filtered audio saved: {args.out}")
    if args.plot:
        plot(freqs, spec, freqs_f, spec_f, args.plot, sr)


if __name__ == "__main__":
    main()
