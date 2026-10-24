"""Run the brain.

  python -m brain.main                    # auto backend (LiteRT-LM if installed, else llama.cpp)
  python -m brain.main --cpu              # LiteRT on CPU (Pi 5)
  python -m brain.main --selftest         # voices, vision, LLM — no Atoms needed
Keyboard: c = canned scene, m = mute mics, i = idle chatter on/off, s <toy> <text> = say, q = quit
Dashboard: http://<brain-ip>:8080
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import config
from .atoms import AtomHub
from .director import Director, system_prompt
from .llm import make_backend
from .perception import Perceiver, Recognizer
from .tts import Voices
from .vad import Segmenter
from . import canned

log = logging.getLogger("brain")

PAGE = """<!doctype html><html><head><meta charset=utf-8><title>Sentient toys</title>
<style>body{background:#111;color:#eee;font-family:system-ui;margin:16px}.row{display:flex;gap:16px}
.toy{flex:1;background:#1c1c1c;padding:10px;border-radius:10px}.toy img{width:100%;border-radius:6px;background:#000}
.bar{height:8px;background:#333;border-radius:4px}.bar>div{height:8px;background:#4c4;border-radius:4px}
button{font-size:16px;margin:4px;padding:8px 14px}.talk{outline:3px solid #fc0}</style></head><body>
<h2>Sentient toys &mdash; Gemma 4 on-device brain <small id=be></small></h2>
<div class=row id=toys></div>
<p><b>Heard:</b> <span id=heard></span><br><b>Said:</b> <span id=said></span> <small id=lat></small></p>
<button onclick="post('canned')">Canned scene</button><button onclick="post('mute')">Mute mics</button>
<button onclick="post('idle')">Idle chatter</button>
<span>Enroll: <input id=nm placeholder=Name size=10><select id=et><option>pip<option selected>sage<option>noodle</select>
<label><input type=checkbox id=pet>pet</label><button onclick="enroll()">Enroll from camera</button></span>
<p id=flags></p>
<script>
const T=["pip","sage","noodle"];
document.getElementById('toys').innerHTML=T.map(t=>`<div class=toy id=b_${t}><h3>${t.toUpperCase()} <small id=s_${t}></small></h3>
<img id=i_${t}><div class=bar><div id=l_${t} style="width:0"></div></div><p id=v_${t}></p></div>`).join('');
function post(p){fetch('/'+p,{method:'POST'})}
function enroll(){fetch(`/enroll?toy=${et.value}&name=${encodeURIComponent(nm.value)}&pet=${pet.checked?1:0}`,{method:'POST'}).then(r=>r.text()).then(alert)}
async function tick(){const s=await (await fetch('/state')).json();be.textContent='('+s.backend+')';
for(const t of T){const x=s.toys[t];document.getElementById('s_'+t).textContent=x.online?(x.ip+(x.cam?'':' no-cam')):'offline';
document.getElementById('l_'+t).style.width=Math.min(100,x.level/30)+'%';document.getElementById('v_'+t).textContent=x.view;
document.getElementById('b_'+t).className='toy'+(s.talking==t?' talk':'');
if(x.online)document.getElementById('i_'+t).src='/frame/'+t+'.jpg?'+Date.now()}
heard.textContent=s.heard;said.textContent=s.said.map(l=>l[0].toUpperCase()+': '+l[1]).join('  /  ');
lat.textContent=s.latency?('('+s.latency.toFixed(1)+'s)'):'';flags.textContent=`muted=${s.muted} idle=${s.idle} canned/paused=${s.paused}`}
setInterval(tick,700);tick();
</script></body></html>"""


def make_handler(hub, eyes, director, rec):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype="text/plain"):
            b = body if isinstance(body, bytes) else body.encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def do_GET(self):
            u = urllib.parse.urlparse(self.path)
            if u.path == "/":
                return self._send(200, PAGE, "text/html")
            if u.path.startswith("/frame/"):
                v = eyes.views.get(u.path[7:].split(".")[0])
                return self._send(200, v.annotated, "image/jpeg") if v and v.annotated else self._send(404, "")
            if u.path == "/state":
                online = hub.online()
                st = {"backend": director.llm.name, "muted": hub.force_mute, "idle": director.idle_on,
                      "paused": director.paused, "talking": hub.talking, "heard": director.last_heard,
                      "said": director.last_lines, "latency": director.last_latency, "toys": {}}
                for t in config.TOY_ORDER:
                    a = hub.atoms.get(t)
                    st["toys"][t] = {"online": t in online, "ip": a.ip if a else "", "cam": bool(a and a.cam),
                                     "level": director.segs[t].level, "view": eyes.views[t].describe()}
                return self._send(200, json.dumps(st), "application/json")
            self._send(404, "")

        def do_POST(self):
            u = urllib.parse.urlparse(self.path)
            q = dict(urllib.parse.parse_qsl(u.query))
            if u.path == "/canned":
                threading.Thread(target=director.run_canned, daemon=True).start()
            elif u.path == "/mute":
                hub.force_mute = not hub.force_mute
            elif u.path == "/idle":
                director.idle_on = not director.idle_on
            elif u.path == "/enroll":
                return self._send(200, enroll_live(rec, hub, q.get("toy", "sage"), q.get("name", "").strip(),
                                                   q.get("pet") == "1"))
            self._send(200, "ok")
    return H


def enroll_live(rec, hub, toy, name, is_pet) -> str:
    import cv2
    import numpy as np
    from .enroll import enroll_person, enroll_pet
    if not name:
        return "Type a name first."
    imgs = []
    for _ in range(6):
        jpg = hub.capture(toy)
        if jpg:
            imgs.append(cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR))
        time.sleep(0.3)
    n = (enroll_pet if is_pet else enroll_person)(rec, name, imgs)
    rec.save_db()
    return f"{name}: {n}/{len(imgs)} frames enrolled from {toy}'s camera" + ("" if n else " — nothing detected, try closer/brighter")


def selftest(args):
    ok = True
    print("[voices]")
    v = Voices()
    for toy in config.TOY_ORDER:
        t = time.time()
        pcm = v.render(toy, "Hello! Let's play a game.")
        print(f"  {toy}: {len(pcm) / 32000:.1f}s audio in {time.time() - t:.1f}s")
    print("[vision]")
    import cv2
    rec = Recognizer()
    sheet = config.ROOT / "aruco_sheet.png"
    if sheet.exists():
        img = cv2.resize(cv2.imread(str(sheet)), (640, 828))
        print("  tags on sheet:", sorted({t.label for t in rec.analyze(img)}))
    print("  mediapipe pets/books:", "on" if rec.obj else "OFF")
    print("[llm]")
    try:
        llm = make_backend(args.backend, system_prompt(), gpu=not args.cpu)
        t = time.time()
        out = llm.ask("[SCENE] PIP is looking at the child. SAGE sees PIP.\n[EVENT] The child waved hello. PIP and SAGE say hi.")
        print(f"  {llm.name} answered in {time.time() - t:.1f}s:\n    " + out.replace("\n", "\n    "))
    except Exception as e:  # noqa: BLE001
        ok = False
        print("  LLM FAILED:", e)
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", default="auto", choices=["auto", "litert", "llamacpp"])
    ap.add_argument("--cpu", action="store_true", help="LiteRT on CPU only (Pi 5)")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("-v", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.v else logging.INFO,
                        format="%(asctime)s %(name)-10s %(message)s", datefmt="%H:%M:%S")
    if args.selftest:
        sys.exit(selftest(args))

    voices = Voices()
    log.info("pre-rendering canned scene + fillers…")
    voices.prerender(canned.SCENE + [(t, f) for t, fs in canned.FILLERS.items() for f in fs])
    llm = make_backend(args.backend, system_prompt(), gpu=not args.cpu)

    segs = {}
    director = None
    hub = AtomHub(on_audio=lambda toy, pcm: segs[toy].feed(pcm) if toy in segs else None,
                  on_button=lambda toy, kind: director.on_button(toy, kind))
    rec = Recognizer()
    eyes = Perceiver(hub, rec)
    director = Director(hub, voices, eyes, llm, segs)
    for t in config.TOY_ORDER:
        segs[t] = Segmenter(t, director.utter_q)
    eyes.on_seen = director.on_seen
    hub.start()
    eyes.start()
    director.start()
    srv = ThreadingHTTPServer(("0.0.0.0", config.DASH_PORT), make_handler(hub, eyes, director, rec))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    log.info("brain up — dashboard http://0.0.0.0:%d  (c=canned m=mute i=idle s <toy> <text> q=quit)", config.DASH_PORT)

    if not sys.stdin.isatty():   # running as a service / in the background: dashboard only
        while True:
            time.sleep(3600)
    for line in sys.stdin:
        cmd = line.strip()
        if cmd == "q":
            break
        if cmd == "c":
            threading.Thread(target=director.run_canned, daemon=True).start()
        elif cmd == "m":
            hub.force_mute = not hub.force_mute
            print("mics muted" if hub.force_mute else "mics live")
        elif cmd == "i":
            director.idle_on = not director.idle_on
            print("idle chatter", director.idle_on)
        elif cmd.startswith("s "):
            _, toy, text = cmd.split(" ", 2)
            threading.Thread(target=hub.play, args=(toy, voices.render(toy, text)), daemon=True).start()
        elif cmd:
            print("online:", hub.online(), "|", eyes.scene_text())


if __name__ == "__main__":
    main()
