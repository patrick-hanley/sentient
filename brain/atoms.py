"""UDP/HTTP link to the toy-client firmware (firmware/toy-client)."""
from __future__ import annotations

import logging
import socket
import threading
import time
import urllib.error
import urllib.request
import json
from dataclasses import dataclass, field

import numpy as np

from . import config
from .floor import FloorControl

log = logging.getLogger("atoms")


def ulaw_encode(pcm: np.ndarray) -> bytes:
    """int16 -> G.711 mu-law bytes (numpy; audioop is gone in Python 3.13)."""
    s = pcm.astype(np.int32)
    sign = (s < 0).astype(np.int32)
    mag = np.minimum(np.abs(s), 32635) + 0x84
    exp = np.clip(np.floor(np.log2(mag)).astype(np.int32) - 7, 0, 7)
    mant = (mag >> (exp + 3)) & 0x0F
    return (~((sign << 7) | (exp << 4) | mant) & 0xFF).astype(np.uint8).tobytes()


def encode_for_atom(pcm16k: bytes) -> tuple[bytes, str]:
    """16 kHz int16 speech -> (wire bytes, query string) per PLAY_CODEC / PLAY_RATE."""
    x = np.frombuffer(pcm16k, "<i2")
    rate = config.PLAY_RATE
    if rate != config.SAMPLE_RATE:
        n = int(len(x) * rate / config.SAMPLE_RATE)
        x = np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x.astype(np.float32)).astype(np.int16)
    if config.PLAY_CODEC == "ulaw":
        return ulaw_encode(x), f"fmt=ulaw&rate={rate}"
    return x.astype("<i2").tobytes(), f"fmt=pcm&rate={rate}"


@dataclass
class Atom:
    mac: str
    ip: str
    toy: str
    cam: bool = False
    last_seen: float = 0.0
    rms: float = 0.0
    pkts: int = 0
    lost: int = 0                               # mic packets missing by sequence number (UDP loss)
    last_seq: int = -1
    clock_off: float | None = None              # atom_clock - brain_monotonic, seconds (from SYNC/SYNCR, lowest RTT wins)
    sync_rtt: float = 9.9
    sync_sent: dict = field(default_factory=dict)
    hport: int = 0                              # test rigs only: HTTP port of a virtual Atom (real ones use 80)

    @property
    def base(self) -> str:
        return f"{self.ip}:{self.hport}" if self.hport else self.ip
    flags: dict = field(default_factory=dict)   # from HELLO: fw, codec repair counters (sfix/sfail/mfix/mfail), clips
    clips: dict = field(default_factory=dict)   # clip name -> seconds, stored in the Atom's flash (firmware 3+)
    fs: tuple = (0, 0)                          # (total, used) bytes of clip storage


class AtomHub:
    monitor = None   # brain.spectrum.Monitor, set by main
    """Tracks Atoms, feeds mic frames to `on_audio(toy, pcm)`, plays speech back.

    Mics are globally muted while any toy talks (+ MIC_TAIL_S) so toys never
    hear each other as "the child".
    """

    def __init__(self, on_audio, on_button=None):
        self.on_audio = on_audio
        self.on_button = on_button or (lambda toy, kind: None)
        self.on_playback = None   # Director sets this: called (toy, 'PLAYING'|'PLAYED', brain_monotonic_time)
        self.on_online = None   # main sets this: called (in a thread) when an Atom appears or moves IP
        self.atoms: dict[str, Atom] = {}
        self.by_ip: dict[str, Atom] = {}
        self.by_addr: dict[tuple, Atom] = {}   # (ip, udp port) of virtual Atoms that share one address
        self.mac_map = config.load_mac_map()
        self.mute_until = 0.0
        self.force_mute = False
        self.talking: str | None = None
        self._play_lock = threading.Lock()
        self.response_active = threading.Event()
        self._http = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("0.0.0.0", config.BRAIN_PORT))

    def sync_clocks(self, rounds=4):
        """Send SYNC pings; Atoms answer SYNCR with their clock (firmware 3.3+; older ones ignore it)."""
        for a in list(self.atoms.values()):
            for i in range(rounds):
                key = f"{int(time.monotonic() * 1000) % 100000}{i}"
                a.sync_sent[key.encode()] = time.monotonic()
                dest = (a.ip, self.udp_port_of(a)) if a.hport else (a.ip, config.ATOM_PORT)
                self.sock.sendto(b"SYNC " + key.encode(), dest)
                time.sleep(.02)
            if len(a.sync_sent) > 32:
                a.sync_sent.clear()

    def stop(self, toy: str) -> None:
        """Barge-in: cut the toy's playback at once (firmware 3.3+)."""
        a = self.atoms.get(toy)
        if a:
            self.sock.sendto(b"STOP", (a.ip, self.udp_port_of(a) if a.hport else config.ATOM_PORT))

    def udp_port_of(self, a: Atom) -> int:
        return next((addr[1] for addr, x in self.by_addr.items() if x is a), config.ATOM_PORT)

    @property
    def floor(self) -> FloorControl:
        if "_floor" not in self.__dict__:   # lazy: test doubles build AtomHub without __init__
            self._floor = FloorControl()
        return self._floor

    def start(self):
        threading.Thread(target=self._rx, daemon=True, name="atoms-rx").start()

    # ---------- registry ----------
    def _toy_for_mac(self, mac: str, forced: str | None = None) -> str:
        if forced in config.TOY_ORDER:   # virtual Atoms (tools/virtual_atoms.py) pick their toy; never persisted
            return forced
        if mac not in self.mac_map:
            used = set(self.mac_map.values())
            free = [t for t in config.TOY_ORDER if t not in used]
            self.mac_map[mac] = free[0] if free else f"extra{len(self.mac_map)}"
            config.save_mac_map(self.mac_map)
            log.warning("new Atom %s assigned to %s (edit %s to change)", mac, self.mac_map[mac], config.MAC_MAP_FILE)
        return self.mac_map[mac]

    def online(self) -> list[str]:
        now = time.time()
        return [t for t in config.TOY_ORDER if t in self.atoms and now - self.atoms[t].last_seen < 10]

    def muted(self) -> bool:
        return self.force_mute or time.time() < self.mute_until

    # ---------- receive ----------
    def _rx(self):
        while True:
            try:
                data, (ip, port) = self.sock.recvfrom(2048)
            except OSError:
                continue
            try:
                self._handle(data, ip, port)
            except Exception:  # noqa: BLE001 — one bad packet must never kill the ears
                log.exception("bad packet from %s: %r", ip, data[:40])

    def _handle(self, data: bytes, ip: str, port: int = 0):
        if True:
            now = time.time()
            if data[:1] == b"M":
                a = self.by_addr.get((ip, port)) or self.by_ip.get(ip)
                if a is None or len(data) < 5:
                    return
                pcm = np.frombuffer(data[3:], "<i2")
                a.last_seen, a.pkts = now, a.pkts + 1
                seq = data[1] | data[2] << 8
                if a.last_seq >= 0:
                    gap = (seq - a.last_seq - 1) & 0xFFFF
                    if 0 < gap <= 50:       # larger jumps are resyncs (reboot, /play upload), not loss
                        a.lost += gap
                a.last_seq = seq
                a.rms = 0.8 * a.rms + 0.2 * float(np.sqrt(np.mean(pcm.astype(np.float32) ** 2)))
                if self.monitor is not None:   # before the mute gate: we want to hear our own toys too
                    self.monitor.add(a.toy, pcm)
                if not self.muted():
                    self.on_audio(a.toy, pcm)
            elif data.startswith(b"HELLO"):
                parts = data.decode(errors="replace").split()
                mac = parts[1]
                flags = dict(p.split("=", 1) for p in parts[2:] if "=" in p)
                hport = int(flags.get("hport", 0))
                toy = self._toy_for_mac(mac, flags.get("toy") if hport else None)
                a = self.atoms.get(toy)
                if a is None or a.ip != ip or a.hport != hport:
                    log.info("Atom %s (%s) online at %s %s", toy, mac, ip, flags)
                    if a is not None:
                        self.by_ip.pop(a.ip, None)
                    a = Atom(mac=mac, ip=ip, toy=toy, hport=hport)
                    self.atoms[toy] = a
                    self.by_ip[ip] = a
                    if hport:
                        self.by_addr[(ip, port)] = a
                    if self.on_online:
                        threading.Thread(target=self.on_online, args=(toy,), daemon=True, name=f"online-{toy}").start()
                a.flags = flags
                a.cam = flags.get("cam") == "1"
                a.last_seen = now
                self.sock.sendto(b"ACK", (ip, port) if hport else (ip, config.ATOM_PORT))
            elif data[:5] == b"SYNCR":
                a = self.by_addr.get((ip, port)) or self.by_ip.get(ip)
                parts = data.split()
                if a and len(parts) == 3 and (sent := a.sync_sent.pop(parts[1], None)) is not None:
                    rtt = time.monotonic() - sent
                    if rtt < a.sync_rtt:   # NTP-style: the sample with the shortest round trip is the least skewed
                        a.sync_rtt, a.clock_off = rtt, int(parts[2]) / 1e6 - (sent + rtt / 2)
            elif data[:7] == b"PLAYING" or data[:6] == b"PLAYED":
                a = self.by_addr.get((ip, port)) or self.by_ip.get(ip)
                parts = data.split()
                if a and self.on_playback:
                    when = time.monotonic()                       # arrival time: the fallback without a clock offset
                    if a.clock_off is not None and len(parts) == 2:
                        when = int(parts[1]) / 1e6 - a.clock_off   # the Atom's own timestamp, in brain time
                    self.on_playback(a.toy, parts[0].decode(), when)
            elif data.startswith(b"BTN"):
                a = self.by_addr.get((ip, port)) or self.by_ip.get(ip)
                if a:
                    self.on_button(a.toy, data.decode().split()[-1])

    # ---------- HTTP ----------
    def capture(self, toy: str, timeout: float = 3.0) -> bytes | None:
        if config.PAUSE_CAPTURE_DURING_TURN and self.response_active.is_set():
            return None
        a = self.atoms.get(toy)
        if not a or not a.cam:
            return None
        try:
            with self._http.open(f"http://{a.base}/capture", timeout=timeout) as response:
                return response.read()
        except (urllib.error.URLError, OSError, TimeoutError):
            return None

    # ---------- clips stored on the Atom (firmware toy-client-3+) ----------
    def list_clips(self, toy: str) -> dict | None:
        """name -> seconds of audio on the Atom, or None if its firmware has no clip storage."""
        a = self.atoms.get(toy)
        if not a:
            return None
        try:
            with self._http.open(f"http://{a.base}/clips", timeout=5) as r:
                d = json.loads(r.read())
        except (urllib.error.URLError, OSError, TimeoutError, ValueError):
            return None
        if not d.get("fs"):
            return None
        # mu-law: 1 byte/sample. Empty files are leftovers of an interrupted upload: treat as missing.
        a.clips = {n: size / config.SAMPLE_RATE for n, size in d.get("clips", {}).items() if size > 0}
        a.fs = (int(d.get("total", 0)), int(d.get("used", 0)))
        return a.clips

    def set_volume(self, toy: str, vol: int) -> bool:
        """Hardware speaker volume 0..255 (0 = silent), saved on the Atom (firmware 3.2+)."""
        a = self.atoms.get(toy)
        if not a:
            return False
        vol = max(0, min(255, int(vol)))
        try:
            with self._http.open(urllib.request.Request(f"http://{a.base}/volume?v={vol}", data=b"", method="POST"),
                                 timeout=5) as r:
                r.read()
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            log.warning("volume on %s failed: %s", toy, e)
            return False
        a.flags["vol"] = str(vol)
        return True

    def clear_clips(self, toy: str) -> None:
        a = self.atoms.get(toy)
        if not a:
            return
        try:
            with self._http.open(urllib.request.Request(f"http://{a.base}/clipclear", data=b"", method="POST"), timeout=30) as r:
                r.read()
            a.clips = {}
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            log.warning("clip clear on %s failed: %s", toy, e)

    def put_clip(self, toy: str, name: str, pcm16k: bytes) -> bool:
        a = self.atoms.get(toy)
        if not a or not pcm16k:
            return False
        if a.flags.get("fw") == "toy-client-3":   # that build's web server overflows its stack on uploads
            log.warning("%s runs toy-client-3 (upload crash bug): reflash to 3.1+ before storing clips", toy)
            return False
        body = ulaw_encode(np.frombuffer(pcm16k, "<i2"))
        for attempt in range(3):   # flash erases can stall the Atom for a moment: be patient, retry
            req = urllib.request.Request(f"http://{a.base}/clip?name={name}", data=body, method="PUT",
                                         headers={"Content-Type": "application/octet-stream"})
            try:
                with self._http.open(req, timeout=30) as r:
                    r.read()
                a.clips[name] = len(body) / config.SAMPLE_RATE
                a.fs = (a.fs[0], a.fs[1] + (len(body) + 4095) // 4096 * 4096)   # LittleFS 4 KB blocks
                return True
            except (urllib.error.URLError, OSError, TimeoutError) as e:
                log.warning("clip upload to %s failed (try %d/3): %s", toy, attempt + 1, e)
                time.sleep(2)
        return False

    def play_line(self, toy: str, text: str, voices, **kw) -> float:
        """Fixed lines (fillers, canned scene): play from the Atom's own flash when stored there,
        otherwise synthesize and stream as usual."""
        a = self.atoms.get(toy)
        name = voices.clip_id(toy, text)
        if a and name in a.clips:
            dur = self._send(toy, f"http://{a.base}/playclip?name={name}", None, a.clips[name], "clip " + name, **kw)
            if dur is not None:
                return dur
            a.clips.pop(name, None)   # missing on the Atom after all: fall back
        return self.play(toy, voices.render(toy, text, persist=True), **kw)

    def _send(self, toy, url, body, dur, what, *, on_dispatch=None, raise_on_error=False):
        """POST to the Atom and wait: it replies only after its speaker has finished, so the
        reply time is the true end of speech. Returns seconds, or None if a clip was missing."""
        with self._play_lock:
            self.talking = toy
            self.floor.agent_start(toy)
            self.mute_until = max(self.mute_until, time.time() + dur + 2.0)
            try:
                req = urllib.request.Request(url, data=body or b"", method="POST",
                                             headers={"Content-Type": "application/octet-stream"})
                t0 = time.monotonic()
                if on_dispatch:
                    on_dispatch()
                with self._http.open(req, timeout=15 + dur) as response:
                    response.read()
                log.info("play %s: %.1fs audio (%s), done after %.1fs (%.1fs network/switch overhead)",
                         toy, dur, what, time.monotonic() - t0, time.monotonic() - t0 - dur)
            except urllib.error.HTTPError as e:
                if e.code == 404 and body is None:
                    return None
                log.warning("play to %s failed: %s", toy, e)
                if raise_on_error:
                    raise
            except (urllib.error.URLError, OSError, TimeoutError) as e:
                log.warning("play to %s failed: %s", toy, e)
                if raise_on_error:
                    raise
            finally:
                self.mute_until = time.time() + config.MIC_TAIL_S
                self.talking = None
                self.floor.agent_end(toy)
        return dur

    def play(self, toy: str, pcm: bytes, *, on_dispatch=None, raise_on_error=False) -> float:
        """Blocking: sends speech to `toy`, returns after it has finished playing."""
        a = self.atoms.get(toy)
        dur = len(pcm) / 2 / config.SAMPLE_RATE
        if not a or not pcm:
            log.warning("play: %s offline — line dropped", toy)
            if raise_on_error:
                raise RuntimeError(f"{toy} is offline or its audio is empty")
            return 0.0
        body, query = encode_for_atom(pcm)
        self._send(toy, f"http://{a.base}/play?{query}", body, dur, f"{len(body) // 1024} KB {query}",
                   on_dispatch=on_dispatch, raise_on_error=raise_on_error)
        return dur
