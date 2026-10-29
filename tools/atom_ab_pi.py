"""Run on the Pi: play each WAV through one Atom's speaker and record what the Atoms' mics hear (via /tap.wav).

  .venv-brain/bin/python tools/atom_ab_pi.py penny dyno,penny /tmp/ab out 3
Needs SENTIENT_DEBUG_RECORD=1 on the brain (RAM-only mic tap). Mute the brain's ears first (POST /mute) so it
does not answer. Plays in an alternating order (a, b, a, b ...) so drift hits both variants alike."""
import json
import os
import sys
import time
import urllib.request
import wave

sys.path.insert(0, ".")
from brain.atoms import encode_for_atom  # noqa: E402

BRAIN = "http://127.0.0.1:8080"


def pcm_of(path):
    with wave.open(path) as w:
        assert w.getframerate() == 16000 and w.getnchannels() == 1
        return w.readframes(w.getnframes())


def main(speaker, mics, folder, out, reps):
    ip = json.load(urllib.request.urlopen(f"{BRAIN}/state", timeout=5))["toys"][speaker]["ip"]
    files = sorted(f for f in os.listdir(folder) if f.endswith(".wav"))
    groups = {}
    for f in files:   # name_<variant>.wav, variants alternate within a name
        stem, variant = f[:-4].rsplit("_", 1)
        groups.setdefault(stem, {})[variant] = f
    os.makedirs(out, exist_ok=True)
    for mic in mics.split(","):   # noise floor: 3 s of room with nothing playing
        time.sleep(3.2)
        open(f"{out}/silence_{mic}.wav", "wb").write(urllib.request.urlopen(f"{BRAIN}/tap.wav?toy={mic}&sec=3", timeout=10).read())
    for rep in range(int(reps)):
        for stem, variants in groups.items():
            for variant in (sorted(variants) if rep % 2 == 0 else sorted(variants, reverse=True)):
                pcm = pcm_of(f"{folder}/{variants[variant]}")
                body, query = encode_for_atom(pcm)
                dur = len(pcm) / 2 / 16000
                time.sleep(1.0)
                req = urllib.request.Request(f"http://{ip}/play?{query}", data=body, method="POST",
                                             headers={"Content-Type": "application/octet-stream"})
                urllib.request.urlopen(req, timeout=30 + dur).read()
                time.sleep(0.3)
                for mic in mics.split(","):
                    data = urllib.request.urlopen(f"{BRAIN}/tap.wav?toy={mic}&sec={dur + 1.0:.1f}", timeout=10).read()
                    open(f"{out}/{stem}_{variant}_r{rep}_{mic}.wav", "wb").write(data)
                print("played", stem, variant, "rep", rep, flush=True)


if __name__ == "__main__":
    main(*sys.argv[1:6])
