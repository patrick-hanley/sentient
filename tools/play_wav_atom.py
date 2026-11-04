"""Run on the brain host: play a 16 kHz mono WAV through one Atom's speaker.  python tools/play_wav_atom.py dyno /tmp/x.wav"""
import json
import sys
import time
import urllib.request
import wave

sys.path.insert(0, ".")
from brain.atoms import encode_for_atom  # noqa: E402

toy, path = sys.argv[1:3]
ip = json.load(urllib.request.urlopen("http://127.0.0.1:8080/state"))["toys"][toy]["ip"]
w = wave.open(path)
body, q = encode_for_atom(w.readframes(w.getnframes()))
time.sleep(1.5)
urllib.request.urlopen(urllib.request.Request(f"http://{ip}/play?{q}", data=body, method="POST"), timeout=60).read()
