#!/usr/bin/env python3
"""Virtual Atoms: speak the firmware protocol so the brain can be timed without hardware or a human.

Each virtual Atom sends HELLO + 20 ms mic frames over UDP (port 5005), and serves the HTTP endpoints the brain
calls (/play, /clips, /status, /volume). Playback is simulated in real time: /play answers only after the clip
has "played", like the real speaker.

  python tools/virtual_atoms.py scenarios/two_toys.json --selfhost          # whole rig on this machine, fake models
  python tools/virtual_atoms.py scenarios/two_toys.json --brain 192.168.2.5 # against the real brain on the Pi

--selfhost uses fake model/voice delays from the scenario's "model" block, so it tests the harness and scoring,
not Gemma. Against the Pi, point it at the real brain (virtual Atoms pick their toy with the test-only `toy=` flag,
and nothing is saved to the brain's toy map).

A scenario with a "room" block (scenarios/stop_while_talking.json) streams every mic all the time with capture times, and
each mic hears the child and the other toys' speakers: that exercises the clock sync, the echo canceller and the barge-in
cut. A turn with "expect": "stop" is scored by score_run.py (was the talking toy cut, how fast, did the toys stay quiet).
Story mode (tools/scenarios/story_read_aloud.json): the child reads aloud; "expect" is "sound:<name>" (that sound and no
words), "quiet" (nothing at all), "story_start" / "ask" / "end" / "talk" (a spoken line). score_run.py reports them under "story".

Output: a JSONL event log (default runs/<scenario>-<time>.jsonl). Audio stays in RAM; clips are synthesised or read
from the scenario, and nothing the brain plays is written to disk. Score it with tools/score_run.py.
"""
from __future__ import annotations

import argparse
import collections
import json
import logging
import os
import random
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SR, FRAME = 16000, 320


def ulaw_decode(b: bytes) -> np.ndarray:
    u = ~np.frombuffer(b, np.uint8) & 0xFF
    sign, exp, mant = u & 0x80, (u >> 4) & 7, u & 0x0F
    mag = (((mant.astype(np.int32) << 3) + 0x84) << exp) - 0x84
    return np.where(sign != 0, -mag, mag).astype(np.int16)


def resample(x: np.ndarray, src: int, dst: int) -> np.ndarray:
    if src == dst or not len(x):
        return x
    n = int(len(x) * dst / src)
    return np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x.astype(np.float32)).astype(np.int16)


class Events:
    def __init__(self, path):
        self.t0, self.lock, self.items = time.monotonic(), threading.Lock(), []
        self.path = path
        self.audio = None

    def add(self, **kw):
        kw["t"] = round(time.monotonic() - self.t0, 4)
        with self.lock:
            self.items.append(kw)

    def save(self):
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.lock, open(self.path, "w") as f:
            for e in sorted(self.items, key=lambda e: e["t"]):
                f.write(json.dumps(e) + "\n")


class VirtualAtom:
    def __init__(self, toy, brain, events, speed=1.0, on_reply=None, room=None, skew=1000.0):
        self.toy, self.brain, self.ev, self.speed, self.on_reply = toy, brain, events, speed, on_reply
        self.mac = "VA:%s" % toy[:4].upper()
        self.playing = False
        self.clock_skew = skew     # the Atom's clock is not the brain's: SYNC must recover this offset
        # room model (scenario "room"): the mic streams all the time (with the capture time, like firmware 3.7+) and hears
        # the child, the child at the other toys (gain "cross") and the other toys' speakers ("leak", after "delay_ms")
        self.room, self.peers, self.sources, self.src_lock = room, {}, [], threading.Lock()
        self.halt = threading.Event()
        self.seq = 0
        self.stop = threading.Event()
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("0.0.0.0", 0))
        atom = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def _ok(self, body=b"OK", code=200, ctype="text/plain"):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.path.startswith("/clips"):
                    return self._ok(b'{"fs":0}', ctype="application/json")
                if self.path.startswith("/status"):
                    return self._ok(json.dumps({"rssi": -55, "playing": int(atom.playing)}).encode(), ctype="application/json")
                self._ok(b"", 404)

            def do_PUT(self):
                self.rfile.read(int(self.headers.get("Content-Length", 0)))
                self._ok()

            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                u = urllib.parse.urlparse(self.path)
                q = urllib.parse.parse_qs(u.query)
                if u.path == "/play":
                    return self._ok(atom.play(body, q))
                if u.path == "/playclip":
                    return self._ok(b"", 404)
                self._ok()

        self.http = ThreadingHTTPServer(("0.0.0.0", 0), H)
        self.hport = self.http.server_address[1]

    def start(self):
        threading.Thread(target=self.http.serve_forever, daemon=True).start()
        threading.Thread(target=self._hello, daemon=True).start()
        threading.Thread(target=self._drain, daemon=True).start()
        if self.room is not None:
            threading.Thread(target=self._mic, daemon=True).start()

    def hear(self, pcm, gain, at):
        """Room model: `pcm` (16 kHz) reaches this mic from time `at`. Returns the source (set src["end"] to cut it short)."""
        src = {"t0": at, "pcm": pcm.astype(np.float32) * gain, "end": len(pcm)}
        with self.src_lock:
            self.sources.append(src)
        return src

    def _mic(self):
        rng = np.random.default_rng(abs(hash(self.toy)) % 2**32)
        t0, i, noise = time.monotonic(), 0, float(self.room.get("noise", 15))
        while not self.stop.is_set():
            due = t0 + i * .02
            wait = due - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            i += 1
            acc = rng.normal(0, noise, FRAME).astype(np.float32)
            with self.src_lock:
                for src in list(self.sources):
                    k = int(round((due - src["t0"]) * SR))
                    if k >= src["end"]:
                        self.sources.remove(src)
                    elif k + FRAME > 0:
                        a, b = max(k, 0), min(k + FRAME, src["end"])
                        acc[a - k:b - k] += src["pcm"][a:b]
            if self.playing:      # the firmware gates its own mic while its speaker plays
                continue
            frame = np.clip(acc, -32768, 32767).astype("<i2").tobytes()
            cap = int(self._clock(due) * 1e6).to_bytes(8, "little", signed=True)
            self.sock.sendto(b"M" + (self.seq & 0xFFFF).to_bytes(2, "little") + frame + cap, self.brain)
            self.seq += 1

    def _hello(self):
        msg = f"HELLO {self.mac} cam=0 mic=1 spk=1 fw=virtual toy={self.toy} hport={self.hport}".encode()
        while not self.stop.is_set():
            self.sock.sendto(msg, self.brain)
            self.stop.wait(1.0)

    def _clock(self, t):     # the Atom's own clock at brain time t: an offset, and a crystal that runs "drift_ppm" fast
        return t * (1 + (self.room or {}).get("drift_ppm", 0) * 1e-6) + self.clock_skew

    def _us(self):
        return int(self._clock(time.monotonic()) * 1e6)

    def _drain(self):
        while not self.stop.is_set():
            try:
                data, addr = self.sock.recvfrom(64)
            except OSError:
                return
            if data.startswith(b"SYNC "):
                self.sock.sendto(b"SYNCR %s %d" % (data[5:], self._us()), addr)
            elif data.startswith(b"STOP"):
                self.halt.set()

    def wait_online(self, timeout=10):
        time.sleep(1.5)   # HELLO -> ACK -> brain registers us

    def play(self, body, q) -> bytes:
        fmt, rate = q.get("fmt", ["pcm"])[0], int(q.get("rate", [SR])[0])
        pcm = ulaw_decode(body) if fmt == "ulaw" else np.frombuffer(body, "<i2")
        dur = len(pcm) / rate
        self.playing = True
        started = time.monotonic() - self.ev.t0
        self.ev.add(ev="play_start", toy=self.toy, dur=round(dur, 3), bytes=len(body))
        self.halt.clear()
        self.sock.sendto(b"PLAYING %d" % self._us(), self.brain)
        t_play, leaks = time.monotonic(), []
        if self.room is not None and self.room.get("leak", 0):
            heard = resample(pcm, rate, SR)
            leaks = [p.hear(heard, self.room["leak"], t_play + self.room.get("delay_ms", 30) / 1000)
                     for p in self.peers.values() if p is not self]
        cut = self.halt.wait(dur / self.speed)        # True: the brain sent STOP (barge-in, "stop")
        played = time.monotonic() - t_play
        for src in leaks:
            src["end"] = min(src["end"], int(played * SR))
        self.playing = False
        self.sock.sendto(b"PLAYED %d" % self._us(), self.brain)
        self.ev.add(ev="play_end", toy=self.toy, dur=round(dur, 3), cut=bool(cut), played=round(played, 3))
        if self.ev.audio is not None:   # --transcribe: RAM only, never written to disk
            self.ev.audio.append((self.toy, round(started, 4), resample(pcm, rate, SR)))
        if self.on_reply:
            self.on_reply(self.toy, resample(pcm, rate, SR), dur)
        return b"OK %d" % int(dur * 1000)

    def say(self, pcm: np.ndarray, label: str, **tags):
        """Send `pcm` as mic frames in real time. Suppressed while playing, like the firmware's rx_busy."""
        n = len(pcm) // FRAME
        self.ev.add(ev="speech_start", toy=self.toy, label=label, dur=round(n * .02, 3), **tags)
        if self.room is not None:      # the mic thread does the sending; the child is heard at every toy
            if label != "silence":
                at = time.monotonic() + .02
                for p in self.peers.values():
                    p.hear(pcm, 1.0 if p is self else self.room.get("cross", 0.3), at)
            time.sleep(n * .02)
            self.ev.add(ev="speech_end", toy=self.toy, label=label, frames=n)
            return
        t0 = time.monotonic()
        sent = 0
        for i in range(n):
            wait = t0 + i * .02 / self.speed - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            if self.playing:
                continue
            frame = pcm[i * FRAME:(i + 1) * FRAME]
            self.sock.sendto(b"M" + (self.seq & 0xFFFF).to_bytes(2, "little") + frame.astype("<i2").tobytes(), self.brain)
            self.seq += 1
            sent += 1
        self.ev.add(ev="speech_end", toy=self.toy, label=label, frames=sent)

    def silence(self, seconds):
        self.say(np.zeros(int(seconds * SR) // FRAME * FRAME, np.int16), "silence")


def synth(text: str) -> np.ndarray:
    """Speech for a scenario line: macOS `say`, else Piper through the brain's own Voices, else a buzz."""
    if sys.platform == "darwin":
        with tempfile.TemporaryDirectory() as d:
            aiff, wav = os.path.join(d, "a.aiff"), os.path.join(d, "a.wav")
            subprocess.run(["say", "-o", aiff, text], check=True)
            subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@16000", "-c", "1", aiff, wav], check=True)
            return load_wav(wav)
    try:
        from brain.tts import Voices
        return np.frombuffer(Voices().render("sage", text), "<i2")
    except Exception:   # noqa: BLE001
        t = np.arange(int(len(text) * .07 * SR)) / SR
        return (6000 * np.sin(2 * np.pi * 140 * t) * (0.6 + 0.4 * np.sin(2 * np.pi * 3 * t))).astype(np.int16)


def load_wav(path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        x = np.frombuffer(w.readframes(w.getnframes()), "<i2")
        if w.getnchannels() > 1:
            x = x[:: w.getnchannels()]
        return resample(x, w.getframerate(), SR)


def transcribe(ev, path, humans, clips):
    """Text-only transcript (who said what, when) for tools/judge.py. Local faster-whisper; audio stays in RAM."""
    from faster_whisper import WhisperModel
    from brain import config
    model = WhisperModel(str(config.OFFLINE / "faster-whisper-base.en"), device="cpu", compute_type="int8")

    def text(pcm):
        segs, _ = model.transcribe(pcm.astype(np.float32) / 32768, language="en")
        return " ".join(s.text.strip() for s in segs).strip()
    rows = [{"t": t, "who": "human", "toy_mic": toy, "text": label.partition(":")[2]} for toy, label, t in humans]
    # a toy plays a filler then its reply as separate clips: merge consecutive clips of one toy within 1.5 s
    for toy, t, pcm in sorted(ev.audio, key=lambda a: a[1]):
        rows.append({"t": t, "who": toy, "dur": round(len(pcm) / SR, 2), "text": text(pcm)})
    rows.sort(key=lambda r: r["t"])
    Path(path).write_text(json.dumps(rows, indent=1))


def clip_for(spec: str, base: Path) -> np.ndarray:
    kind, _, arg = spec.partition(":")
    if kind == "say":
        return synth(arg)
    if kind == "file":
        return load_wav(base / arg)
    raise SystemExit(f"unknown clip spec {spec!r} (use say:<text> or file:<wav>)")


# ---------------- self-hosted brain with fake models ----------------
class FakeLLM:
    """Streams a labelled reply after delays shaped like Gemma on the Pi (prefill grows with audio length)."""
    name, hears_audio = "fake", True

    def __init__(self, cfg, rng):
        self.cfg, self.rng = cfg, rng
        self.heard = collections.deque()   # the scenario's words, in order: the fake "hears" them (stop / names are found in code)

    def stream(self, prompt, wav=None, image=None):
        import re
        from brain.director import NAMES
        c = self.cfg
        n = 0
        if wav:
            with wave.open(wav, "rb") as w:
                n = w.getnframes() / w.getframerate()
        time.sleep(c.get("prefill_base_s", .4) + c.get("prefill_per_audio_s", .5) * n)
        time.sleep(c.get("first_token_s", .3))
        m = re.search(r"\[HEARD BY\] (\w+)", prompt)
        online = re.search(r"\[TOYS HERE\] ([^(]+)\(", prompt).group(1).split(", ")
        who = (m.group(1) if m else online[0]).strip().upper()
        said = "something"
        if wav and self.heard:        # the newest words spoken: an utterance the brain missed must not shift the later ones
            said = self.heard[-1]
            self.heard.clear()
        yield f"HEARD: {said}\n"
        lines = int(c.get("lines", 1))
        order = [who] + [x.strip().upper() for x in online if x.strip().upper() != who]
        for i in range(min(lines, len(order))):
            time.sleep(c.get("line_gap_s", .6) if i else 0)
            yield f"{order[i]}: " + c.get("text", "That is a great question. Let us think about it together.") + "\n"
        del NAMES


class FakeVoices:
    def __init__(self, cfg):
        self.cfg, self.sounds = cfg, None

    def render(self, toy, text, persist=False):
        dur = max(.6, len(text) * .06)
        if text.startswith("{") and text.endswith("}"):   # a lone sound effect (story mode): a recording, no synthesis
            dur = self.cfg.get("sfx_s", 2.0)
        else:
            time.sleep(dur * self.cfg.get("tts_rtf", .9))
        t = np.arange(int(dur * SR)) / SR
        if self.cfg.get("voice") == "noise":   # speech-like wide-band sound: an echo canceller cannot lock onto a pure tone
            x = np.random.default_rng(len(text)).normal(0, 1, len(t))
            x = np.convolve(x, np.ones(4) / 4, "same") * (0.55 + 0.45 * np.sin(2 * np.pi * 4 * t))
            return (3000 * x / x.std()).astype(np.int16).tobytes()
        return (3000 * np.sin(2 * np.pi * 200 * t)).astype(np.int16).tobytes()

    def clip_id(self, toy, text):
        return "c" + str(abs(hash((toy, text))))[:12]


def selfhost(cfg, toys):
    from brain import config
    from brain.atoms import AtomHub
    from brain.director import Director
    from brain.vad import Segmenter
    import types
    config.apply_latency_profile(cfg.get("profile", "responsive"))
    for k, v in {**(cfg.get("config") or {}), **cfg.get("_set", {})}.items():   # A/B knobs, e.g. END_SILENCE_MS=700
        setattr(config, k, v)
    segs = {}
    hub = AtomHub(on_audio=lambda toy, pcm: segs[toy].feed(pcm) if toy in segs else None)
    eyes = types.SimpleNamespace(views={}, scene_text=lambda: "Nothing special.")
    llm = FakeLLM(cfg.get("model", {}), random.Random(cfg.get("seed", 1)))
    director = Director(hub, FakeVoices(cfg.get("model", {})), eyes, llm, segs)
    for t in config.TOY_ORDER:
        segs[t] = Segmenter(t, director.utter_q)
    hub.on_barge = director.barge_in      # as brain/main.py wires it: the child talks over a toy -> cut it
    hub.start()
    director.start()
    return hub, director


def run(args):
    sc = json.loads(Path(args.scenario).read_text())
    sc["_set"] = {k: json.loads(v) for k, _, v in (x.partition("=") for x in args.set)}
    base = Path(args.scenario).parent
    rng = random.Random(sc.get("seed", 1))
    toys = sc.get("toys", ["dyno", "sage"])
    out = args.out or ROOT / "runs" / f"{Path(args.scenario).stem}-{time.strftime('%H%M%S')}.jsonl"
    ev = Events(out)
    if args.transcribe:
        ev.audio = []
    director = None
    if args.selfhost:
        _, director = selfhost(sc, toys)
        brain = ("127.0.0.1", 5005)
    else:
        brain = (args.brain, 5005)
    chain = sc.get("chain", {})
    atoms: dict[str, VirtualAtom] = {}
    hops = {"n": 0}

    def on_reply(toy, pcm, dur):
        """Tier A agent-to-agent: what one toy said becomes the next toy's mic input (no air gap)."""
        if not chain or dur < chain.get("min_dur_s", 1.5) or hops["n"] >= chain.get("max_hops", 4):
            return
        others = [t for t in toys if t != toy]
        target = others[hops["n"] % len(others)]
        hops["n"] += 1

        def go():
            time.sleep(chain.get("delay_s", .5) + 0.5)   # clear the brain's mic tail
            ev.add(ev="chain", src=toy, dst=target)
            atoms[target].say(pcm, f"chain from {toy}")
            atoms[target].silence(1.2)
        threading.Thread(target=go, daemon=True).start()

    room = sc.get("room")
    for i, t in enumerate(toys):
        atoms[t] = VirtualAtom(t, brain, ev, speed=args.speed, on_reply=on_reply, room=room, skew=1000.0 + 777.7 * i)
        atoms[t].peers = atoms
    for a in atoms.values():
        a.start()
    time.sleep(2.0)
    if director is not None:
        class BargeLog(logging.Handler):       # how the brain noticed the child over a toy
            def emit(self, r):
                m = r.getMessage()
                if m.startswith("barge-in: "):
                    ev.add(ev="barge", mode="echo canceller" if "echo canceller" in m else "loudness")
        logging.getLogger("atoms").addHandler(BargeLog())

        class StoryLog(logging.Handler):       # story mode: which sound the brain chose, and when the mode turned on/off
            def emit(self, r):
                m = r.getMessage()
                if m.startswith("story sound: "):
                    for i, part in enumerate(m[13:].split(", ")):     # several: they play one after another
                        name, _, toy = part.partition(" on ")
                        ev.add(ev="story_sound", sound=name, toy=toy, nth=i)
                elif m.startswith("story mode "):
                    ev.add(ev="story_mode", on=m.startswith("story mode on"))
        logging.getLogger("director").addHandler(StoryLog())
        logging.getLogger("director").setLevel(logging.INFO)
        logging.getLogger("atoms").setLevel(logging.INFO)
        if room is not None:
            director.hub.sync_clocks()
            time.sleep(.3)
    clips = {}
    threads = []
    for turn in sc["turns"]:
        spec = turn["clip"]
        clips.setdefault(spec, clip_for(spec, base))
    ev.t0 = time.monotonic()
    ev.add(ev="rig_up", toys=toys, mode="selfhost" if args.selfhost else "brain")

    def fire(turn):
        time.sleep(max(0, turn["at"] / args.speed - (time.monotonic() - ev.t0)))
        a = atoms[turn["toy"]]
        if director is not None and hasattr(director.llm, "heard"):
            director.llm.heard.append(turn.get("text") or turn["clip"].partition(":")[2])
        a.say(clips[turn["clip"]], turn["clip"], **({"expect": turn["expect"]} if turn.get("expect") else {}))
        a.silence(turn.get("tail_s", 1.2))   # the brain needs silence to close the utterance
    for turn in sc["turns"]:
        th = threading.Thread(target=fire, args=(turn,))
        th.start()
        threads.append(th)
    for th in threads:
        th.join()
    time.sleep(sc.get("settle_s", 12) / args.speed)
    if director is not None and room is not None:   # did SYNC recover each Atom's clock? (the echo canceller places audio with it)
        for t, a in atoms.items():
            h, now = director.hub.atoms.get(t), time.monotonic()
            ok = h is not None and h.clock_off is not None
            ev.add(ev="clock_sync", toy=t, err_ms=round((h.off(now) - (a._clock(now) - now)) * 1000, 2) if ok else None)
    ev.save()
    if args.transcribe:
        transcribe(ev, str(out) + ".transcript.json", [(t["toy"], t["label"], t["t"]) for t in ev.items
                                                      if t["ev"] == "speech_start" and t["label"] != "silence"
                                                      and not t["label"].startswith("chain")], clips)
    if director is not None:
        Path(str(out) + ".turns.json").write_text(json.dumps(director.turn_log.summary()))
    print(f"events: {out}")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("scenario")
    ap.add_argument("--selfhost", action="store_true", help="run an in-process brain with fake model/voices")
    ap.add_argument("--brain", default="127.0.0.1", help="brain host (when not --selfhost)")
    ap.add_argument("--speed", type=float, default=1.0, help="time compression; keep 1.0 for latency numbers")
    ap.add_argument("--out")
    ap.add_argument("--set", action="append", default=[], metavar="KEY=JSON",
                    help="override a brain config value in --selfhost, e.g. --set END_SILENCE_MS=700 --set PLAY_FILLERS=false")
    ap.add_argument("--log", action="store_true", help="print the brain's own log (--selfhost)")
    ap.add_argument("--transcribe", action="store_true",
                    help="after the run, transcribe what each toy said (RAM only) into <out>.transcript.json")
    a = ap.parse_args()
    if a.log:
        logging.basicConfig(level=logging.INFO, format="%(relativeCreated)7d %(name)s %(message)s")
    run(a)
    os._exit(0)
