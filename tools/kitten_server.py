"""Kitten TTS sidecar: the brain's Python 3.13 cannot install kittentts (misaki needs <3.13), so it runs
in its own 3.12 venv and serves speech over loopback. POST /tts?voice=Jasper&speed=1.0, body = text,
reply = 24 kHz mono int16 PCM. GET /voices lists voices. Pi: see deploy/sentient-kitten.service."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import sys
import threading
import urllib.parse

import numpy as np

MODEL = "KittenML/kitten-tts-nano-0.8-int8"
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8099


def main():
    from kittentts import KittenTTS
    tts, lock = KittenTTS(MODEL), threading.Lock()
    tts.generate("Warm up.", voice="Jasper")

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _reply(self, code, body, ctype="application/octet-stream"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            self._reply(200, json.dumps(list(tts.available_voices)).encode(), "application/json")

        def do_POST(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            text = self.rfile.read(int(self.headers.get("Content-Length", 0))).decode("utf-8", "replace")
            try:
                with lock:
                    audio = tts.generate(text, voice=q.get("voice", ["Jasper"])[0], speed=float(q.get("speed", ["1.0"])[0]))
                pcm = (np.clip(np.asarray(audio, np.float32).squeeze(), -1, 1) * 32767).astype("<i2").tobytes()
                self._reply(200, pcm)
            except Exception as e:  # noqa: BLE001
                self._reply(500, str(e).encode(), "text/plain")

    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()


if __name__ == "__main__":
    main()
