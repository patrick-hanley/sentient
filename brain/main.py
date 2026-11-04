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
import re
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import config
from .atoms import AtomHub
from .director import Director, system_prompt
from .llm import make_backend
from .perception import Perceiver, Recognizer
from .spectrum import Monitor
from . import parent as parent_mod, parent_web, scripted
from .tts import KITTEN_VOICES, Voices
from . import debugrec
from .vad import Segmenter
from . import canned

log = logging.getLogger("brain")

PAGE = (Path(__file__).with_name("dashboard.html")).read_text(encoding="utf-8")   # the operator dashboard on :8080


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
                return self._send(200, json.dumps({"kokoro": voices.kokoro_voices(), "piper": voices.piper_voices(), "kitten": KITTEN_VOICES,
                                                   "toys": {t: voices.settings(t) for t in config.TOY_ORDER}}),
                                  "application/json")
            if u.path == "/spectrum":   # band levels (dB re full scale) of each mic's last second: numbers only
                mon = hub.monitor
                return self._send(200, json.dumps({t: (mon.latest(t) if mon else {}) for t in config.TOY_ORDER}), "application/json")
            if u.path == "/tap.wav":   # last seconds of one mic, RAM only, and only with SENTIENT_DEBUG_RECORD=1
                q = dict(urllib.parse.parse_qsl(u.query))
                if not debugrec.enabled() or not hub.monitor or q.get("toy") not in config.TOYS:
                    return self._send(403, "audio tap is off (set SENTIENT_DEBUG_RECORD=1)")
                import io, wave
                buf = io.BytesIO()
                with wave.open(buf, "wb") as w:
                    w.setnchannels(1); w.setsampwidth(2); w.setframerate(config.SAMPLE_RATE)
                    w.writeframes(hub.monitor.tap(q["toy"], float(q.get("sec", 5))))
                return self._send(200, buf.getvalue(), "audio/wav")
            if u.path == "/latency":
                return self._send(200, json.dumps(director.turn_log.summary()), "application/json")
            if u.path == "/state":
                online = hub.online()
                st = {"backend": director.llm.name, "muted": hub.force_mute, "idle": director.idle_on,
                      "paused": director.paused, "talking": hub.talking, "heard": director.last_heard,
                      "said": [(w, voices.sounds.display(t)) for w, t in director.last_lines], "latency": director.last_latency,
                      "latency_breakdown": director.latency_state(), "latency_profile": config.LATENCY_PROFILE,
                      "device": getattr(director.llm, "device", "server-configured"), "toys": {}}
                for t in config.TOY_ORDER:
                    a = hub.atoms.get(t)
                    st["toys"][t] = {"online": t in online, "ip": a.ip if a else "", "cam": bool(a and a.cam),
                                     "level": director.segs[t].level, "view": eyes.views[t].describe(),
                                     "voice": voices.describe(t),
                                     "health": {k: a.flags.get(k) for k in ("fw", "sfix", "sfail", "mfix", "mfail", "vol", "imu")}
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
            elif u.path == "/preview" and q.get("toy") in config.TOYS:
                try:
                    pcm = voices.preview(q["toy"], q.get("engine", ""), q.get("voice", ""), q.get("speed", 1),
                                         q.get("pitch", 1), q.get("volume", 1), q.get("speaker"))
                except (ValueError, TypeError) as e:
                    return self._send(400, str(e))
                threading.Thread(target=hub.play, args=(q["toy"], pcm), daemon=True).start()
                muted = q["toy"] in hub.atoms and str(hub.atoms[q["toy"]].flags.get("vol", "200")) == "0"
                return self._send(200, "playing" + (" — but this toy's speaker volume is 0 (muted)" if muted else ""))
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
            elif u.path == "/imu" and q.get("toy") in config.TOYS and q.get("event") in scripted.IMU_EVENTS:
                # test without moving a toy: the toy plays its own clip, then the others react (rate limits skipped)
                threading.Thread(target=hub.play_local, args=(q["toy"], "imu_" + q["event"]), daemon=True).start()
                director.on_imu(q["toy"], q["event"], force=True)
            elif u.path == "/calibrate" and q.get("toy") in config.TOYS:
                return self._send(200 if hub.calibrate(q["toy"]) else 502, "stand the toy upright and still for 2 s")
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


def _fw_at_least(flags, major, minor):
    m = re.match(r"toy-client-(\d+)(?:\.(\d+))?", flags.get("fw", ""))
    return bool(m) and (int(m.group(1)), int(m.group(2) or 0)) >= (major, minor)


def sync_imu_clips(hub, voices, toy, have):
    """The toy's own motion sounds (snore, toss yell...) live in ITS flash as fixed names imu_<event>, so firmware 3.5 can play
    them with no brain and no network. Names are fixed (the firmware cannot know a hash), so which text/voice each one was
    rendered with is remembered in brain/data/imu_clips.json and a stale one is re-uploaded. They go in BEFORE the sound
    effects: if the flash is too full for them it is cleared once and refilled in priority order (the sounds that no longer
    fit simply stream from the Pi, as before). Returns the (possibly emptied) list of clips on the Atom."""
    path = config.DATA / "imu_clips.json"
    try:
        recorded = json.loads(path.read_text()).get(toy, {})
    except (OSError, ValueError):
        recorded = {}
    texts = {f"imu_{ev}": scripted.IMU_LOCAL[ev][toy] for ev in scripted.IMU_EVENTS}
    want = {n: voices.clip_id(toy, t) for n, t in texts.items()}
    missing = [n for n in texts if n not in have or recorded.get(n) != want[n]]
    if not missing:
        return have
    pcms = {n: voices.render(toy, texts[n], persist=True) for n in missing}
    total, used = hub.atoms[toy].fs
    need = sum(len(p) // 2 + 4096 for p in pcms.values())
    if total and total - used < need + 16384:
        log.info("%s: clearing the flash to make room for its %d motion sounds (%d KB)", toy, len(missing), need // 1024)
        hub.clear_clips(toy)
        have, recorded = {}, {}
        pcms = {n: voices.render(toy, t, persist=True) for n, t in texts.items()}
    for n, pcm in pcms.items():
        if pcm and hub.put_clip(toy, n, pcm):
            recorded[n] = want[n]
    try:
        allrec = json.loads(path.read_text()) if path.exists() else {}
    except (OSError, ValueError):
        allrec = {}
    allrec[toy] = recorded
    path.write_text(json.dumps(allrec))
    return hub.list_clips(toy) or have


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
        has_imu = _fw_at_least(hub.atoms[toy].flags, 3, 5)
        needed = {voices.clip_id(toy, x) for x in lines} | {"hello"}
        if has_imu:
            needed |= {f"imu_{ev}" for ev in scripted.IMU_EVENTS}
        if set(have) - needed:   # old voice/text versions: clear the flash and store a fresh set
            hub.clear_clips(toy)
            have = {}
        if has_imu:
            have = sync_imu_clips(hub, voices, toy, have)
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

    config.pin(config.TTS_CORES)   # onnxruntime's pool inherits the mask of the thread that creates the session
    voices = Voices()
    config.pin(config.LLM_CORES)   # threads created from here on (LiteRT, HTTP, director) use the LLM cores
    log.info("pre-rendering canned scene + fillers…")
    voices.prerender([(t, f) for t, fs in canned.FILLERS.items() for f in fs])
    # Kokoro is slower than real time on a Pi: render the canned scene in the background, only
    # when no live speech or turn needs the voice engine (and only once: it's cached on disk).
    threading.Thread(target=voices.prerender, args=([l for sc in canned.SCENES.values() for l in sc] + scripted.all_lines(),),
                     kwargs={"polite": True}, daemon=True, name="prerender").start()
    llm = make_backend(args.backend, system_prompt(), gpu=not args.cpu)

    if hasattr(llm, "warm"):   # prefill the persona prompt now so the first child's turn isn't ~10 s slower
        threading.Thread(target=llm.warm, daemon=True, name="llm-warm").start()
    segs = {}
    director = None
    hub = AtomHub(on_audio=lambda toy, pcm: segs[toy].feed(pcm) if toy in segs else None,
                  on_button=lambda toy, kind: director.on_button(toy, kind))
    hub.monitor = Monitor()
    rec = Recognizer()
    eyes = Perceiver(hub, rec)
    director = Director(hub, voices, eyes, llm, segs)
    hub.on_imu = director.on_imu
    for t in config.TOY_ORDER:
        segs[t] = Segmenter(t, director.utter_q)
    eyes.on_seen = director.on_seen
    eyes.hold = lambda: director.busy or director.paused
    voices.busy = lambda: director.busy
    hub.on_online = make_clip_sync(hub, voices, director)
    hub.resync = lambda toy: threading.Thread(target=hub.on_online, args=(toy,), daemon=True).start()
    if config.PARENT_PORT:   # Parent Board: its own port, PIN-protected, encrypted profiles (docs/parent-board.md)
        parent = parent_mod.Parent(activity=lambda: director.last_activity)
        director.parent = parent
        parent_web.serve(parent, director, config.PARENT_PORT)
        if not parent_mod.available():
            log.warning("Parent Board: the 'cryptography' package is missing, profiles cannot be stored (pip install cryptography)")
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
