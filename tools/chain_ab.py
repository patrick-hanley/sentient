"""A/B of the whole speech chain: an earlier brain/tts.py (default f3f6a9d, what was deployed) vs the current one with
brain/dsp.py (band-limited resample, trim, speaker EQ, soft limit). Mac side.

  python tools/chain_ab.py --old f3f6a9d --toy penny --samples <dir with 24 kHz wavs> --out runs/chain"""
import argparse
import json
import sys
import threading
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tools"))
from brain import config, dsp  # noqa: E402
from brain import tts as new  # noqa: E402
from brain.spectrum import metrics  # noqa: E402
import audio_ab  # noqa: E402
import spectro  # noqa: E402

LINES = audio_ab.LINES


def edges_ms(pcm):
    x = np.frombuffer(pcm, "<i2").astype(np.float32) / 32768
    n = 160
    r = 20 * np.log10(np.sqrt(np.mean(x[: len(x) // n * n].reshape(-1, n) ** 2, axis=1)) + 1e-9)
    live = np.nonzero(r > -50)[0]
    return (int(live[0] * 10), int((len(r) - 1 - live[-1]) * 10)) if len(live) else (0, 0)


def row(pcm):
    m = metrics(pcm)
    lead, tail = edges_ms(pcm)
    return {"bands_db": m["bands_db"], "rms_dbfs": m["rms_dbfs"], "peak": m["peak"], "clipped": m["clipped"],
            "dur_s": round(len(pcm) / 32000, 2), "lead_ms": lead, "tail_ms": tail,
            "active_rms_dbfs": round(dsp.active_rms_dbfs(np.frombuffer(pcm, "<i2").astype(np.float32)), 1),
            "near_full_scale": int((np.abs(np.frombuffer(pcm, "<i2").astype(np.int32)) > 30000).sum())}


def piper_source(toy, text):
    from piper import PiperVoice, SynthesisConfig
    t = config.TOYS[toy]
    key = t["voice"]
    if key not in _VOICES:
        _VOICES[key] = PiperVoice.load(str(config.OFFLINE / "piper" / f"{key}.onnx"))
    chunks = list(_VOICES[key].synthesize(text, syn_config=SynthesisConfig(speaker_id=t["speaker"], length_scale=t["length"] * t["pitch"])))
    return np.concatenate([c.audio_int16_array for c in chunks]).astype(np.float32), chunks[0].sample_rate


_VOICES = {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--old", default="f3f6a9d"); ap.add_argument("--toy", default="penny")
    ap.add_argument("--samples"); ap.add_argument("--out", default="runs/chain")
    a = ap.parse_args()
    out = ROOT / a.out; (out / "play").mkdir(parents=True, exist_ok=True)
    old = audio_ab.load_old(a.old)
    res, items = {}, []
    for i, text in enumerate(LINES):
        src, sr = piper_source("sage", text)   # one render, both chains: Piper's output varies from call to call
        po = np.clip(old._resample(src, sr * config.TOYS["sage"]["pitch"], 16000), -32768, 32767).astype("<i2").tobytes()
        pn = dsp.finish((new._soft_limit(new._resample(src, sr * config.TOYS["sage"]["pitch"], 16000) / 32768.0) * 32768.0).astype("<i2").tobytes(), a.toy)
        res[f"piper-{i}"] = {"old": row(po), "new": row(pn)}
        audio_ab.write(out / "play" / f"piper{i}_old.wav", po); audio_ab.write(out / "play" / f"piper{i}_new.wav", pn)
        if i == 1:
            items += [("Piper line OLD (deployed)", np.frombuffer(po, "<i2"), 16000), ("Piper line NEW (resample + trim + soft limit)", np.frombuffer(pn, "<i2"), 16000)]
    folder = Path(a.samples) if a.samples else None
    for name, tag in (("-nano-0.8-int8_Jasper", "kitten-jasper"), ("-nano-0.8-int8_Bella", "kitten-bella"), ("kokoro_int8_af_heart", "kokoro-heart")):
        p = folder / f"{name}.wav" if folder else None
        if not p or not p.exists():
            continue
        with wave.open(str(p)) as w:
            x, sr = np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(np.float32), w.getframerate()
        po = np.clip(old._resample(x, sr, 16000), -32768, 32767).astype("<i2").tobytes()
        pn = dsp.finish(np.clip(new._resample(x, sr, 16000), -32768, 32767).astype("<i2").tobytes(), a.toy)
        res[tag] = {"old": row(po), "new": row(pn)}
        audio_ab.write(out / "play" / f"{tag}_old.wav", po); audio_ab.write(out / "play" / f"{tag}_new.wav", pn)
        if tag == "kitten-jasper":
            items += [("Kitten Jasper OLD", np.frombuffer(po, "<i2"), 16000), ("Kitten Jasper NEW (silent lead-in trimmed)", np.frombuffer(pn, "<i2"), 16000)]
    spectro.plot(items, out / "chain_old_vs_new.png", title="Whole chain, old vs new")
    (out / "metrics.json").write_text(json.dumps(res, indent=1))
    keys = ["0-500", "500-1000", "1000-2000", "2000-4000", "4000-6000", "6000-7200", "7200-8000"]
    print("clip".ljust(14), "var", *[k.rjust(9) for k in keys], " active-rms  lead/tail ms  dur  peak >30k")
    for k, v in res.items():
        for var in ("old", "new"):
            r = v[var]
            print(k.ljust(14), var.ljust(3), *[f"{r['bands_db'][b]:9.1f}" for b in keys], f"{r['active_rms_dbfs']:9.1f}", f"{r['lead_ms']:6d}/{r['tail_ms']:<5d}", f"{r['dur_s']:5.2f}", f"{r['peak']:6d} {r['near_full_scale']:4d}")


if __name__ == "__main__":
    main()
