"""UDP/HTTP link to the toy-client firmware (firmware/toy-client)."""
from __future__ import annotations

import logging
import socket
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

import numpy as np

from . import config

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


class AtomHub:
    """Tracks Atoms, feeds mic frames to `on_audio(toy, pcm)`, plays speech back.

    Mics are globally muted while any toy talks (+ MIC_TAIL_S) so toys never
    hear each other as "the child".
    """

    def __init__(self, on_audio, on_button=None):
        self.on_audio = on_audio
        self.on_button = on_button or (lambda toy, kind: None)
        self.atoms: dict[str, Atom] = {}
        self.by_ip: dict[str, Atom] = {}
        self.mac_map = config.load_mac_map()
        self.mute_until = 0.0
        self.force_mute = False
        self.talking: str | None = None
        self._play_lock = threading.Lock()
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("0.0.0.0", config.BRAIN_PORT))

    def start(self):
        threading.Thread(target=self._rx, daemon=True, name="atoms-rx").start()

    # ---------- registry ----------
    def _toy_for_mac(self, mac: str) -> str:
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
                data, (ip, _) = self.sock.recvfrom(2048)
            except OSError:
                continue
            try:
                self._handle(data, ip)
            except Exception:  # noqa: BLE001 — one bad packet must never kill the ears
                log.exception("bad packet from %s: %r", ip, data[:40])

    def _handle(self, data: bytes, ip: str):
        if True:
            now = time.time()
            if data[:1] == b"M":
                a = self.by_ip.get(ip)
                if a is None or len(data) < 5:
                    return
                pcm = np.frombuffer(data[3:], "<i2")
                a.last_seen, a.pkts = now, a.pkts + 1
                a.rms = 0.8 * a.rms + 0.2 * float(np.sqrt(np.mean(pcm.astype(np.float32) ** 2)))
                if not self.muted():
                    self.on_audio(a.toy, pcm)
            elif data.startswith(b"HELLO"):
                parts = data.decode(errors="replace").split()
                mac = parts[1]
                flags = dict(p.split("=", 1) for p in parts[2:] if "=" in p)
                toy = self._toy_for_mac(mac)
                a = self.atoms.get(toy)
                if a is None or a.ip != ip:
                    log.info("Atom %s (%s) online at %s %s", toy, mac, ip, flags)
                    if a is not None:
                        self.by_ip.pop(a.ip, None)
                    a = Atom(mac=mac, ip=ip, toy=toy)
                    self.atoms[toy] = a
                    self.by_ip[ip] = a
                a.cam = flags.get("cam") == "1"
                a.last_seen = now
                self.sock.sendto(b"ACK", (ip, config.ATOM_PORT))
            elif data.startswith(b"BTN"):
                a = self.by_ip.get(ip)
                if a:
                    self.on_button(a.toy, data.decode().split()[-1])

    # ---------- HTTP ----------
    def capture(self, toy: str, timeout: float = 3.0) -> bytes | None:
        a = self.atoms.get(toy)
        if not a or not a.cam:
            return None
        try:
            return urllib.request.urlopen(f"http://{a.ip}/capture", timeout=timeout).read()
        except (urllib.error.URLError, OSError, TimeoutError):
            return None

    def play(self, toy: str, pcm: bytes) -> float:
        """Blocking: sends speech to `toy`, returns after it has finished playing."""
        a = self.atoms.get(toy)
        dur = len(pcm) / 2 / config.SAMPLE_RATE
        if not a or not pcm:
            log.warning("play: %s offline — line dropped", toy)
            return 0.0
        with self._play_lock:
            self.talking = toy
            self.mute_until = max(self.mute_until, time.time() + dur + 2.0)
            try:
                # The Atom replies only after the speaker has finished (firmware queues behind
                # any line already playing), so the reply time is the true end of speech.
                body, query = encode_for_atom(pcm)
                req = urllib.request.Request(f"http://{a.ip}/play?{query}", data=body, method="POST",
                                             headers={"Content-Type": "application/octet-stream"})
                t0 = time.time()
                urllib.request.urlopen(req, timeout=15 + dur).read()
                log.info("play %s: %.1fs audio (%d KB %s), done after %.1fs (%.1fs network/switch overhead)",
                         toy, dur, len(body) // 1024, query, time.time() - t0, time.time() - t0 - dur)
            except (urllib.error.URLError, OSError, TimeoutError) as e:
                log.warning("play to %s failed: %s", toy, e)
            finally:
                self.mute_until = time.time() + config.MIC_TAIL_S
                self.talking = None
        return dur
