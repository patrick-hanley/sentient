"""The Parent Board web server: its own port (8090), its own handler, separate from the toys' open dashboard on 8080.

Security notes (docs/parent-board.md has the full threat list):
  * Every API call except /api/status, /api/setup and /api/login needs a session cookie (HttpOnly, SameSite=Strict,
    5 minutes idle). Every POST also needs the header X-PB: 1 and a JSON body, so a page on another site cannot drive it.
  * The Host header must be an IP address, localhost or a bare / .local name (blocks DNS-rebinding tricks).
  * Plain HTTP: it is meant for the home Wi-Fi. The PIN can be read by anyone who can sniff that network; use a trusted
    network and a PIN you do not reuse. (HTTPS would need a certificate the phone trusts; noted as a later step.)
  * Request bodies are never logged. Nothing here is linked from the toys' dashboard.
"""
from __future__ import annotations

import http.cookies
import json
import logging
import re
import threading
import urllib.parse
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import config, curriculum_picks, teach
from . import parent as P
from . import scripted
from . import coaching, metrics, report          # progress / coaching views (docs/metrics.md)
from .progress import ProgressStore

log = logging.getLogger("parent-web")

HOST_OK = re.compile(r"^(\d{1,3}(\.\d{1,3}){3}|\[[0-9a-f:]+\]|localhost|[a-z0-9-]+(\.local)?)(:\d+)?$", re.I)
MAX_JSON, MAX_PHOTO = 64 * 1024, 8 * 1024 * 1024
PUBLIC = {"/", "/api/status", "/api/setup", "/api/login"}


def make_handler(parent: P.Parent, director=None):
    class H(BaseHTTPRequestHandler):
        server_version = "ParentBoard"
        sys_version = ""
        timeout = 15   # a stalled or trickling connection is dropped (one thread each otherwise)

        def log_message(self, *a):   # no request logging: paths and bodies can carry a child's details
            pass

        def _send(self, code, body, ctype="application/json", cookie=None):
            b = body if isinstance(body, bytes) else (json.dumps(body) if not isinstance(body, str) else body).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype + ("; charset=utf-8" if ctype.startswith("text") or ctype == "application/json" else ""))
            self.send_header("Content-Length", str(len(b)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
                                                        "connect-src 'self'; img-src 'self' data:; form-action 'none'; base-uri 'none'")
            if cookie is not None:
                self.send_header("Set-Cookie", cookie)
            self.end_headers()
            self.wfile.write(b)

        def _token(self):
            c = http.cookies.SimpleCookie(self.headers.get("Cookie", ""))
            return c["pb"].value if "pb" in c else None

        def _cookie(self, token):
            return f"pb={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age={P.SESSION_IDLE_S}" if token else "pb=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0"

        def _guard(self, path, post):
            if not HOST_OK.match(self.headers.get("Host", "")):
                self._send(400, {"error": "bad host"})
                return False
            if post and self.headers.get("X-PB") != "1":
                self._send(403, {"error": "forbidden"})
                return False
            if path not in PUBLIC and not parent.check(self._token()):
                self._send(401, {"error": "locked"})
                return False
            return True

        def _length(self, limit):
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                raise ValueError("bad request")
            if n < 0 or n > limit:   # a negative length would make read() consume the whole connection into memory
                raise ValueError("bad request")
            return n

        def _json(self):
            n = self._length(MAX_JSON)
            if "json" not in (self.headers.get("Content-Type") or ""):
                raise ValueError("bad request")
            data = json.loads(self.rfile.read(n) or b"{}")
            if not isinstance(data, dict):
                raise ValueError("bad request")
            return data

        # ---------------- GET ----------------
        def do_GET(self):
            u = urllib.parse.urlparse(self.path)
            if not self._guard(u.path, False):
                return
            q = dict(urllib.parse.parse_qsl(u.query))
            try:
                if u.path == "/":
                    return self._send(200, PAGE, "text/html")
                if u.path == "/api/status":
                    return self._send(200, parent.status())
                if u.path == "/api/state":
                    parent.sweep()
                    bound = parent.bound_child()
                    return self._send(200, {
                        "children": parent.children(), "bound": bound["id"] if bound else None,
                        "categories": [{"id": i, "label": l} for i, l in P.CATEGORIES],
                        "settings": parent.index["settings"], "checkin_due": parent.checkin_due(),
                        "cues": [{"id": k, "label": v["label"]} for k, v in scripted.CUES.items()],
                        "toys_online": list(director.hub.online()) if director else [],
                        "gemma": bool(director and hasattr(director.llm, "complete"))})
                if u.path == "/api/progress":      # numbers-only session history + the toys' coaching state for one child
                    data = ProgressStore(parent).load(q.get("child", ""))
                    sessions = [dict(x, notes=metrics.qualitative(x)) for x in data["sessions"]]
                    return self._send(200, {"sessions": sessions, "coach": coaching.describe(data["coach"]), "targets": metrics.TARGETS,
                                            "labels": metrics.LABELS, "categories": list(metrics.CATEGORIES)})
                if u.path == "/api/progress/export":   # generated on demand, never stored
                    data = ProgressStore(parent).load(q.get("child", ""))
                    sess = next((x for x in data["sessions"] if x.get("id") == q.get("session")), None)
                    if not sess:
                        return self._send(404, {"error": "no such session"})
                    name = next((c["name"] for c in parent.children() if c["id"] == q.get("child")), None)
                    return self._send(200, report.session_markdown(sess, name), "text/markdown")
                if u.path == "/api/items":
                    return self._send(200, {"items": parent.view(q.get("child", ""))})
                if u.path == "/api/curriculum":   # read-only: what the toys can teach at this child's grade, with the parent's picks
                    return self._send(200, curriculum_picks.overview(parent, q.get("child", "")))
                if u.path == "/api/teach/list":   # Teach the camera (brain/teach.py): names and counts, never vectors
                    teacher = getattr(parent, "teacher", None)
                    if not teacher:
                        return self._send(200, {"entries": [], "toys": [], "ready": False})
                    hub = director.hub if director else None
                    online = set(hub.online()) if hub else set()
                    return self._send(200, {"ready": True, "entries": teacher.store.list(), "toys": [
                        {"id": k, "name": t["name"], "online": k in online, "cam": bool(hub and k in hub.atoms and hub.atoms[k].cam)}
                        for k, t in config.TOYS.items()]})
                if u.path in ("/api/photo/status", "/api/sort/status"):
                    return self._send(200, parent.jobs.get(q.get("job", ""), {"status": "unknown"}))
            except P.Locked:
                return self._send(401, {"error": "locked"})
            except KeyError:
                return self._send(404, {"error": "no such child"})
            self._send(404, {"error": "not found"})

        # ---------------- POST ----------------
        def do_POST(self):
            u = urllib.parse.urlparse(self.path)
            if not self._guard(u.path, True):
                return
            q = dict(urllib.parse.parse_qsl(u.query))
            try:
                if u.path == "/api/photo":
                    n = self._length(MAX_PHOTO)
                    if not (self.headers.get("Content-Type") or "").startswith("image/"):
                        return self._send(400, {"error": "bad photo"})
                    data = self.rfile.read(n)
                    job = parent.read_worksheet(q.get("child", ""), data, director.llm if director else None,
                                                busy=lambda: bool(director and (director.busy or director.child_speaking())))
                    return self._send(200, {"job": job})
                if u.path == "/api/teach/photo":   # one photo, embedded in RAM and dropped: only the vector is kept
                    teacher = self._teacher()
                    n = self._length(MAX_PHOTO)
                    if not (self.headers.get("Content-Type") or "").startswith("image/"):
                        return self._send(400, {"error": "bad photo"})
                    img = teach.decode(self.rfile.read(n))
                    if img is None:
                        return self._send(400, {"error": "That photo could not be read (export it as JPEG)."})
                    return self._send(200, teacher.enroll(q.get("kind", ""), q.get("name", ""), [img], q.get("consent") == "1",
                                                          role=q.get("role"), child=q.get("child") or None))
                b = self._json()
                return self._post(u.path, b)
            except P.Locked:
                return self._send(401, {"error": "locked"})
            except P.RateLimited as e:
                return self._send(429, {"error": str(e), "wait": int(e.seconds)})
            except P.WrongPin:
                return self._send(403, {"error": "That PIN is not right."})
            except KeyError:
                return self._send(404, {"error": "no such child"})
            except (ValueError, RuntimeError) as e:
                return self._send(400, {"error": str(e)})
            except Exception:  # noqa: BLE001 — never echo internals to a browser
                log.exception("parent board request failed")
                return self._send(500, {"error": "something went wrong"})

        def _teacher(self):
            teacher = getattr(parent, "teacher", None)
            if not teacher:
                raise RuntimeError("The camera cannot be taught on this brain.")
            return teacher

        def _post(self, path, b):
            if path == "/api/teach/capture":   # the parent pressed the button: that toy's camera is on for these few frames only
                teacher = self._teacher()
                kind = str(b.get("kind", ""))
                name = str(b.get("name", ""))
                if b.get("consent") is not True:   # before any camera is touched
                    raise ValueError("A parent has to agree first (tick the consent box).")
                imgs = teacher.capture(str(b.get("toy", "")), shots=6)
                return self._send(200, teacher.enroll(kind, name, imgs, b.get("consent") is True,
                                                      role=b.get("role"), child=b.get("child") or None))
            if path == "/api/teach/delete":
                self._teacher().store.delete(str(b.get("id", "")))
                return self._send(200, {"ok": True})
            if path == "/api/setup":
                tok = parent.setup(str(b.get("pin", "")), str(b.get("code", "")))
                return self._send(200, {"ok": True}, cookie=self._cookie(tok))
            if path == "/api/login":
                tok = parent.login(str(b.get("pin", "")))
                return self._send(200, {"ok": True}, cookie=self._cookie(tok))
            if path == "/api/logout":
                parent.logout(self._token())
                return self._send(200, {"ok": True}, cookie=self._cookie(None))
            if path == "/api/child/add":
                return self._send(200, parent.add_child(str(b.get("name", ""))))
            if path == "/api/child/delete":
                parent.delete_child(str(b.get("id", "")))
                if getattr(parent, "teacher", None):
                    parent.teacher.store.forget_child(str(b.get("id", "")))   # their enrolled face goes too
                return self._send(200, {"ok": True})
            if path == "/api/sort":
                text = str(b.get("text", ""))[:6000]
                if not text.strip():
                    return self._send(400, {"error": "Type or paste something first."})
                job = parent.sort_dump(text, director.llm if director else None,
                                       busy=lambda: bool(director and (director.busy or director.child_speaking())))
                return self._send(200, {"job": job})
            if path == "/api/parse":
                res = P.parse_text(str(b.get("text", ""))[:1000])
                return self._send(200, res)
            if path == "/api/items/add":
                return self._send(200, {"added": parent.add_items(str(b.get("child", "")), b.get("cards") or [])})
            if path == "/api/items/delete":
                parent.delete_item(str(b.get("child", "")), str(b.get("id", "")))
                return self._send(200, {"ok": True})
            if path == "/api/items/confirm":
                parent.confirm_item(str(b.get("child", "")), str(b.get("id", "")))
                return self._send(200, {"ok": True})
            if path == "/api/items/clear":
                parent.clear_child(str(b.get("child", "")), b.get("kinds") if isinstance(b.get("kinds"), list) else None)
                return self._send(200, {"ok": True})
            if path == "/api/curriculum/pick":   # boost / skip / clear one topic: stored as a normal Parent Board item
                curriculum_picks.set_pick(parent, str(b.get("child", "")), str(b.get("id", "")), str(b.get("mode", "")))
                return self._send(200, {"ok": True})
            if path == "/api/nowplaying":
                parent.now_playing(b.get("child") or None)
                return self._send(200, {"ok": True})
            if path == "/api/cue":
                if not director:
                    return self._send(503, {"error": "toys are not connected"})
                return self._send(200, director.cue(str(b.get("text", ""))[:200], b.get("cue"), bool(b.get("urgent"))))
            if path in ("/api/progress/clear", "/api/progress/session/delete", "/api/coach"):
                return self._progress_post(path, b)
            if path == "/api/checkin/done":
                parent.checkin_done()
                return self._send(200, {"ok": True})
            if path == "/api/settings":
                parent.set_settings(checkin_day=b.get("checkin_day"), checkin_hour=b.get("checkin_hour"), notes_on=b.get("notes_on"), child_memory=b.get("child_memory"))
                return self._send(200, {"ok": True})
            if path == "/api/pin/change":
                parent.change_pin(str(b.get("old", "")), str(b.get("new", "")), keep=self._token())
                return self._send(200, {"ok": True})
            if path == "/api/lock":
                parent.lock()
                return self._send(200, {"ok": True}, cookie=self._cookie(None))
            if path == "/api/wipe":
                if b.get("confirm") != "DELETE":
                    return self._send(400, {"error": "type DELETE to confirm"})
                parent.wipe_all(str(b.get("pin", "")))
                return self._send(200, {"ok": True}, cookie=self._cookie(None))
            self._send(404, {"error": "not found"})

        def _progress_post(self, path, b):
            cid, store = str(b.get("child", "")), ProgressStore(parent)
            if path == "/api/progress/clear":
                store.clear(cid)
            elif path == "/api/progress/session/delete":
                store.delete_session(cid, str(b.get("id", "")))
            else:       # /api/coach: the parent's controls over what the toys adapt
                act, rid = b.get("action"), str(b.get("id", ""))
                if act in ("enable", "disable"):
                    store.mutate_coach(cid, lambda st: coaching.set_enabled(st, act == "enable"))
                elif act == "undo":
                    store.mutate_coach(cid, lambda st: coaching.undo(st, rid))
                elif act == "reset":
                    store.mutate_coach(cid, coaching.reset)
                elif act == "review":
                    store.mutate_coach(cid, lambda st: coaching.resolve_review(st, rid, str(b.get("decision", ""))))
                else:
                    return self._send(400, {"error": "unknown action"})
            if director:
                director.live.refresh(cid)     # the toys pick up the change at once
            return self._send(200, {"ok": True})

    return H


def serve(parent, director=None, port: int = 8090):
    srv = ThreadingHTTPServer(("0.0.0.0", port), make_handler(parent, director))
    threading.Thread(target=srv.serve_forever, daemon=True, name="parent-board").start()
    log.info("Parent Board on port %d (home network only; first visit sets the family PIN)", port)
    return srv


PAGE = (Path(__file__).with_name("parent.html")).read_text(encoding="utf-8")
