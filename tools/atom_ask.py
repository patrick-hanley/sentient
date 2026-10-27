"""Run on the Pi: play a recorded question through one Atom's speaker so the other Atoms' mics hear it as a child.

  .venv-brain/bin/python tools/atom_ask.py penny /tmp/asks/0.wav
Bypasses the brain's own-speech mute on purpose (the brain does not know this is playing). Blocks until done.
"""
import json
import sys
import urllib.request
import wave

sys.path.insert(0, ".")
from brain.atoms import encode_for_atom  # noqa: E402


def main(toy, path, brain="127.0.0.1"):
    ip = json.load(urllib.request.urlopen(f"http://{brain}:8080/state", timeout=5))["toys"][toy]["ip"]
    with wave.open(path) as w:
        assert w.getframerate() == 16000 and w.getnchannels() == 1, "need 16 kHz mono"
        pcm = w.readframes(w.getnframes())
    body, query = encode_for_atom(pcm)
    req = urllib.request.Request(f"http://{ip}/play?{query}", data=body, method="POST",
                                 headers={"Content-Type": "application/octet-stream"})
    urllib.request.urlopen(req, timeout=30).read()


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
