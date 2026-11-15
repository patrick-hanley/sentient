"""Mirror the brain's two pages on the Mac while the Jetson is busy (grading stops the brain):

  Parent Board  http://localhost:18090   the REAL board (brain/parent_web.py) on a local, encrypted profile folder. Set the PIN and
                                         add the child's notes here; port the folder to the Jetson afterwards (it is encrypted with
                                         the PIN, nothing machine-bound), then enter the PIN once on the Jetson's board.
  Dashboard     http://localhost:18080   dashboard.html, its requests proxied to the Jetson's dashboard through an ssh tunnel
                                         (--upstream); while the brain is down it shows the last answer it got (read-only).

    python tools/mirror_pages.py --parent-dir <folder> [--upstream http://127.0.0.1:18081]

Both listen on 127.0.0.1 only. No Gemma here: reading a worksheet photo needs the brain.
"""
from __future__ import annotations

import argparse
import logging
import sys
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from brain import parent as P, parent_web  # noqa: E402

DASH = (Path(__file__).resolve().parent.parent / "brain" / "dashboard.html").read_bytes()


def dash_handler(upstream: str):
    cache: dict[str, tuple[int, str, bytes]] = {}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass

        def _send(self, code, ctype, body):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _proxy(self, method):
            if method == "GET" and self.path in ("/", "/index.html"):
                return self._send(200, "text/html; charset=utf-8", DASH)
            n = int(self.headers.get("Content-Length") or 0)
            data = self.rfile.read(n) if n else (b"" if method == "POST" else None)
            try:
                req = urllib.request.Request(upstream + self.path, data=data, method=method)
                with urllib.request.urlopen(req, timeout=4) as r:
                    body, ctype = r.read(), r.headers.get("Content-Type", "application/octet-stream")
                    if method == "GET":
                        cache[self.path.split("?")[0]] = (r.status, ctype, body)
                    return self._send(r.status, ctype, body)
            except urllib.error.HTTPError as e:
                return self._send(e.code, "text/plain", e.read() or b"")
            except Exception:   # noqa: BLE001 - the brain is down (grading) or the tunnel is gone
                hit = cache.get(self.path.split("?")[0]) if method == "GET" else None
                if hit:
                    return self._send(*hit)
                return self._send(503, "application/json", b'{"error": "the brain is busy (grading); showing nothing live"}')

        def do_GET(self): self._proxy("GET")
        def do_POST(self): self._proxy("POST")

    return H


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--parent-dir", required=True)
    ap.add_argument("--parent-port", type=int, default=18090)
    ap.add_argument("--dash-port", type=int, default=18080)
    ap.add_argument("--upstream", default="http://127.0.0.1:18081")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    Path(a.parent_dir).mkdir(parents=True, exist_ok=True, mode=0o700)
    parent = P.Parent(directory=a.parent_dir)
    ThreadingHTTPServer.allow_reuse_address = True
    psrv = ThreadingHTTPServer(("127.0.0.1", a.parent_port), parent_web.make_handler(parent, None))
    dsrv = ThreadingHTTPServer(("127.0.0.1", a.dash_port), dash_handler(a.upstream.rstrip("/")))
    threading.Thread(target=dsrv.serve_forever, daemon=True).start()
    print(f"Parent Board: http://localhost:{a.parent_port}   Dashboard: http://localhost:{a.dash_port}", flush=True)
    if parent.setup_code:
        print(f"SETUP CODE {parent.setup_code}", flush=True)
    psrv.serve_forever()


if __name__ == "__main__":
    main()
