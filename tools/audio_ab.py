"""A/B of the audio conversion in brain/tts.py: the old resample/clip path vs the current one.

  python tools/audio_ab.py --old da23239 --out runs/audio_ab
Runs the real _render_piper of both versions on the same text, plus a tone test that shows folded-back
(aliased) energy, a loud-peak test for the soft limiter, and the 24 kHz Kokoro/Kitten samples through both
_resample()s. Writes WAVs, spectrogram PNGs and a metrics JSON. Mac side; needs piper, matplotlib, scipy."""
import argparse
import importlib.util
import json
import subprocess
import sys
import tempfile
import threading
import types
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
from brain import config  # noqa: E402
from brain import tts as new  # noqa: E402
from brain.spectrum import metrics  # noqa: E402
import spectro  # noqa: E402

LINES = ["Seven times eight is fifty-six! That is like seven rows of eight penguins.",
         "Sally sells seashells by the seashore, and she says it six times fast.",
         "Hmm, that is a great question. Let us think about how plants grow, shall we?"]


def load_old(rev):
    src = subprocess.run(["git", "show", f"{rev}:brain/tts.py"], capture_output=True, text=True, check=True, cwd=ROOT).stdout
    path = Path(tempfile.mkdtemp()) / "tts_old.py"
    path.write_text(src)
    spec = importlib.util.spec_from_file_location("brain.tts_old", path)
    mod = importlib.util.module_from_spec(spec)
    mod.__package__ = "brain"
    sys.modules["brain.tts_old"] = mod
    spec.loader.exec_module(mod)
    return mod


def piper_render(mod, toy, text):
    v = object.__new__(mod.Voices)
    v._voices, v._lock = {}, threading.Lock()
    return v._render_piper(config.TOYS[toy], text)


def write(path, pcm, sr=16000):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes(pcm if isinstance(pcm, bytes) else pcm.astype("<i2").tobytes())


def tone(freq, sr, secs=1.0, amp=0.5):
    t = np.arange(int(sr * secs)) / sr
    return np.sin(2 * np.pi * freq * t).astype(np.float32) * amp * 32767


def level_at(x, freq, sr=16000):
    n = len(x); win = np.hanning(n)
    spec = np.abs(np.fft.rfft(x.astype(np.float64) * win)) / win.sum() * 2
    k = int(round(freq * n / sr))
    return float(20 * np.log10(spec[max(k - 2, 0):k + 3].max() / 32768 + 1e-12))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--old", default="da23239")
    ap.add_argument("--out", default="runs/audio_ab")
    ap.add_argument("--samples", help="folder with 24 kHz Kokoro/Kitten WAVs")
    a = ap.parse_args()
    out = ROOT / a.out
    out.mkdir(parents=True, exist_ok=True)
    old = load_old(a.old)
    res = {"old": a.old, "tones": {}, "piper": {}, "loud": {}, "24k": {}}

    # 1. aliasing: a tone above 8 kHz at Piper's 22.05 kHz folds to 16 kHz - f if nothing removes it first
    ref = {}
    for name, mod in (("old", old), ("new", new)):
        ref[name] = level_at(mod._resample(tone(1000, 22050), 22050, 16000), 1000)
    for f in (9000, 10000, 11000):
        row = {}
        for name, mod in (("old", old), ("new", new)):
            y = mod._resample(tone(f, 22050), 22050, 16000)
            row[name] = round(level_at(y, 16000 - f) - ref[name], 1)   # alias level vs the 1 kHz tone, dB
        row["improvement_db"] = round(row["old"] - row["new"], 1)
        res["tones"][f"{f}Hz->alias {16000 - f}Hz"] = row

    # 2. real Piper speech through each version's own _render_piper
    items = []
    for toy in ("sage", "dyno"):
        for i, text in enumerate(LINES):
            po, pn = piper_render(old, toy, text), piper_render(new, toy, text)
            key = f"{toy}-{i}"
            write(out / f"piper_{key}_old.wav", po)
            write(out / f"piper_{key}_new.wav", pn)
            res["piper"][key] = {"old": metrics(po), "new": metrics(pn)}
            if i == 0:
                items += [(f"{toy} OLD (hard resample, clip)", np.frombuffer(po, "<i2"), 16000),
                          (f"{toy} NEW (anti-alias + soft limit)", np.frombuffer(pn, "<i2"), 16000)]
    spectro.plot(items, out / "piper_old_vs_new.png", title="Piper speech, same text, old vs new conversion")

    # 3. soft limiter vs hard clip on a loud line (x3 before the final stage, like a hot voice)
    voice = object.__new__(new.Voices); voice._voices, voice._lock = {}, threading.Lock()
    t = config.TOYS["sage"]
    audio = new._resample(np.concatenate([c.audio_int16_array for c in
                          voice._voices.setdefault(t["voice"], __import__("piper").PiperVoice.load(str(config.OFFLINE / "piper" / f"{t['voice']}.onnx"))).synthesize(LINES[0])]).astype(np.float32) * 3.0,
                          22050 * t["pitch"], 16000)
    hard = np.clip(audio, -32768, 32767).astype("<i2")
    soft = (new._soft_limit(audio / 32768.0) * 32768.0).astype("<i2")
    res["loud"] = {"old_hard_clip": metrics(hard), "new_soft_limit": metrics(soft)}
    write(out / "loud_old.wav", hard); write(out / "loud_new.wav", soft)
    spectro.plot([("loud x3, hard clip (old)", hard, 16000), ("loud x3, soft limit (new)", soft, 16000)],
                 out / "loud_old_vs_new.png", title="Peak handling")

    # 4. 24 kHz neural voices through both _resample()s (Kokoro and Kitten take this path too)
    folder = Path(a.samples) if a.samples else None
    for name in ("kokoro_int8_af_heart", "-nano-0.8-int8_Bella"):
        p = folder / f"{name}.wav" if folder else None
        if p and p.exists():
            with wave.open(str(p)) as w:
                x = np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(np.float32) if w.getsampwidth() == 2 else None
                sr = w.getframerate()
            if x is None:
                continue
            yo, yn = (np.clip(m._resample(x, sr, 16000), -32768, 32767).astype("<i2") for m in (old, new))
            write(out / f"{name.strip('-')}_old.wav", yo); write(out / f"{name.strip('-')}_new.wav", yn)
            res["24k"][name] = {"old": metrics(yo), "new": metrics(yn)}
            spectro.plot([(f"{name} OLD", yo, 16000), (f"{name} NEW", yn, 16000)], out / f"{name.strip('-')}_old_vs_new.png")
    (out / "metrics.json").write_text(json.dumps(res, indent=1))
    print(json.dumps({"tones_dB_below_1kHz_tone": res["tones"]}, indent=1))


if __name__ == "__main__":
    main()
