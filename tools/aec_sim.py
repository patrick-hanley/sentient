#!/usr/bin/env python3
"""Echo-cancellation simulation rig: one toy talks, another toy's mic listens, the child talks over it.

Everything the real system has is modelled, on a virtual clock (no sleeping, no hardware, no audio played anywhere):
  * the toy line: synthetic source-filter speech (or any int16 array), mu-law coded exactly like the wire, optional
    speaker soft clipping;
  * the room: a decaying-noise impulse response with a direct path, a pre-delay, and a speaker/mic band-pass;
  * clocks: the listener's mic timeline has an unknown offset to the brain clock and a drift (ppm), the talker's
    speaker clock drifts too, mic packets arrive with network jitter and loss, the toy's 'PLAYING' stamp is early by the
    codec pipeline latency and off by a sync error;
  * ambient noise and a child talking from another direction (own short impulse response);
  * the brain side is the real `brain.aec.AecManager`, fed frame by frame with a seq number and an arrival time.

run(Scenario) -> Result with ERLE, the barge-in trigger time, the residual stream. Used by tools/test_aec.py and runnable
as a report:  .venv/bin/python tools/aec_sim.py
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from scipy import signal
from scipy.interpolate import CubicSpline

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from brain import aec as aecmod  # noqa: E402
from brain import config  # noqa: E402
from brain.atoms import ulaw_encode  # noqa: E402

FS, B = 16000, 320


# ----------------------------------------------------------------------------------------------------------- signals
def synth_speech(dur: float, seed: int, f0: float = 130.0, level: float = 2000.0, gaps: bool = True) -> np.ndarray:
    """Syllable-timed voiced speech with moving formants, a few fricatives and short pauses (float32, RMS = level)."""
    rng = np.random.default_rng(seed)
    n = int(dur * FS)
    out = np.zeros(n)
    vowels = [(730, 1090, 2440), (270, 2290, 3010), (300, 870, 2240), (530, 1840, 2480), (660, 1720, 2410), (570, 840, 2410)]
    pos = int(rng.uniform(0.0, 0.05) * FS)
    while pos < n:
        ln = int(rng.uniform(0.12, 0.28) * FS)
        ln = min(ln, n - pos)
        if ln < 200:
            break
        if rng.random() < 0.15:                                    # fricative
            nz = signal.lfilter(*signal.butter(2, [3000, 7000], "bandpass", fs=FS), rng.normal(0, 1, ln))
            seg = nz * np.hanning(ln) * 0.5
        else:
            f = f0 * (1 + 0.15 * np.sin(np.linspace(0, rng.uniform(1, 3), ln)) + rng.uniform(-0.1, 0.1))
            ph = np.cumsum(f / FS)
            pulses = (np.diff(np.floor(ph), prepend=0) > 0).astype(float)
            fm = vowels[rng.integers(len(vowels))]
            seg = pulses
            for k, fc in enumerate(fm):
                bw = 60 + 40 * k
                r = np.exp(-np.pi * bw / FS)
                a = [1, -2 * r * np.cos(2 * np.pi * fc / FS), r * r]
                seg = signal.lfilter([1 - r], a, seg)
            seg = seg * np.hanning(ln)
        seg = seg / (np.sqrt(np.mean(seg ** 2)) + 1e-9)
        out[pos:pos + ln] += seg
        pos += ln + int((rng.uniform(0.02, 0.1) if rng.random() > 0.2 or not gaps else rng.uniform(0.2, 0.4)) * FS)
    act = out[np.abs(out) > 1e-3]
    return (out / (np.sqrt(np.mean(act ** 2)) + 1e-9) * level).astype(np.float32)


def room_rir(seed: int, rt60: float = 0.25, delay_s: float = 0.0, direct: float = 1.0, length_s: float = 0.35,
             band=(180.0, 6500.0)) -> np.ndarray:
    """Direct path + exponentially decaying diffuse tail, shaped by a speaker/mic band-pass. Energy-normalised to 1."""
    rng = np.random.default_rng(seed)
    n = int(length_s * FS)
    t = np.arange(n) / FS
    tail = rng.normal(0, 1, n) * 10 ** (-3 * t / rt60)
    tail[: int(0.004 * FS)] = 0
    h = tail * 0.18
    h[0] += direct
    for k in range(4):                                                # a few early reflections
        h[int(rng.uniform(0.004, 0.03) * FS)] += rng.uniform(-0.35, 0.35)
    h = signal.lfilter(*signal.butter(2, band, "bandpass", fs=FS), h)
    d = int(delay_s * FS)
    h = np.concatenate([np.zeros(d), h])
    return (h / np.sqrt(np.sum(h ** 2))).astype(np.float64)


def resample_drift(x: np.ndarray, ppm: float, out_len: int | None = None) -> np.ndarray:
    """Sample x at t*(1+ppm*1e-6): a clock running ppm fast sees the signal slightly time-compressed."""
    if ppm == 0:
        return x if out_len is None else np.pad(x, (0, max(0, out_len - len(x))))[:out_len]
    n = len(x) if out_len is None else out_len
    t = np.arange(n) * (1 + ppm * 1e-6)
    cs = CubicSpline(np.arange(len(x)), x)
    y = np.zeros(n)
    ok = t < len(x) - 1
    y[ok] = cs(t[ok])
    return y


# ----------------------------------------------------------------------------------------------------------- scenario
@dataclass
class Scenario:
    seed: int = 1
    dur: float = 6.0                      # seconds of simulated time
    line_s: float = 4.0                   # the toy talks this long (after t_play)
    t_play: float = 0.6                   # true brain time the first sample leaves the talker's speaker
    echo_rms: float = 1200.0              # toy speech level at the listener's mic (active-speech RMS)
    child_at: float | None = None         # child starts here (None = no child)
    child_s: float = 2.0
    child_rms: float = 1500.0
    child_over_echo: float | None = None  # alternative: set the child's level relative to the echo (dB)
    noise_rms: float = 60.0
    rt60: float = 0.25
    delay_ms: float = 12.0                # speaker -> mic acoustic + codec buffer delay
    ppm: float = 0.0                      # relative clock drift between the talker's speaker and the listener's mic
    nonlinear: float = 0.0                # 0 = linear speaker; 1 = heavy soft clipping
    jitter_ms: float = 6.0                # mean extra network delay of a mic packet
    burst_every: float = 1.5              # a stall releasing several packets at once, this often (s); 0 = never
    loss: float = 0.01                    # fraction of mic packets lost
    pipe_ms: float = 45.0                 # 'PLAYING' is stamped this long before the first sample really leaves
    sync_err_ms: float = 3.0              # clock-offset error of the toy's timestamp
    mic_epoch: float = 123.4567           # brain time of the listener's sample 0
    seq0: int = 65000                     # tests wraparound
    stop_after: float | None = None       # (internal) true time the talker's speaker is cut by a STOP
    clip: np.ndarray | None = None        # use this int16 line instead of synthesising one
    room_shift_ms: float | None = None    # ...if set, the new path is the old one delayed by this much (a toy slid along the table)
    room_change_at: float | None = None   # the toy is moved / a door closes: the echo path switches to a different RIR here
    more_lines: tuple = ()                # extra (t_play, seconds) clips from the same toy, back to back (warm starts)
    child_clip: np.ndarray | None = None
    manager: object = None                # reuse an AecManager (warm start across clips)
    clock0: float = 0.0                   # brain time offset added to everything (several clips in a row)


@dataclass
class Result:
    sc: Scenario
    mic: np.ndarray                       # int16 frames that arrived: [n_frames, 320]
    res: np.ndarray                       # what the canceller handed on (same shape)
    cancelling: np.ndarray                # bool per frame
    t_frame: np.ndarray                   # brain time each frame ended (arrival, jittered)
    t_true: np.ndarray                    # true sample-clock time of the frame start, relative to scenario start
    child: np.ndarray | None = None       # the child's signal as the mic hears it (full length, int16 grid of frames)
    echo: np.ndarray | None = None        # the echo alone, as the mic hears it
    barge_frame: int | None = None
    barge_frames: list | None = None
    barge_t: float | None = None
    mgr: object = None
    lag_samples_true: float = 0.0
    erle_curve: list = field(default_factory=list)

    def erle_db(self, t0: float, t1: float) -> float:
        """ERLE over frames whose true time lies in [t0, t1): total mic power over total residual power."""
        m = (self.t_true >= t0) & (self.t_true < t1)
        if self.echo is not None:                                    # only where the toy is audibly talking
            ep = (self.echo[: len(self.mic) * B].reshape(-1, B) ** 2).mean(1)
            m &= ep > (3 * self.sc.noise_rms) ** 2
        d, e = self.mic[m].astype(np.float64), self.res[m].astype(np.float64)
        return float(10 * np.log10(np.sum(d ** 2) / max(np.sum(e ** 2), 1e-9)))

    def echo_erle_db(self, t0: float, t1: float) -> float:
        """ERLE of the echo alone: how much of the *echo component* is gone (needs a clean child-free echo + noise)."""
        return self.erle_db(t0, t1)


def _make(sc: Scenario):
    rng = np.random.default_rng(sc.seed)
    n = int(sc.dur * FS)
    line = sc.clip if sc.clip is not None else synth_speech(sc.line_s, sc.seed * 7 + 1, f0=130 + 20 * (sc.seed % 3), level=9000)
    line = np.asarray(line, np.int16)
    wire = ulaw_encode(line)
    ref = aecmod.wire_to_ref(wire)                                    # what the speaker really gets (and what the brain knows)
    # speaker output on the true time grid (talker's speaker clock drifts against the listener's mic)
    spk = np.zeros(n + FS)
    refs = [(sc.t_play, ref)]
    for j, (tp, secs) in enumerate(sc.more_lines):
        ln = synth_speech(secs, sc.seed * 7 + 11 + j, f0=130 + 20 * ((sc.seed + j + 1) % 3), level=9000)
        refs.append((tp, aecmod.wire_to_ref(ulaw_encode(np.asarray(ln, np.int16)))))
    for tp, rf in refs:
        s0 = int(tp * FS)
        k = min(len(rf), len(spk) - s0)
        x = rf[:k].astype(np.float64)
        if sc.stop_after is not None and tp == sc.t_play:             # speaker cut by STOP
            cut = max(0, int((sc.stop_after - sc.t_play) * FS))
            x = x.copy()
            x[cut:] = 0
        if sc.nonlinear:
            a = 32768 * (0.55 - 0.35 * sc.nonlinear)
            x = a * np.tanh(x / a)
        spk[s0:s0 + k] += x
    s0 = int(sc.t_play * FS)
    k = min(len(ref), len(spk) - s0)
    h = room_rir(sc.seed + 100, sc.rt60, sc.delay_ms / 1000)
    echo = signal.fftconvolve(spk, h)[: n + FS]
    if sc.room_change_at is not None:
        h2 = room_rir(sc.seed + 300, sc.rt60, sc.delay_ms / 1000 + 0.006, direct=0.9)
        if sc.room_shift_ms is not None:
            h2 = np.concatenate([np.zeros(int(sc.room_shift_ms * FS / 1000)), h])[: len(h)]
        echo2 = signal.fftconvolve(spk, h2)[: n + FS]
        w = np.clip((np.arange(n + FS) / FS - sc.room_change_at) / 0.05, 0, 1)
        echo = echo * (1 - w) + echo2 * w
    echo = resample_drift(echo, sc.ppm, n)
    act = echo[np.abs(echo) > 1e-3] if np.any(np.abs(echo) > 1e-3) else np.ones(1)
    gain = sc.echo_rms / (np.sqrt(np.mean(echo[s0:s0 + k] ** 2)) + 1e-9) if k else 1.0
    echo = echo * gain
    noise = signal.lfilter([1, 0.6], [1, -0.4], rng.normal(0, 1, n))
    noise = noise / noise.std() * sc.noise_rms
    child = np.zeros(n)
    if sc.child_at is not None:
        cl = sc.child_clip if sc.child_clip is not None else synth_speech(sc.child_s, sc.seed * 13 + 5, f0=250 + 10 * (sc.seed % 4), level=1000, gaps=False)
        cl = cl[: int(sc.child_s * FS)].astype(np.float64)
        hc = room_rir(sc.seed + 200, 0.2, 0.003, direct=0.8, length_s=0.2)
        cl = signal.fftconvolve(cl, hc)[: len(cl)]
        lvl = sc.child_rms
        if sc.child_over_echo is not None:
            lvl = sc.echo_rms * 10 ** (sc.child_over_echo / 20)
        cl = cl / (np.sqrt(np.mean(cl[np.abs(cl) > 1e-3] ** 2)) + 1e-9) * lvl
        c0 = int(sc.child_at * FS)
        child[c0:c0 + len(cl)] = cl[: n - c0]
    mic = echo + noise + child
    return refs, mic, echo, child, wire


def run(sc: Scenario, two_pass: bool = True) -> Result:
    """Feed the scenario to AecManager. With a trigger, rerun with the speaker cut by the STOP the brain would have sent."""
    res = _run_once(sc)
    if two_pass and res.barge_t is not None and sc.stop_after is None:
        sc2 = Scenario(**{**sc.__dict__, "stop_after": res.barge_t - sc.mic_epoch - sc.clock0 + 0.03, "manager": None})
        res2 = _run_once(sc2, stop_at_trigger=res.barge_t)
        res2.barge_t, res2.barge_frame, res2.barge_frames = res.barge_t, res.barge_frame, res.barge_frames
        return res2
    return res


def _run_once(sc: Scenario, stop_at_trigger: float | None = None) -> Result:
    refs, mic, echo, child, wire = _make(sc)
    rng = np.random.default_rng(sc.seed + 999)
    mgr = sc.manager or aecmod.AecManager()
    nfr = len(mic) // B
    frames = np.round(np.clip(mic[: nfr * B], -32768, 32767)).astype("<i2").reshape(nfr, B)
    # arrival times: sample clock frame k ends at epoch + (k+1)*0.02 (listener clock = reference), plus jitter and stalls
    ends = sc.clock0 + sc.mic_epoch + (np.arange(nfr) + 1) * B / FS
    jit = rng.exponential(sc.jitter_ms / 1000, nfr) + 0.002
    arr = ends + jit
    if sc.burst_every:
        for t in np.arange(sc.burst_every, sc.dur, sc.burst_every):   # a stall: ~60-120 ms of packets arrive together
            i = int(t / (B / FS))
            m = rng.integers(3, 6)
            if i + m < nfr:
                arr[i:i + m] = np.max(arr[i:i + m]) + 0.0005 * np.arange(m)
    arr = np.maximum.accumulate(arr)
    lost = rng.random(nfr) < sc.loss
    # talker's events (brain time)
    evs = []                                                      # (arrival time, kind, payload)
    for tp, rf in refs:
        td = sc.clock0 + sc.mic_epoch + tp - 0.12
        t0r = sc.clock0 + sc.mic_epoch + tp - sc.pipe_ms / 1000 + rng.normal(0, sc.sync_err_ms / 1000 / 2) + sc.sync_err_ms / 1000 * 0.5
        evs += [(td, "begin", (rf, td)), (td + 0.15, "playing", t0r)]
    evs.sort(key=lambda e: e[0])
    out = np.zeros_like(frames)
    canc = np.zeros(nfr, bool)
    res = Result(sc, frames, out, canc, arr, np.arange(nfr) * B / FS, child, echo, mgr=mgr)
    for k in range(nfr):
        t = arr[k]
        while evs and t >= evs[0][0]:
            _, kind, pl = evs.pop(0)
            if kind == "begin":
                mgr.begin("dyno", *pl)
            else:
                mgr.playing("dyno", pl)
        if lost[k]:
            out[k] = 0
            continue
        o = mgr.feed("sage", frames[k], (sc.seq0 + k) & 0xFFFF, t)
        out[k], canc[k] = o.pcm, o.cancelling
        if o.barge is not None and res.barge_t is None:
            res.barge_t, res.barge_frame, res.barge_frames = t, k, o.barge
            mgr.stopped("dyno", t)                                   # what the hub does: STOP goes out, the reference is cut
    return res


# ------------------------------------------------------------------------------------------------------------- report
def main():
    print("ERLE (dB) once converged, echo + noise only, 4 s line, other 25 ms of clock jitter, 1% loss")
    for name, kw in [("clean room", {}), ("long reverb rt60 0.5", dict(rt60=0.5)), ("drift 100 ppm", dict(ppm=100)),
                     ("noisy (rms 200)", dict(noise_rms=200)), ("clipping speaker", dict(nonlinear=0.8)),
                     ("sync error 40 ms", dict(sync_err_ms=40, pipe_ms=120))]:
        r = run(Scenario(**kw), two_pass=False)
        print(f"  {name:24s} ERLE 1.5-2.5 s: {r.erle_db(1.5, 2.5):5.1f}   3.5-4.5 s: {r.erle_db(3.5, 4.5):5.1f}   locked at "
              f"{r.mgr.snapshot()['dyno->sage']['lag_ms']:.0f} ms")
    print("barge-in, child 2 s long starting at 2.0 s over the toy:")
    for db in (6, 0, -6):
        r = run(Scenario(child_at=2.0, child_over_echo=db))
        lat = None if r.barge_t is None else r.barge_t - (r.sc.mic_epoch + 2.0)
        print(f"  child {db:+d} dB vs echo: trigger {'none' if lat is None else f'{lat * 1000:.0f} ms after onset'}")


if __name__ == "__main__":
    main()
