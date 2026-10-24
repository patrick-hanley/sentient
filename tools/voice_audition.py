"""Play numbered candidate voices on this computer's speakers, to pick one per toy.

Usage: python tools/voice_audition.py ["line to say"]
Then copy the winner's voice/speaker/pitch/length into brain/config.py TOYS.
"""
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np
from piper import PiperVoice, SynthesisConfig

OFF = Path(__file__).resolve().parent.parent / "offline" / "piper"
LINE = sys.argv[1] if len(sys.argv) > 1 else "Hi! I'm Dyno! Ooh, what's that? Do you want to play with me?"
# (voice, speaker, pitch, length)
CANDIDATES = [
    ("en_US-amy-medium", None, 1.15, 0.90),          # current Dyno
    ("en_US-amy-medium", None, 1.35, 0.85),
    ("en_US-libritts_r-medium", 20, 1.25, 0.95),     # current Penny
    ("en_US-libritts_r-medium", 100, 1.20, 0.90),
    ("en_US-libritts_r-medium", 300, 1.20, 0.90),
    ("en_US-libritts_r-medium", 500, 1.15, 0.90),
    ("en_GB-alba-medium", None, 1.25, 0.90),
    ("en_US-ryan-medium", None, 1.40, 0.90),
]

voices = {}
for i, (name, spk, pitch, length) in enumerate(CANDIDATES, 1):
    v = voices.setdefault(name, PiperVoice.load(str(OFF / f"{name}.onnx")))
    chunks = list(v.synthesize(f"Number {i}. {LINE}", syn_config=SynthesisConfig(speaker_id=spk, length_scale=length * pitch)))
    sr = chunks[0].sample_rate
    a = np.concatenate([c.audio_int16_array for c in chunks]).astype(np.float32)
    n = int(len(a) / pitch)  # same pitch trick the brain uses
    a = np.interp(np.linspace(0, len(a) - 1, n), np.arange(len(a)), a).astype("<i2")
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        with wave.open(f.name, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr); w.writeframes(a.tobytes())
    print(f"{i}: voice={name} speaker={spk} pitch={pitch} length={length}", flush=True)
    subprocess.run(["afplay", f.name])
    Path(f.name).unlink()
