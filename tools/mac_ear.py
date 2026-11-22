"""The Mac's mic as the reference: what actually sounded in the room. Audio stays in RAM; only numbers are written."""
import json, subprocess, sys, time, wave, glob, os
import numpy as np, sounddevice as sd
SR = 16000
SFX = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "offline", "sfx") + "/"

def feats(x):
    x = x.astype(np.float32)
    n, hop = 512, 160
    if len(x) < n: x = np.pad(x, (0, n - len(x)))
    fr = np.lib.stride_tricks.sliding_window_view(x, n)[::hop] * np.hanning(n)
    P = np.abs(np.fft.rfft(fr, axis=1)) ** 2
    f = np.fft.rfftfreq(n, 1 / SR)
    edges = np.geomspace(250, 7000, 15)
    B = np.stack([P[:, (f >= a) & (f < b)].sum(1) for a, b in zip(edges[:-1], edges[1:])], 1)
    return np.log10(B + 1e3)

def load(name):
    w = wave.open(SFX + name + ".wav"); x = np.frombuffer(w.readframes(w.getnframes()), "<i2"); r = w.getframerate(); w.close()
    if w.getnchannels() == 2: x = x[::2]
    if r != SR: x = np.interp(np.arange(0, len(x), r / SR), np.arange(len(x)), x)
    return x
REFS = {os.path.basename(p)[:-4]: None for p in glob.glob(SFX + "*.wav")}

def match(seg, cap_s=2.5):
    """-> [(score, name)] best first: how well each recorded sound's band pattern fits this piece of the room recording."""
    F = feats(seg); out = []
    for name in REFS:
        if REFS[name] is None: REFS[name] = load(name)
        R = feats(REFS[name][:int(cap_s * SR)])
        if len(R) < 8: continue
        if len(F) < len(R): R = R[:len(F)]
        best = -1
        Rz = R - R.mean(); rn = np.linalg.norm(Rz) or 1
        for o in range(0, len(F) - len(R) + 1, 2):
            W = F[o:o + len(R)]; Wz = W - W.mean()
            best = max(best, float((Wz * Rz).sum() / (rn * (np.linalg.norm(Wz) or 1))))
        out.append((round(best, 2), name))
    return sorted(out, reverse=True)

def bursts(x, floor, mult=4.0, min_s=0.15, join_s=0.25):
    """Loud stretches: [(start_s, end_s, rms)] in 50 ms steps."""
    n = len(x) // 800; e = np.sqrt((x[:n * 800].astype(np.float32).reshape(n, 800) ** 2).mean(1))
    on = e > max(floor * mult, 120); out = []; i = 0
    while i < n:
        if on[i]:
            j = i; gap = 0; last = i
            while j < n and gap * 0.05 <= join_s:
                if on[j]: last = j; gap = 0
                else: gap += 1
                j += 1
            if (last + 1 - i) * 0.05 >= min_s:
                out.append((round(i * 0.05, 2), round((last + 1) * 0.05, 2), int(np.sqrt((e[i:last + 1] ** 2).mean()))))
            i = last + 1
        else: i += 1
    return out

class Ear:
    def __init__(self):
        self.buf = []; self.st = sd.InputStream(samplerate=SR, channels=1, dtype="int16", callback=lambda d, f, t, s: self.buf.append(d[:, 0].copy()))
        self.t0 = time.time(); self.st.start()
    def now(self): return time.time() - self.t0
    def stop(self):
        self.st.stop(); return np.concatenate(self.buf)
