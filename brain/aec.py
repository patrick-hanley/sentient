"""Cross-toy acoustic echo cancellation: the other toys listen to the child while one toy talks.

A toy cannot hear while its own speaker plays (shared codec), but the other toys' mics keep streaming 20 ms frames, and
those mics hear the talking toy through the room. The brain knows exactly what it sent to the talker, so it can subtract
that sound from each listener's stream and keep only what is left: the child, plus a little noise. Docs: docs/aec.md.

Per (talker -> listener) pair:
  * reference  the PCM the brain sent (decoded back from the wire codec), placed on the listener's own sample timeline.
               Listener frames carry only a 16-bit sequence number (frame n = seq * 320 samples), so the brain-side
               arrival time minus n/16000 (lower envelope = the least delayed packets) maps that timeline onto brain time
               and the talker's 'PLAYING <us>' timestamp (atoms.py turns it into brain time) puts the clip on it.
  * lag        what is left (codec/DMA latency, the capture frame, a clock-offset error of some ms) is found once per clip
               with GCC-PHAT over the first ~0.5 s, or reused from the last clip of the pair (warm start) and verified.
  * filter     partitioned-block frequency-domain NLMS (multi-delay filter, 8 x 20 ms = 160 ms of echo), run on the
               listener's frames, trained retrospectively over the search window so it converges at once.
  * double talk  the residual is compared with the echo the filter predicts times the residual-to-echo ratio measured
               while no child was talking, plus the ambient noise floor. A much louder residual freezes adaptation, and
               a run of it that webrtcvad hears as speech is a barge-in. Before triggering, the residual is checked
               for correlation with the reference (an echo path that changed leaves a residual that still looks like the
               toy; a child does not): that case resets the pair instead of cutting the toy.
  * drift      the filter's main tap is watched; a persistent shift re-centres filter and alignment.

Everything is RAM only (a couple of seconds of frames per listener, the clip being played). Nothing is logged but counts.
"""
from __future__ import annotations

import collections
import logging
import threading
from dataclasses import dataclass, field

import numpy as np
import webrtcvad

from . import config

log = logging.getLogger("aec")

FS = 16000
B = 320                    # one mic packet = 20 ms = one filter block
NB = B + 1                 # rfft bins of a 2B overlap-save block
PRE = 160                  # filter taps kept before the expected main peak (10 ms): alignment slack
PASSES = 6                 # retrospective adaptation passes over the first heard part of a clip


def ulaw_decode(b: bytes) -> np.ndarray:
    u = ~np.frombuffer(b, np.uint8) & 0xFF
    sign, exp, mant = u & 0x80, (u >> 4) & 7, u & 0x0F
    mag = (((mant.astype(np.int32) << 3) + 0x84) << exp) - 0x84
    return np.where(sign != 0, -mag, mag).astype(np.int16)


def wire_to_ref(body: bytes, fmt: str = "ulaw", rate: int = FS) -> np.ndarray:
    """What the toy's speaker was fed, as float32 at 16 kHz (undo the codec and the optional 8 kHz transport)."""
    x = (ulaw_decode(body) if fmt == "ulaw" else np.frombuffer(body, "<i2")).astype(np.float32)
    if rate != FS and len(x):
        x = np.interp(np.linspace(0, len(x) - 1, int(len(x) * FS / rate)), np.arange(len(x)), x).astype(np.float32)
    return x


def rms(x) -> float:
    x = np.asarray(x, np.float32)
    return float(np.sqrt(np.mean(x * x))) if len(x) else 0.0


def _cubic(x: np.ndarray, p: np.ndarray) -> np.ndarray:
    """x sampled at float positions p (Catmull-Rom cubic; zero outside the clip)."""
    i = np.floor(p).astype(np.int64)
    f = (p - i).astype(np.float32)
    xp = np.concatenate([np.zeros(2, np.float32), x, np.zeros(3, np.float32)])
    j = np.clip(i + 2, 1, len(xp) - 3)
    inside = (i >= -1) & (i < len(x))
    a, b, c, d = xp[j - 1], xp[j], xp[j + 1], xp[j + 2]
    y = b + 0.5 * f * (c - a + f * (2 * a - 5 * b + 4 * c - d + f * (3 * (b - c) + d - a)))
    return np.where(inside, y, 0.0).astype(np.float32)


# ---------------------------------------------------------------------------------------------------------------------
# GCC-PHAT
# ---------------------------------------------------------------------------------------------------------------------
def gcc_phat(m: np.ndarray, r: np.ndarray, lo: int, hi: int, band=(250.0, 3800.0), beta: float = 0.85):
    """Delay of r inside m: m[n] ~ g * r[n - D]. Returns (D, peak, score) with D searched in [lo, hi] samples.
    peak = PHAT cross-correlation height (1.0 for a clean delayed copy), score = peak / RMS of the rest of the search range."""
    n = len(m)
    nf = 1 << int(np.ceil(np.log2(2 * n)))
    M, R = np.fft.rfft(m, nf), np.fft.rfft(r, nf)
    cs = M * np.conj(R)
    f = np.fft.rfftfreq(nf, 1.0 / FS)
    w = ((f >= band[0]) & (f <= band[1])).astype(np.float64)
    cs = cs * w / np.maximum(np.abs(cs), 1e-9 * np.max(np.abs(cs)) + 1e-12) ** beta
    cc = np.fft.irfft(cs, nf) * nf / max(2 * np.abs(cs).sum(), 1e-12)   # <= 1; 1.0 = every bin in phase (a clean delayed copy)
    lags = np.arange(lo, hi + 1)
    seg = cc[lags % nf]
    k = int(np.argmax(np.abs(seg)))
    peak = float(abs(seg[k]))
    rest = np.delete(seg, slice(max(0, k - 24), k + 25))
    score = peak / (float(np.sqrt(np.mean(rest ** 2))) + 1e-12) if len(rest) else 0.0
    return int(lags[k]), peak, score


# ---------------------------------------------------------------------------------------------------------------------
# Partitioned-block frequency-domain NLMS
# ---------------------------------------------------------------------------------------------------------------------
class MDF:
    """Multi-delay (partitioned block) frequency-domain adaptive filter, overlap-save, 2B FFT, per-bin power-normalised step."""

    def __init__(self, parts: int = 8, mu: float = 0.5):
        self.P, self.mu = parts, mu
        self.W = np.zeros((parts, NB), np.complex128)
        self.reset_history()
        self.pw = np.zeros(NB)

    def reset_history(self):
        self.X = np.zeros((self.P, NB), np.complex128)
        self.xb = np.zeros(2 * B)

    def reset(self):
        self.W[:] = 0
        self.pw[:] = 0
        self.reset_history()

    def push(self, x: np.ndarray):
        self.xb[:B] = self.xb[B:]
        self.xb[B:] = x
        self.X[1:] = self.X[:-1]
        self.X[0] = np.fft.rfft(self.xb)

    def predict(self) -> np.ndarray:
        return np.fft.irfft((self.W * self.X).sum(0))[B:]

    def adapt(self, e: np.ndarray, scale: float = 1.0):
        E = np.fft.rfft(np.concatenate([np.zeros(B), e]))
        pn = (self.X.real ** 2 + self.X.imag ** 2).sum(0)
        self.pw = pn if not self.pw.any() else 0.8 * self.pw + 0.2 * pn
        step = self.mu * scale / (self.pw + 0.01 * self.pw.mean() + 1e3)
        G = np.conj(self.X) * (E * step)
        g = np.fft.irfft(G, axis=1)
        g[:, B:] = 0.0
        self.W += np.fft.rfft(g, axis=1)

    def step(self, x: np.ndarray, d: np.ndarray, scale: float = 1.0):
        self.push(x)
        y = self.predict()
        e = d - y
        if scale > 0:
            self.adapt(e, scale)
        return e, y

    # -- time-domain view, for drift tracking and warm starts
    def taps(self) -> np.ndarray:
        return np.fft.irfft(self.W, axis=1)[:, :B].reshape(-1)

    def set_taps(self, w: np.ndarray):
        g = np.zeros((self.P, 2 * B))
        g[:, :B] = w.reshape(self.P, B)
        self.W = np.fft.rfft(g, axis=1)

    def shift_taps(self, k: int):
        """Delay the filter by k samples (negative = advance), zero filled."""
        w = self.taps()
        out = np.zeros_like(w)
        if k >= 0:
            out[k:] = w[:len(w) - k]
        else:
            out[:k] = w[-k:]
        self.set_taps(out)

    def peak_pos(self) -> float:
        """Fractional position of the main echo tap (centroid of the energy around the strongest tap)."""
        w = self.taps()
        k = int(np.argmax(np.convolve(w * w, np.ones(9), "same")))
        lo, hi = max(0, k - 12), min(len(w), k + 13)
        e = w[lo:hi] ** 2
        return float(np.sum(np.arange(lo, hi) * e) / max(np.sum(e), 1e-12))


# ---------------------------------------------------------------------------------------------------------------------
# One talker clip on the wire
# ---------------------------------------------------------------------------------------------------------------------
@dataclass
class Clip:
    pcm: np.ndarray                 # float32, 16 kHz: what the speaker was fed
    dispatch: float                 # brain monotonic time the upload started
    t0: float | None = None         # brain time of the first sample out ('PLAYING' in the toy's clock, converted); None until it arrives
    cut: int | None = None          # sample index where the speaker stopped (STOP or PLAYED), or None
    ended: bool = False

    @property
    def n(self) -> int:
        return len(self.pcm) if self.cut is None else max(0, min(len(self.pcm), self.cut))


@dataclass
class Out:
    pcm: np.ndarray                          # int16 frame to hand on (the residual while a pair is cancelling, else the raw frame)
    cancelling: bool = False                 # the residual is trustworthy (locked pair)
    talker: str | None = None
    barge: list | None = None                # residual frames from the child's true start, when a barge-in just triggered


# ---------------------------------------------------------------------------------------------------------------------
# Listener timeline (seq -> samples, arrival -> brain time) and noise floor
# ---------------------------------------------------------------------------------------------------------------------
class Listener:
    def __init__(self, toy: str):
        self.toy = toy
        self.last_seq: int | None = None
        self.n = 0                                       # unwrapped frame counter
        self.off = collections.deque(maxlen=400)         # arrival - n*0.02 over the last 8 s
        self.c: float | None = None                      # brain time of sample 0 of this timeline (lower envelope)
        self.ring: collections.deque = collections.deque(maxlen=200)   # (n_samples, int16 frame), ~4 s
        self.noise2 = 150.0 ** 2                         # ambient power per sample while no known toy plays
        self.pairs: dict[str, "Pair"] = {}

    def frame(self, seq: int, arrival: float, pcm: np.ndarray):
        """Returns (n_start_sample, missing_frames) for this frame; resets the timeline on a resync."""
        missing = 0
        if self.last_seq is None:
            self.n = 0
        else:
            gap = (seq - self.last_seq) & 0xFFFF
            if gap == 0 or gap > 0x8000:                 # duplicate or reordered (a late packet): ignore
                return None, 0
            if gap > 50:                                 # resync (reboot, /play upload): start over
                self.n, self.off, self.c = 0, collections.deque(maxlen=400), None
                self.ring.clear()
                for p in self.pairs.values():
                    p.relock("resync")
            else:
                self.n += gap
                missing = gap - 1
        self.last_seq = seq
        ns = self.n * B
        self.off.append(arrival - ns / FS)
        c = min(self.off)
        self.c = c if self.c is None else 0.99 * self.c + 0.01 * c
        self.ring.append((ns, pcm))
        return ns, missing

    def window(self, a: int, b: int) -> np.ndarray:
        """Raw int16 samples [a, b) of this timeline (zeros where frames are missing)."""
        out = np.zeros(max(0, b - a), np.float32)
        for ns, f in self.ring:
            lo, hi = max(a, ns), min(b, ns + B)
            if lo < hi:
                out[lo - a:hi - a] = f[lo - ns:hi - ns]
        return out


# ---------------------------------------------------------------------------------------------------------------------
# One (talker -> listener) pair
# ---------------------------------------------------------------------------------------------------------------------
SEARCH_LO, SEARCH_HI = int(-0.15 * FS), int(0.6 * FS)


class Pair:
    def __init__(self, talker: str, lst: Listener):
        self.talker, self.l = talker, lst
        self.mdf = MDF(config.AEC_PARTS, config.AEC_MU)
        self.vad = webrtcvad.Vad(config.VAD_AGGRESSIVENESS)
        self.D: int | None = None            # lag from a clip's t0 placement (samples), once found; the guess for the next clip
        self.state = "search"                # search (no filter yet) | place (filter known, this clip not aligned yet) | locked
        self.s0: dict[int, int] = {}         # id(clip) -> sample index on the listener timeline where clip sample 0 sits
        self.next_n = None                   # next block start the filter expects
        self.qn, self.qd = 1.0, 1.0          # energy-weighted running sums behind q (residual power over predicted-echo power)
        self.dt_hang = 0
        self.dt_run = 0
        self.py_hold = 0.0
        self.lag0: int | None = None         # where the echo sits against the placed reference when the filter was last good
        self.run = self.voiced = 0
        self.run_start = None
        self.res_ring: collections.deque = collections.deque(maxlen=40)   # (n, residual int16) for the true start
        self.x_ring: collections.deque = collections.deque(maxlen=30)     # reference blocks, for the mismatch check
        self.d_ring: collections.deque = collections.deque(maxlen=30)     # mic blocks, same
        self.audible = 0                     # blocks of this clip with audible echo, while placing
        self.eps = 0.0                       # relative clock rate error (samples per sample) of the talker's speaker vs this mic
        self.anchor: dict[int, tuple] = {}   # id(clip) -> (n, extra delay at n)
        self.sum_d = self.sum_e = 0.0         # echo-audible power in / out while no child was detected: the clip's ERLE
        self.snap = None                     # (n, filter frequency response) at the start of the current drift measurement
        self.stats = dict(erle_db=0.0, locks=0, places=0, mismatch=0, barges=0, lag_ms=0.0)

    @property
    def q(self) -> float:
        return min(1.0, max(1e-3, self.qn / max(self.qd, 1e-9)))

    def relock(self, why: str, forget: bool = False):
        log.debug("aec %s->%s: relock (%s)", self.talker, self.l.toy, why)
        self.state, self.s0, self.next_n, self.anchor, self.snap, self.lag0 = "search", {}, None, {}, None, None
        self.mdf.reset()
        self.qn, self.qd = 1.0, 1.0
        self.dt_hang, self.dt_run, self.run, self.voiced, self.audible = 0, 0, 0, 0, 0
        if forget:
            self.D = None


class AecManager:
    """The hub's single entry point. Times are brain monotonic seconds; every call is cheap and thread-safe."""

    def __init__(self, stop_latency_s: float | None = None):
        self.lock = threading.RLock()
        self.clips: dict[str, list[Clip]] = {}
        self.listeners: dict[str, Listener] = {}
        self.stop_latency = config.AEC_STOP_LATENCY_S if stop_latency_s is None else stop_latency_s

    # ---- talker side
    def begin(self, toy: str, pcm: np.ndarray, dispatch: float, t0: float | None = None) -> Clip:
        clip = Clip(np.asarray(pcm, np.float32), dispatch, t0)
        with self.lock:
            lst = self.clips.setdefault(toy, [])
            lst.append(clip)
            del lst[:-4]
        return clip

    def playing(self, toy: str, when: float):
        """'PLAYING' from the toy, converted to brain time: the first sample leaves the speaker then."""
        with self.lock:
            for c in reversed(self.clips.get(toy, [])):
                if c.t0 is None and not c.ended:
                    c.t0 = when
                    break

    def played(self, toy: str, when: float):
        """'PLAYED': the speaker has finished (or was cut)."""
        with self.lock:
            for c in reversed(self.clips.get(toy, [])):
                if not c.ended and c.t0 is not None:
                    k = int((when - c.t0) * FS)
                    c.cut = k if c.cut is None else min(c.cut, k)
                    c.ended = True
                    break

    def stopped(self, toy: str, when: float):
        """The brain sent STOP: the speaker falls silent a moment later."""
        with self.lock:
            for c in reversed(self.clips.get(toy, [])):
                if not c.ended and c.t0 is not None:
                    k = int((when + self.stop_latency - c.t0) * FS)
                    c.cut = k if c.cut is None else min(c.cut, k)
                    break

    # ---- listener side
    def feed(self, toy: str, pcm: np.ndarray, seq: int, arrival: float) -> Out:
        """One 20 ms mic frame. Returns the frame to use (residual when a locked pair is cancelling)."""
        if len(pcm) != B:
            return Out(pcm)
        with self.lock:
            lst = self.listeners.get(toy)
            if lst is None:
                lst = self.listeners[toy] = Listener(toy)
            ns, missing = lst.frame(seq, arrival, pcm)
            if ns is None:
                return Out(pcm)
            active = self._active_pair(lst, toy, ns)
            if active is None:
                p2 = float(np.mean(pcm.astype(np.float32) ** 2))
                lst.noise2 = 0.995 * lst.noise2 + 0.005 * min(p2, 1.5 * lst.noise2)
                for p in lst.pairs.values():
                    p.next_n = None                      # the filter's history is stale after a gap
                return Out(pcm)
            pair, clips = active
            return self._run_pair(pair, clips, ns, missing, pcm)

    def _clip_span(self, pair: Pair, clip: Clip, lst: Listener):
        """(start, end) sample indices on the listener timeline where this clip's echo can be, or None if unplaced."""
        if clip.t0 is None or lst.c is None:
            return None
        base = (clip.t0 - lst.c) * FS
        lo, hi = (SEARCH_LO, SEARCH_HI) if pair.D is None else (pair.D - 1000, pair.D + 1000)
        return int(base + lo), int(base + clip.n + hi + pair.mdf.P * B)

    def _active_pair(self, lst: Listener, toy: str, ns: int):
        best = None
        for talker, clist in self.clips.items():
            if talker == toy:
                continue
            pair = lst.pairs.get(talker)
            if pair is None:
                pair = lst.pairs[talker] = Pair(talker, lst)
            live = []
            for c in clist:
                sp = self._clip_span(pair, c, lst)
                if sp and sp[0] <= ns + B and ns < sp[1] + B:
                    live.append(c)
            if live and (best is None or live[-1].t0 > best[1][-1].t0):
                best = (pair, live)
        return best

    # ---- one block through one pair
    def _base(self, pair: Pair, clip: Clip) -> float:
        return (clip.t0 - pair.l.c) * FS

    def _s0(self, pair: Pair, clip: Clip) -> int:
        k = id(clip)
        if k not in pair.s0:
            pair.s0[k] = int(round(self._base(pair, clip) + (pair.D if pair.D is not None else 0) - PRE))
        return pair.s0[k]

    def _xprime(self, pair: Pair, clips: list[Clip], n0: int, n1: int) -> np.ndarray:
        """Reference on the listener timeline for samples [n0, n1): every live clip placed at its s0, summed."""
        out = np.zeros(n1 - n0, np.float32)
        for c in clips:
            s0 = self._s0(pair, c)
            if pair.eps == 0.0 and id(c) not in pair.anchor:
                lo, hi = max(n0, s0), min(n1, s0 + c.n)
                if lo < hi:
                    out[lo - n0:hi - n0] += c.pcm[lo - s0:hi - s0]
                continue
            n_a, d_a = pair.anchor.get(id(c), (s0, 0.0))            # extra delay (samples) = d_a + eps * (n - n_a)
            n = np.arange(n0, n1)
            p = (n - s0) - (d_a + pair.eps * (n - n_a))
            out += _cubic(c.pcm[: c.n], p)
        return out

    def _run_pair(self, pair: Pair, clips: list[Clip], ns: int, missing: int, pcm: np.ndarray) -> Out:
        clip = clips[-1]
        out = Out(pcm, False, pair.talker)
        if pair.state == "locked" and id(clip) not in pair.s0:
            pair.state, pair.audible = "place", 0       # a new clip: the filter is the room's, the placement is new
            pair.mdf.reset_history()
            pair.next_n = None
        if pair.state in ("search", "place"):
            if not self._acquire(pair, clip, clips, ns):
                if pair.state == "place":
                    pair.audible += int(rms(self._xprime(pair, clips, ns, ns + B)) > 30)
                return out
        d = pcm.astype(np.float32)
        if pair.next_n is None or ns - pair.next_n > 4 * pair.mdf.P * B:
            pair.next_n = ns
            pair.mdf.reset_history()
        while pair.next_n < ns:            # lost packets: keep the reference clock moving, learn nothing from them
            x = self._xprime(pair, clips, pair.next_n, pair.next_n + B)
            pair.mdf.step(x, np.zeros(B, np.float32), 0.0)
            pair.next_n += B
        x = self._xprime(pair, clips, ns, ns + B)
        e, dt = self._block(pair, x, d)
        pair.next_n = ns + B
        e16 = np.clip(e, -32768, 32767).astype("<i2")
        pair.res_ring.append((ns, e16))
        pair.x_ring.append(x)
        pair.d_ring.append(d)
        out.pcm, out.cancelling = e16, pair.q < 0.6
        if config.BARGE_IN and out.cancelling:
            frames = self._barge_check(pair, e16, dt, ns)
            if frames:
                out.barge = frames
        self._track(pair, clip, ns)
        return out

    def _acquire(self, pair: Pair, clip: Clip, clips: list[Clip], ns: int) -> bool:
        """Find where this clip sits on the listener's timeline: a wide GCC-PHAT search for the pair's first clip (then the
        filter is trained retrospectively), a narrow one around the last lag for later clips. True once running."""
        lst = pair.l
        if clip.t0 is None or lst.c is None:
            return False
        base = self._base(pair, clip)
        local = pair.D is not None and pair.mdf.W.any()
        span = config.AEC_PLACE_S if local else config.AEC_SEARCH_S
        have = ns + B - int(base) - (pair.D if local else 0)
        if have < int((span + 0.15) * FS) + (0 if local else 1600) or (ns // B) % 5:
            return False
        lo, hi = (pair.D - 1000, pair.D + 1000) if local else (SEARCH_LO, SEARCH_HI)
        a = max(int(base) + lo, ns + B - int(2.6 * FS))
        b = ns + B
        m = lst.window(a, b)
        r = np.zeros_like(m)
        off = int(round(base)) - a
        i0, i1 = max(0, off), min(len(m), off + clip.n)
        if i1 > i0:
            r[i0:i1] = clip.pcm[i0 - off:i1 - off]
        if rms(r[max(0, off + max(lo, 0)):]) < 50.0:
            return False                      # the clip has not said much yet (or ended)
        lag, peak, score = gcc_phat(m, r, lo, hi)
        if score < (config.AEC_MIN_SCORE_PLACE if local else config.AEC_MIN_SCORE):
            pair.stats["weak"] = pair.stats.get("weak", 0) + 1
            if local and pair.audible > 0.8 * FS / B:
                pair.relock("could not place the clip", forget=True)     # the room changed: start over
            return False
        pair.D = lag
        pair.stats["lag_ms"] = lag / FS * 1000
        if local:
            pair.s0[id(clip)] = int(round(base + lag - PRE))
            pair.state, pair.qn = "locked", max(pair.qn, 0.3 * pair.qd)
            pair.mdf.reset_history()
            pair.next_n = None
            pair.stats["places"] += 1
        else:
            pair.stats["locks"] += 1
            self._retrain(pair, clips, ns)
            pair.state = "locked"
        return True

    def _retrain(self, pair: Pair, clips: list[Clip], ns: int):
        """Converge the filter on the frames already heard of this clip (adaptation passes, then a clean one)."""
        lst = pair.l
        s0 = self._s0(pair, clips[-1])
        first = lst.ring[0][0]
        frames = [(n, f) for n, f in lst.ring if n >= max(s0 - B, first) and n < ns]
        pair.mdf.reset()
        n2, num, den = lst.noise2, 0.0, 1.0
        for p in range(PASSES + 1):
            pair.mdf.reset_history()
            for n, f in frames:
                x = self._xprime(pair, clips, n, n + B)
                e, y = pair.mdf.step(x, f.astype(np.float32), 1.0 if p < PASSES else 0.0)
                if p == PASSES and float(np.mean(y * y)) > 4 * n2:
                    num += max(float(np.mean(e * e)) - n2, 0.0)
                    den += float(np.mean(y * y))
        pair.next_n = frames[-1][0] + B if frames else ns
        pair.qn, pair.qd = max(2.5 * num, 0.2 * den), den   # the last pass flatters (it saw this data): be pessimistic until measured live

    def _block(self, pair: Pair, x: np.ndarray, d: np.ndarray):
        lst = pair.l
        px = float(np.mean(x * x))
        e, y = pair.mdf.step(x, d, 0.0)
        py, pe = float(np.mean(y * y)), float(np.mean(e * e))
        n2 = lst.noise2
        echo_audible = py > 4 * n2
        # leftover echo the filter normally leaves (it follows the recent loudness, not this instant: at a syllable end the
        # residual lingers), plus the room's noise
        pair.py_hold = max(py, 0.85 * pair.py_hold)
        expected = pair.q * pair.py_hold * 1.5 + n2
        trusted = pair.q < 0.6
        dt = trusted and pe > max(config.AEC_DT_RATIO ** 2 * expected, config.AEC_MIN_RMS ** 2)
        louder = trusted and pe > max(2.0 * expected, (0.5 * config.AEC_MIN_RMS) ** 2)    # a second voice may be starting: do not learn from it
        if dt or louder:
            pair.dt_hang = 5
            pair.dt_run += 1
        else:
            pair.dt_hang = max(0, pair.dt_hang - 1)
            pair.dt_run = 0
        frozen = bool(pair.dt_hang) or pair.run > 0
        if not frozen and px > 1.0:
            pair.mdf.adapt(e, 1.0)
        if not frozen and echo_audible:
            pair.qn = 0.95 * pair.qn + max(pe - n2, 0.0)       # ~0.4 s memory, loud blocks count most
            pair.qd = 0.95 * pair.qd + py
            pair.stats["erle_db"] = 10 * np.log10(max(float(np.mean(d * d)), 1e-3) / max(pe, 1e-3))
            pair.sum_d += float(np.mean(d * d))
            pair.sum_e += pe
        if not frozen and not echo_audible and px < 1.0:
            lst.noise2 = 0.98 * lst.noise2 + 0.02 * min(pe, 1.5 * n2)
        if pair.dt_run == 12 and self._realign(pair, 12):   # loud residual that the barge detector did not take for speech
            return e, False
        if pair.dt_run == 25:                              # half a second of loud residual that was never speech to the VAD:
            pair.qn, pair.dt_hang, pair.dt_run = pair.qd, 0, 0   # stop trusting the filter and learn again instead of freezing for good
            pair.stats["relearn"] = pair.stats.get("relearn", 0) + 1
        if not pair.dt_hang and echo_audible and pair.q < 0.3 and px > 1.0 and (pair.d_ring and len(pair.d_ring) >= 29):
            if pair.lag0 is None or pair.stats.get("n", 0) % 25 == 0:
                got = self._peak_lag(pair)
                if got and (pair.lag0 is None or abs(got[0] - pair.lag0) <= 2):
                    pair.lag0 = got[0]
            pair.stats["n"] = pair.stats.get("n", 0) + 1
        return e, dt

    def _barge_check(self, pair: Pair, e16: np.ndarray, dt: bool, ns: int):
        """A run of loud, speech-like residual = the child. Returns the residual frames from its start, or None."""
        loud = dt and rms(e16) > config.AEC_MIN_RMS * 0.7
        if loud:
            if pair.run == 0:
                pair.run_start = ns
            pair.run += 1
            pair.voiced += bool(pair.vad.is_speech(e16.tobytes(), FS))
        else:
            pair.run = pair.voiced = 0
        if pair.run * 20 >= config.AEC_BARGE_MS and pair.voiced * 2 >= pair.run:
            if self._realign(pair, pair.run + 2):   # the toy was nudged, not the child talking: re-centre the filter, no cut
                return None
            pair.stats["barges"] += 1
            start = pair.run_start - config.AEC_PREROLL_FRAMES * B
            frames = [f for n, f in pair.res_ring if n >= start]
            pair.run = pair.voiced = 0
            return frames
        return None

    def _peak_lag(self, pair: Pair, n: int = 8):
        """GCC-PHAT lag of the echo in the last n mic blocks against the placed reference, (samples, score) or None."""
        if len(pair.d_ring) < n:
            return None
        d = np.concatenate(list(pair.d_ring)[-n:])
        x = np.concatenate(list(pair.x_ring)[-n:])
        if rms(x) < 100 or rms(d) < 30:
            return None
        lag, _, score = gcc_phat(d, x, 0, pair.mdf.P * B // 2, band=(300.0, 3400.0))
        return (lag, score) if score >= 4.0 else None

    def _replay(self, pair: Pair, w: np.ndarray, n: int) -> float:
        """Residual power of the last n blocks if filter taps w had been used (no adaptation; older blocks warm the history)."""
        m = MDF(pair.mdf.P, pair.mdf.mu)
        m.set_taps(w)
        X, D = list(pair.x_ring), list(pair.d_ring)
        tot = 0.0
        for i, (x, d) in enumerate(zip(X, D)):
            e, _ = m.step(x, d, 0.0)
            if i >= len(X) - n:
                tot += float(np.sum(e * e))
        return tot

    def _realign(self, pair: Pair, n: int = 8) -> bool:
        """A loud residual just began. If the echo itself has moved (the toy was nudged: its delay changed) the filter's main
        tap is in the wrong place and the residual is the toy, not the child. A candidate shift comes from GCC-PHAT; it is
        accepted only if replaying the last blocks through the shifted filter removes most of the residual (a child cannot be
        removed by shifting). True if the filter was shifted, which cancels the barge-in."""
        if pair.lag0 is None or len(pair.d_ring) < n + 4:
            return False
        got = self._peak_lag(pair, n)
        if got is None:
            return False
        delta = got[0] - pair.lag0
        if abs(delta) < 3:
            return False
        w = pair.mdf.taps()
        w2 = np.zeros_like(w)
        if delta > 0:
            w2[delta:] = w[:-delta]
        else:
            w2[:delta] = w[-delta:]
        if self._replay(pair, w2, n) > 0.5 * self._replay(pair, w, n):
            return False
        pair.mdf.set_taps(w2)
        pair.lag0 = got[0]
        pair.qn, pair.dt_hang, pair.dt_run, pair.run, pair.voiced = pair.qd, 0, 0, 0, 0   # untrusted until it has re-converged
        pair.stats["mismatch"] += 1
        return True

    def _track(self, pair: Pair, clip: Clip, ns: int):
        """Drift. While the filter is converged its frequency response is sampled; the phase change between two samples
        2 s apart (a delay change, measured sub-sample over 300-3500 Hz) divided by the time between them is the clock
        mismatch of the talker's speaker against this mic. The reference is then read at a slowly changing fractional delay
        (closed loop: the mismatch of what is left is added to eps)."""
        if pair.state != "locked" or pair.q > 0.7:
            pair.snap = None
            return
        if (ns // B) % 10 or pair.dt_hang or pair.run:
            return
        H = np.fft.rfft(pair.mdf.taps(), 4096)
        if pair.snap is None:
            pair.snap = (ns, H)
            return
        n0, H0 = pair.snap
        if ns - n0 < 1.0 * FS:
            return
        f = np.fft.rfftfreq(4096, 1 / FS)
        band = (f >= 300) & (f <= 3500)
        cross = H[band] * np.conj(H0[band])
        w = np.abs(cross)
        om = 2 * np.pi * f[band] / FS
        dtau = float(-np.sum(w * np.angle(cross) * om) / max(np.sum(w * om * om), 1e-12))   # samples later (+) or earlier (-)
        pair.snap = (ns, H)
        slope = dtau / (ns - n0)
        pair.stats["drift_meas_ppm"] = slope * 1e6
        if abs(slope) < 4e-6 or abs(dtau) > 6:
            return
        for c in self._live_anchor_clips(pair):
            n_a, d_a = pair.anchor.get(id(c), (self._s0(pair, c), 0.0))
            pair.anchor[id(c)] = (ns, d_a + pair.eps * (ns - n_a))
        pair.eps = float(np.clip(pair.eps + 0.8 * slope, -300e-6, 300e-6))
        pair.stats["drift_ppm"] = pair.eps * 1e6

    def _live_anchor_clips(self, pair: Pair):
        return [c for cl in self.clips.values() for c in cl if id(c) in pair.s0]

    # ---- reporting
    def finish(self, talker: str) -> list[str]:
        """The talker has finished (or was cut): one summary line per listener, numbers only, then reset the counters."""
        out = []
        with self.lock:
            for toy, l in self.listeners.items():
                p = l.pairs.get(talker)
                if p is None or p.sum_d <= 0:
                    continue
                out.append(f"aec {talker}->{toy}: ERLE {10 * np.log10(p.sum_d / max(p.sum_e, 1e-3)):.1f} dB over the clip, lag "
                           f"{p.stats['lag_ms']:.0f} ms, residual/echo q={p.q:.3f}, drift {p.eps * 1e6:+.0f} ppm, "
                           f"barges {p.stats['barges']}, echo-path resets {p.stats['mismatch']}")
                p.sum_d = p.sum_e = 0.0
        return out

    def snapshot(self) -> dict:
        with self.lock:
            return {f"{p.talker}->{toy}": dict(state=p.state, q=round(p.q, 3), **{k: (round(float(v), 1) if isinstance(v, float) else v) for k, v in p.stats.items()})
                    for toy, l in self.listeners.items() for p in l.pairs.values()}
