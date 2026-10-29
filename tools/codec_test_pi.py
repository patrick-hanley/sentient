"""Run on the Pi: upload time of one line to an Atom as mu-law vs 16-bit PCM (network overhead = request time - audio time).
  .venv-brain/bin/python tools/codec_test_pi.py penny /tmp/chainp/pip_new.wav 3"""
import json
import sys
import time
import urllib.request
import wave

import numpy as np

sys.path.insert(0, ".")
from brain.atoms import ulaw_encode  # noqa: E402

toy, path, reps = sys.argv[1], sys.argv[2], int(sys.argv[3])
ip = json.load(urllib.request.urlopen("http://127.0.0.1:8080/state", timeout=5))["toys"][toy]["ip"]
with wave.open(path) as w:
    pcm = np.frombuffer(w.readframes(w.getnframes()), "<i2")
dur = len(pcm) / 16000
for rep in range(reps):
    for name, body, q in (("ulaw", ulaw_encode(pcm), "fmt=ulaw&rate=16000"), ("pcm16", pcm.astype("<i2").tobytes(), "fmt=pcm&rate=16000")):
        t = time.monotonic()
        urllib.request.urlopen(urllib.request.Request(f"http://{ip}/play?{q}", data=body, method="POST"), timeout=40).read()
        print(f"{name:6} {len(body) // 1024:4d} KB  done after {time.monotonic() - t:5.2f}s for {dur:.2f}s of audio -> overhead {time.monotonic() - t - dur:5.2f}s", flush=True)
        time.sleep(1.0)
