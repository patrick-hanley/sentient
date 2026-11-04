"""Measure an Atom speaker with the Mac's own microphone (independent of the Atom mics).

  .venv/bin/python tools/mac_sweep.py ref runs/sweep/mac dyno,sage,penny [sentient@sentient-jetson.local]
Hold the Atom about 10 cm from the Mac mic. For each toy, plays sweep_lo then sweep_hi through the Atom
(the play step runs on the brain host over ssh) while the Mac records. Audio is analysed in RAM-sized files
under the output folder (git-ignored runs/). Report: per-toy response and lo->hi level step."""
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np
import sounddevice as sd

sys.path.insert(0, str(Path(__file__).parent))
import atom_sweep as A  # noqa: E402

PLAY = "cd /data/sentient && .venv-brain/bin/python tools/play_wav_atom.py %s /tmp/%s.wav"


def record_while(cmd, sec):
    x = sd.rec(int(sec * A.SR), samplerate=A.SR, channels=1, dtype="int16")
    subprocess.run(cmd, shell=True, check=True, capture_output=True)
    sd.wait()
    return x[:, 0]


def main(ref, out, toys, host="sentient@sentient-jetson.local"):
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    for lvl in ("lo", "hi"):
        subprocess.run(["scp", "-q", f"{ref}/sweep_{lvl}.wav", f"{host}:/tmp/sweep_{lvl}.wav"], check=True)
    quiet = sd.rec(2 * A.SR, samplerate=A.SR, channels=1, dtype="int16"); sd.wait()
    print("room noise rms", round(float(np.sqrt((quiet.astype(float) ** 2).mean())), 1))
    for toy in toys.split(","):
        for lvl in ("lo", "hi"):
            x = record_while(f"ssh {host} \"{PLAY % (toy, 'sweep_' + lvl)}\"", A.DUR + 6)
            A.write(out / f"{toy}_{lvl}.wav", x)
            print(toy, lvl, "peak", int(np.abs(x).max()), "rms", round(float(np.sqrt((x.astype(float) ** 2).mean())), 1), flush=True)


if __name__ == "__main__":
    main(*sys.argv[1:])
