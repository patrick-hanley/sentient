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
.bar{height:8px;background:#333;border-radius:4px}.vs{font-size:13px;line-height:1.9;border-top:1px solid #333;margin-top:6px;padding-top:6px}.vs label{display:inline-block;margin-right:8px}
.vs input[type=range]{width:110px;vertical-align:middle}.line{font-size:13px;margin:2px 0;padding:4px 8px;display:block;text-align:left;width:100%}
.voice{font-size:13px;line-height:1.5;color:#cfd2ee;border-top:1px solid #333;padding-top:6px}.dim{color:#8b8fb0}.bar>div{height:8px;background:#4c4;border-radius:4px}
button{font-size:16px;margin:4px;padding:8px 14px}.talk{outline:3px solid #fc0}</style></head><body>
<h2>Sentient toys &mdash; Gemma 4 on-device brain <small id=be></small></h2>
<div class=row id=toys></div>
<p><b>Heard:</b> <span id=heard></span><br><b>Said:</b> <span id=said></span> <small id=lat></small></p>
<details><summary>Latency stages (milliseconds)</summary><pre id=stages></pre></details>
<button id=muteall onclick="post('muteall')">Mute all toys</button><button onclick="post('mute')">Mute mics</button>
<button onclick="post('idle')">Idle chatter</button>
<span>Say: <select id=st><option>dyno<option>sage<option>penny</select><input id=sx size=30>
<button onclick="fetch(`/say?toy=${st.value}&text=${encodeURIComponent(sx.value)}`,{method:'POST'})">Speak</button></span><br>
<span>Enroll: <input id=nm placeholder=Name size=10><select id=et><option>dyno<option selected>sage<option>penny</select>
<label><input type=checkbox id=pet>pet</label><button onclick="enroll()">Enroll from camera</button></span>
<p id=flags></p>
<h3>Sound effects <small class=dim>(CC0 from freesound.org &mdash; Gemma can use them too: {knock} …)</small></h3>
<div>Play on <select id=sfxt><option>dyno<option>sage<option>penny</select> <span id=sfx></span></div>
<h3>Canned lines <small class=dim>(stored on each toy &mdash; play instantly)</small></h3><div id=canned></div>
<script>
const T=["dyno","sage","penny"];
document.getElementById('toys').innerHTML=T.map(t=>`<div class=toy id=b_${t}><h3>${t.toUpperCase()} <small id=s_${t}></small></h3>
<img id=i_${t}><div class=bar><div id=l_${t} style="width:0"></div></div><p id=v_${t}></p>
<p class=voice id=vc_${t}></p><p class=voice id=hl_${t}></p>
<div class=vs><b>Speaker volume</b> <input type=range id=hv_${t} min=0 max=255 step=5 onchange="setVol('${t}',this.value)" style="width:150px;vertical-align:middle">
<span id=hvv_${t}></span> <button onclick="setVol('${t}',0)">Mute</button></div><div class=vs id=vs_${t}></div></div>`).join('');
function post(p){fetch('/'+p,{method:'POST'})}
function enroll(){fetch(`/enroll?toy=${et.value}&name=${encodeURIComponent(nm.value)}&pet=${pet.checked?1:0}`,{method:'POST'}).then(r=>r.text()).then(alert)}
async function tick(){const s=await (await fetch('/state')).json();be.textContent='('+s.backend+')';
for(const t of T){const x=s.toys[t];document.getElementById('s_'+t).textContent=x.online?(x.ip+(x.cam?'':' no-cam')):'offline';
document.getElementById('l_'+t).style.width=Math.min(100,x.level/30)+'%';document.getElementById('v_'+t).textContent=x.view;
const h=x.health||{};const hc=(+h.sfail||+h.mfail)?'#f66':((+h.sfix||+h.mfix)?'#fc6':'#8b8fb0');
document.getElementById('hl_'+t).innerHTML=h.fw?`<span style="color:${hc}">Speaker repairs ${h.sfix||0}${+h.sfail?` (failed ${h.sfail})`:''} · mic repairs ${h.mfix||0}${+h.mfail?` (failed ${h.mfail})`:''}</span> · ${h.clips} clips on toy · ${h.fw}`:'';
{const hv=document.getElementById('hv_'+t),v=h.vol;if(v!==undefined&&v!==null&&document.activeElement!==hv){hv.value=v;
 document.getElementById('hvv_'+t).textContent=(+v===0?'muted':v+'/255');}}
const vc=x.voice||{};document.getElementById('vc_'+t).innerHTML=vc.engine?`<b>Voice:</b> ${vc.label} <span class=dim>(${vc.engine} ${vc.quant||''}, ${vc.id})</span><br>speed ${vc.speed} · pitch ${vc.pitch}`+(vc.last?`<br><span class=dim>last line: ${vc.last}</span>`:''):'';
document.getElementById('b_'+t).className='toy'+(s.talking==t?' talk':'');
if(x.online)document.getElementById('i_'+t).src='/frame/'+t+'.jpg?'+Date.now()}
heard.textContent=s.heard;said.textContent=s.said.map(l=>l[0].toUpperCase()+': '+l[1]).join('  /  ');
document.getElementById('muteall').textContent=T.some(t=>s.toys[t].online&&+((s.toys[t].health||{}).vol??200)>0)?'Mute all toys':'Unmute all toys';
lat.textContent=s.latency?('reply upload after '+s.latency.toFixed(2)+'s; speaker onset unmeasured'):'';
stages.textContent=JSON.stringify(s.latency_breakdown,null,2);
flags.textContent=`profile=${s.latency_profile} device=${s.device} muted=${s.muted} idle=${s.idle} canned/paused=${s.paused}`}
let VO={};
async function loadVoices(){VO=await (await fetch('/voices')).json();for(const t of T)renderVS(t,VO.toys[t]);}
function slider(t,k,label,lo,hi,v){return `<label>${label} <input type=range id=${k}_${t} min=${lo} max=${hi} step=0.05 value=${v} oninput="document.getElementById('${k}v_${t}').textContent=this.value"> <span id=${k}v_${t}>${v}</span></label>`;}
function renderVS(t,s){const opts=e=>(VO[e]||[]).map(v=>`<option ${v==s.voice?'selected':''}>${v}</option>`).join('');
 document.getElementById('vs_'+t).innerHTML=`<b>Voice settings</b><br>
 <label>Engine <select id=en_${t} onchange="engChange('${t}')"><option value=kokoro ${s.engine=='kokoro'?'selected':''} ${VO.kokoro.length?'':'disabled'}>Kokoro</option><option value=piper ${s.engine=='piper'?'selected':''}>Piper</option></select></label>
 <label>Voice <select id=vo_${t}>${opts(s.engine)}</select></label><br>
 ${slider(t,'speed','Speed',0.6,1.6,s.speed)}${slider(t,'pitch','Pitch',0.7,1.6,s.pitch)}<br>${slider(t,'volume','Voice gain',0.2,2.5,s.volume)}
 <label id=spk_${t} style="display:${s.engine=='piper'?'inline-block':'none'}">Speaker # <input id=sp_${t} type=number min=0 max=903 value="${s.speaker??''}" style="width:60px"></label><br>
 <button onclick="applyV('${t}')">Apply</button><button onclick="testV('${t}')">Test</button> <span id=vm_${t} class=dim></span>`;}
function engChange(t){const e=document.getElementById('en_'+t).value;document.getElementById('vo_'+t).innerHTML=(VO[e]||[]).map(v=>`<option>${v}</option>`).join('');document.getElementById('spk_'+t).style.display=e=='piper'?'inline-block':'none';}
async function applyV(t){const g=k=>document.getElementById(k+'_'+t).value;
 const r=await fetch(`/voice?toy=${t}&engine=${g('en')}&voice=${encodeURIComponent(g('vo'))}&speed=${g('speed')}&pitch=${g('pitch')}&volume=${g('volume')}&speaker=${g('sp')}`,{method:'POST'});
 document.getElementById('vm_'+t).textContent=r.ok?'saved — re-storing its clips in the new voice':('error: '+await r.text());}
function testV(t){fetch(`/say?toy=${t}&text=${encodeURIComponent('Hi! This is how I sound now. Do you like my voice?')}`,{method:'POST'});}
async function loadCanned(){const c=await (await fetch('/canned')).json();
 let h='<b>Scenes:</b> '+c.scenes.map(s=>`<button onclick="post('canned?scene=${encodeURIComponent(s)}')">&#9654; ${s}</button>`).join('');
 h+='<div class=row>'+T.map(t=>`<div class=toy><b>${t.toUpperCase()}</b>`+Object.entries(c.lines[t]).filter(([g,ls])=>ls.length).map(([g,ls])=>
   `<div class=dim>${g}</div>`+ls.map(x=>`<button class=line data-x="${x.replace(/&/g,'&amp;').replace(/"/g,'&quot;')}" onclick="playLine('${t}',this.dataset.x)">${x}</button>`).join('')).join('')+'</div>').join('')+'</div>';
 document.getElementById('canned').innerHTML=h;}
function playLine(t,x){fetch(`/playline?toy=${t}&text=${encodeURIComponent(x)}`,{method:'POST'});}
function setVol(t,v){fetch(`/speaker?toy=${t}&vol=${v}`,{method:'POST'});document.getElementById('hvv_'+t).textContent=(+v===0?'muted':v+'/255');}
async function loadSfx(){const s=await (await fetch('/sfx')).json();const groups={character:'Character',story:'Story',halloween:'Halloween'};
 document.getElementById('sfx').innerHTML=Object.entries(groups).map(([g,label])=>`<div><span class=dim>${label}:</span> `+
  Object.entries(s).filter(([n,v])=>(v.set||'story')==g).map(([n,v])=>`<button title="${v.desc}${v.owner?' ('+v.owner+')':''}" onclick="playLine(sfxt.value,'{${n}}')">${n.replace('_',' ')}</button>`).join(' ')+'</div>').join('');}
loadVoices();loadCanned();loadSfx();
setInterval(tick,700);tick();
</script></body></html>"""


def make_handler(hub, eyes, director, rec, voices):
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
            if u.path == "/canned":
                lines = {t: {"Fillers": canned.FILLERS.get(t, []), "Greeting": [canned.GREETINGS[t]] if t in canned.GREETINGS else [],
                             **{name: [x for w, x in sc if w == t] for name, sc in canned.SCENES.items()}}
                         for t in config.TOY_ORDER}
                return self._send(200, json.dumps({"scenes": list(canned.SCENES), "lines": lines}), "application/json")
            if u.path == "/sfx":
                return self._send(200, json.dumps({n: dict(v, owner=v.get("toy")) for n, v in voices.sounds.index.items()}),
                                  "application/json")
            if u.path == "/voices":
                return self._send(200, json.dumps({"kokoro": voices.kokoro_voices(), "piper": voices.piper_voices(),
                                                   "toys": {t: voices.settings(t) for t in config.TOY_ORDER}}),
                                  "application/json")
            if u.path == "/state":
                online = hub.online()
                st = {"backend": director.llm.name, "muted": hub.force_mute, "idle": director.idle_on,
                      "paused": director.paused, "talking": hub.talking, "heard": director.last_heard,
                      "said": director.last_lines, "latency": director.last_latency,
                      "latency_breakdown": director.latency_state(), "latency_profile": config.LATENCY_PROFILE,
                      "device": getattr(director.llm, "device", "server-configured"), "toys": {}}
                for t in config.TOY_ORDER:
                    a = hub.atoms.get(t)
                    st["toys"][t] = {"online": t in online, "ip": a.ip if a else "", "cam": bool(a and a.cam),
                                     "level": director.segs[t].level, "view": eyes.views[t].describe(),
                                     "voice": voices.describe(t),
                                     "health": {k: a.flags.get(k) for k in ("fw", "sfix", "sfail", "mfix", "mfail", "vol")}
                                               | {"clips": len(a.clips), "fs_used": a.fs[1], "fs_total": a.fs[0]} if a else {}}
                return self._send(200, json.dumps(st), "application/json")
            self._send(404, "")

        def do_POST(self):
            u = urllib.parse.urlparse(self.path)
            q = dict(urllib.parse.parse_qsl(u.query))
            if u.path == "/canned":
                threading.Thread(target=director.run_canned, args=(q.get("scene"),), daemon=True).start()
            elif u.path == "/playline" and q.get("toy") in config.TOYS and q.get("text"):
                threading.Thread(target=hub.play_line, args=(q["toy"], q["text"], voices), daemon=True).start()
            elif u.path == "/voice" and q.get("toy") in config.TOYS:
                try:
                    new = voices.apply(q["toy"], q.get("engine", ""), q.get("voice", ""), q.get("speed", 1),
                                       q.get("pitch", 1), q.get("volume", 1), q.get("speaker"))
                except (ValueError, TypeError) as e:
                    return self._send(400, str(e))
                getattr(hub, "resync", lambda t: None)(q["toy"])   # re-store its clips in the new voice
                return self._send(200, json.dumps(new), "application/json")
            elif u.path == "/speaker" and q.get("toy") in config.TOYS and q.get("vol", "").isdigit():
                ok = hub.set_volume(q["toy"], int(q["vol"]))
                return self._send(200 if ok else 502, "ok" if ok else "toy unreachable")
            elif u.path == "/muteall":
                online = hub.online()
                if any(int(hub.atoms[t].flags.get("vol", 200)) > 0 for t in online):   # mute, remember levels
                    hub.saved_vol = {t: int(hub.atoms[t].flags.get("vol", 200)) for t in online}
                    for t in online:
                        hub.set_volume(t, 0)
                else:                                                                    # unmute to saved levels
                    for t in online:
                        hub.set_volume(t, getattr(hub, "saved_vol", {}).get(t, 200) or 200)
            elif u.path == "/mute":
                hub.force_mute = not hub.force_mute
            elif u.path == "/idle":
                director.idle_on = not director.idle_on
            elif u.path == "/say" and q.get("toy") in config.TOYS and q.get("text"):
                threading.Thread(target=hub.play, args=(q["toy"], voices.render(q["toy"], q["text"])), daemon=True).start()
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


def make_clip_sync(hub, voices, director):
    """Store each toy's fixed lines (fillers, its canned-scene lines, offline greeting) in its own
    flash, so they play instantly and without the network. Only missing clips are uploaded."""
    def sync(toy):
        time.sleep(2)   # let the Atom finish connecting
        if hub.atoms[toy].flags.get("fw") == "toy-client-3":   # upload/clear can crash that build
            log.warning("%s: firmware toy-client-3 — reflash to 3.1 to store clips; lines stream meanwhile", toy)
            hub.list_clips(toy)   # still use the clips already stored
            return
        have = hub.list_clips(toy)
        if have is None:
            log.info("%s: firmware has no clip storage — fixed lines will stream", toy)
            return
        greet = canned.GREETINGS.get(toy)
        lines = list(canned.FILLERS.get(toy, [])) + [x for sc in canned.SCENES.values() for t, x in sc if t == toy]
        lines += [greet] if greet else []
        rank = {"character": 0, "story": 1, "halloween": 2}   # store in this order; the rest streams
        snd = sorted(voices.sounds.names(toy), key=lambda n: (rank.get(voices.sounds.index[n].get("set"), 1), n))
        lines += ["{%s}" % n for n in snd]
        needed = {voices.clip_id(toy, x) for x in lines} | {"hello"}
        if set(have) - needed:   # old voice/text versions: clear the flash and store a fresh set
            hub.clear_clips(toy)
            have = {}
        uploaded = 0
        for text in lines:
            cid = voices.clip_id(toy, text)
            if cid in have:
                continue
            while director.busy or director.paused:   # never compete with a live turn
                time.sleep(0.5)
            pcm = voices.render(toy, text, persist=True)
            total, used = hub.atoms[toy].fs
            if total and used + len(pcm) // 2 + 16384 > total * 0.9:   # keep ~10% free; later lines stream
                log.info("%s: clip storage full (%d/%d KB) — remaining lines/sounds will stream", toy, used // 1024, total // 1024)
                break
            if hub.put_clip(toy, cid, pcm):
                uploaded += 1
        if greet:   # "hello" is the fixed name the firmware plays when no brain is reachable
            gid = voices.clip_id(toy, greet)
            if abs(have.get("hello", -1) - hub.atoms[toy].clips.get(gid, -2)) > 1e-3:
                hub.put_clip(toy, "hello", voices.render(toy, greet, persist=True))
        log.info("%s: %d clips stored on the Atom (%d uploaded now)", toy, len(hub.atoms[toy].clips), uploaded)
    return sync


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
        out = llm.ask("[SCENE] DYNO is looking at the child. SAGE sees DYNO.\n[EVENT] The child waved hello. DYNO and SAGE say hi.")
        print(f"  {llm.name} answered in {time.time() - t:.1f}s:\n    " + out.replace("\n", "\n    "))
    except Exception as e:  # noqa: BLE001
        ok = False
        print("  LLM FAILED:", e)
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", default="auto", choices=["auto", "litert", "llamacpp", "geniex"])
    ap.add_argument("--cpu", action="store_true", help="LiteRT on CPU only (Pi 5)")
    ap.add_argument("--latency-profile", choices=["responsive", "patient"], default="responsive",
                    help="responsive: 500ms endpoint + streaming; patient: 700ms endpoint and fillers")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("-v", action="store_true")
    args = ap.parse_args()
    config.apply_latency_profile(args.latency_profile)
    logging.basicConfig(level=logging.DEBUG if args.v else logging.INFO,
                        format="%(asctime)s %(name)-10s %(message)s", datefmt="%H:%M:%S")
    if args.selftest:
        sys.exit(selftest(args))

    voices = Voices()
    log.info("pre-rendering canned scene + fillers…")
    voices.prerender([(t, f) for t, fs in canned.FILLERS.items() for f in fs])
    # Kokoro is slower than real time on a Pi: render the canned scene in the background, only
    # when no live speech or turn needs the voice engine (and only once: it's cached on disk).
    threading.Thread(target=voices.prerender, args=([l for sc in canned.SCENES.values() for l in sc],), kwargs={"polite": True},
                     daemon=True, name="prerender").start()
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
    eyes.hold = lambda: director.busy or director.paused
    voices.busy = lambda: director.busy
    hub.on_online = make_clip_sync(hub, voices, director)
    hub.resync = lambda toy: threading.Thread(target=hub.on_online, args=(toy,), daemon=True).start()
    hub.start()
    eyes.start()
    director.start()
    srv = ThreadingHTTPServer(("0.0.0.0", config.DASH_PORT), make_handler(hub, eyes, director, rec, voices))
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
