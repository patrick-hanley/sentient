"""Cross-toy echo cancellation (brain/aec.py): simulated room, clocks and child (tools/aec_sim.py), plus the hub and director
glue. No hardware, no audio played. Run: .venv/bin/python tools/test_aec.py   (about 40 s)"""
import queue
import sys
import threading
import time
import types
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import aec_sim as S  # noqa: E402
from brain import aec, atoms, config  # noqa: E402
from brain.vad import Segmenter  # noqa: E402

SEEDS = (1, 2, 3, 4)


def erle(kw, window=(3.0, 4.0), seeds=SEEDS):
    out = []
    for sd in seeds:
        r = S.run(S.Scenario(seed=sd, **kw), two_pass=False)
        out.append(r.erle_db(*window))
    return float(np.mean(out)), out


class UnitTests(unittest.TestCase):
    def test_gcc_phat_finds_delay_and_confidence(self):
        rng = np.random.default_rng(0)
        r = S.synth_speech(1.0, 3, level=3000).astype(np.float64)
        m = np.concatenate([np.zeros(1234), r])[: len(r)] * 0.3 + rng.normal(0, 100, len(r))
        lag, peak, score = aec.gcc_phat(m, r, -2000, 4000)
        self.assertEqual(lag, 1234)
        self.assertGreater(score, 10)
        _, _, noscore = aec.gcc_phat(rng.normal(0, 100, len(r)), r, -2000, 4000)
        self.assertLess(noscore, config.AEC_MIN_SCORE)       # unrelated audio is not "found"

    def test_mdf_identifies_a_path_from_white_noise(self):
        rng = np.random.default_rng(1)
        h = S.room_rir(5, 0.2, 0.01)[:2400]
        x = rng.normal(0, 3000, 16000 * 6)
        d = np.convolve(x, h)[: len(x)]
        f = aec.MDF(8, 0.5)
        e_tot = d_tot = 0.0
        for k in range(len(x) // 320):
            e, _ = f.step(x[k * 320:(k + 1) * 320], d[k * 320:(k + 1) * 320], 1.0)
            if k > 200:
                e_tot += float(np.sum(e ** 2))
                d_tot += float(np.sum(d[k * 320:(k + 1) * 320] ** 2))
        self.assertGreater(10 * np.log10(d_tot / e_tot), 30)

    def test_wire_roundtrip_matches_what_the_speaker_gets(self):
        x = (S.synth_speech(0.5, 2, level=8000)).astype(np.int16)
        ref = aec.wire_to_ref(atoms.ulaw_encode(x))
        self.assertLess(np.sqrt(np.mean((ref - x) ** 2)) / np.sqrt(np.mean(x.astype(float) ** 2)), 0.05)
        half = aec.wire_to_ref(atoms.ulaw_encode(x[::2]), "ulaw", 8000)
        self.assertEqual(len(half), len(x) - len(x) % 2 or len(x))

    def test_fractional_reference_read(self):
        x = np.sin(2 * np.pi * 440 * np.arange(1600) / 16000).astype(np.float32)
        p = np.arange(100, 400) - 0.37
        y = aec._cubic(x, p)
        want = np.sin(2 * np.pi * 440 * p / 16000)
        self.assertLess(np.max(np.abs(y - want)), 2e-3)

    def test_listener_timeline_wraps_and_resyncs(self):
        lst = aec.Listener("sage")
        f = np.zeros(320, np.int16)
        ns = [lst.frame(s & 0xFFFF, 1.0 + i * 0.02, f)[0] for i, s in enumerate(range(65530, 65545))]
        self.assertEqual(ns, [i * 320 for i in range(15)])           # monotone across 65535 -> 0
        _, missing = lst.frame(65544 - 65536 + 3, 2.0, f)
        self.assertEqual(missing, 2)
        lst.pairs["dyno"] = aec.Pair("dyno", lst)
        lst.pairs["dyno"].state = "locked"
        lst.frame(11 + 20000, 5.0, f)                                 # a jump: reboot or /play upload
        self.assertEqual(lst.pairs["dyno"].state, "search")
        self.assertIsNone(lst.frame(11 + 20000, 5.0, f)[0])                # duplicate ignored


class ErleTests(unittest.TestCase):
    """ERLE = mic power / residual power while the toy talks and nobody else does (frames where the echo is audible)."""

    def test_clean_room(self):
        m, per = erle({})
        print(f"\n  ERLE clean room: {m:.1f} dB {np.round(per, 1)}")
        self.assertGreater(m, 14)
        self.assertGreater(min(per), 10)

    def test_long_reverb(self):
        m, _ = erle(dict(rt60=0.5))
        print(f"  ERLE rt60 0.5 s: {m:.1f} dB")
        self.assertGreater(m, 10)

    def test_noisy_room_and_nonlinear_speaker(self):
        m1, _ = erle(dict(noise_rms=200))
        m2, _ = erle(dict(nonlinear=0.8))
        print(f"  ERLE noise rms 200: {m1:.1f} dB, clipping speaker: {m2:.1f} dB")
        self.assertGreater(m1, 6)
        self.assertGreater(m2, 6)

    def test_timestamp_and_clock_errors_are_found_by_gcc_phat(self):
        base, _ = erle({})
        m, _ = erle(dict(sync_err_ms=40, pipe_ms=120, jitter_ms=15))
        print(f"  ERLE with a 40 ms sync error, 120 ms pipeline, 15 ms jitter: {m:.1f} dB (clean {base:.1f})")
        self.assertGreater(m, base - 3)

    def test_lost_packets_and_burst_arrivals(self):
        m, _ = erle(dict(loss=0.05, burst_every=0.7))
        self.assertGreater(m, 10)

    def test_clock_drift_is_tracked(self):
        out = []
        for sd in SEEDS:
            r = S.run(S.Scenario(seed=sd, ppm=40, line_s=6, dur=8), two_pass=False)
            snap = r.mgr.snapshot()["dyno->sage"]
            out.append((r.erle_db(4.0, 6.0), snap.get("drift_ppm", 0.0)))
        erle_m = float(np.mean([o[0] for o in out]))
        ppm_m = float(np.mean([o[1] for o in out]))
        print(f"  40 ppm drift: ERLE at 4-6 s {erle_m:.1f} dB, estimated drift {ppm_m:+.0f} ppm (sim sign: negative)")
        self.assertGreater(erle_m, 10)
        self.assertLess(abs(abs(ppm_m) - 40), 15)

    def test_second_clip_places_itself_and_keeps_the_filter(self):
        r = S.run(S.Scenario(seed=2, dur=16, line_s=3.0, more_lines=((6.0, 3.0), (10.5, 3.0))), two_pass=False)
        snap = r.mgr.snapshot()["dyno->sage"]
        self.assertEqual(snap["locks"], 1)            # one full search; the next clips only re-align (warm start)
        self.assertEqual(snap["places"], 2)
        self.assertGreater(r.erle_db(7.2, 9.0), 8)
        self.assertGreater(r.erle_db(11.7, 13.5), 8)
        self.assertEqual(snap["barges"], 0)

    def test_no_clock_no_cancelling(self):
        """Without a PLAYING timestamp the canceller never claims a residual: frames pass through untouched."""
        mgr = aec.AecManager()
        mgr.begin("dyno", np.ones(16000, np.float32) * 1000, 100.0)          # t0 never arrives
        rng = np.random.default_rng(0)
        for k in range(100):
            f = rng.normal(0, 500, 320).astype("<i2")
            o = mgr.feed("sage", f, k, 100.0 + k * 0.02)
            self.assertFalse(o.cancelling)
            self.assertTrue(np.array_equal(o.pcm, f))


class BargeTests(unittest.TestCase):
    def test_child_over_the_toy_triggers_fast_and_keeps_the_first_word(self):
        lat = []
        for sd in (1, 3, 4, 5):
            r = S.run(S.Scenario(seed=sd, child_at=2.5, child_over_echo=6, dur=7))
            self.assertIsNotNone(r.barge_t, f"seed {sd}: no barge-in")
            lat.append(r.barge_t - (r.sc.mic_epoch + 2.5))
            onset_frame = int(2.5 * 16000 / 320)
            # the frames returned reach back before the onset: the segmenter sees the true start
            first = r.barge_frame - len(r.barge_frames) + 1
            self.assertLessEqual(first, onset_frame)
            self.assertGreater(first, onset_frame - 30)
        print(f"\n  barge-in latency, child +6 dB over the toy: {np.round(np.array(lat) * 1000)} ms after onset")
        self.assertLess(max(lat), 0.6)

    def test_equal_loudness_child_is_still_heard(self):
        got = [S.run(S.Scenario(seed=sd, child_at=2.5, child_over_echo=0)).barge_t is not None for sd in (1, 3, 4, 5, 6)]
        print(f"  child at 0 dB vs the echo: barge-in in {sum(got)}/5 runs")
        self.assertGreaterEqual(sum(got), 4)

    def test_no_false_triggers_without_a_child(self):
        n = tot = 0
        for kw in ({}, dict(rt60=0.5), dict(nonlinear=0.8), dict(ppm=30), dict(noise_rms=150)):
            for sd in range(1, 9):
                r = S.run(S.Scenario(seed=sd, **kw), two_pass=False)
                n += r.barge_t is not None
                tot += 1
        print(f"  false barge-ins without a child: {n}/{tot} clips")
        self.assertEqual(n, 0)

    def test_toy_cut_then_the_childs_utterance_comes_out_whole(self):
        """Closed loop: the trigger sends STOP (the speaker really falls silent 30 ms later); the residual stream
        from the first returned frame on goes to the real Segmenter and one utterance starts at the child's first word."""
        for sd in (1, 3, 5):
            r = S.run(S.Scenario(seed=sd, child_at=2.5, child_over_echo=6, dur=7))
            self.assertIsNotNone(r.barge_t)
            q = queue.Queue()
            seg = Segmenter("sage", q)
            for f in list(r.barge_frames) + [r.res[k] for k in range(r.barge_frame + 1, len(r.res))]:
                seg.feed(f)
            self.assertFalse(q.empty(), f"seed {sd}: nothing reached the director")
            u = q.get_nowait()
            self.assertTrue(q.empty(), "one utterance, not a toy-echo remnant after it")
            child = r.child[int(2.5 * 16000):int(2.5 * 16000) + 4800]
            cc = np.correlate(u.pcm.astype(float), child, "valid")
            pos = int(np.argmax(np.abs(cc))) / 16000
            self.assertLess(pos, 0.4)                                 # the child's onset is at the head of the utterance
            self.assertGreater(len(u.pcm) / 16000, 1.8)              # and the whole 2 s sentence is in it

    def test_stop_cuts_the_reference_so_no_phantom_echo_is_subtracted(self):
        """After STOP the speaker is silent; subtracting the rest of the clip would add a phantom echo to the child's audio."""
        r = S.run(S.Scenario(seed=3, child_at=2.5, child_over_echo=6, dur=7))
        k0 = r.barge_frame + 8                                        # after the speaker has stopped and the tail died
        res = r.res[k0:k0 + 20].astype(float)
        mic = r.mic[k0:k0 + 20].astype(float)
        child = r.child[k0 * 320:(k0 + 20) * 320].reshape(20, 320)
        self.assertLess(np.mean((res - (mic - 0)) ** 2) ** .5, 3 * np.mean(child ** 2) ** .5)   # sanity: same order as the child
        # the residual should not carry more than the child + noise: no echo of a clip that is no longer playing
        extra = (res - child.astype(float))
        self.assertLess(np.sqrt(np.mean(extra ** 2)), 0.45 * np.sqrt(np.mean(child ** 2)) + 150)


class HubGlueTests(unittest.TestCase):
    """AtomHub._handle with the real canceller on a virtual clock: gated while the toy talks, cut + hand-over on the child."""

    def make_hub(self):
        hub = atoms.AtomHub.__new__(atoms.AtomHub)
        hub.atoms, hub.by_ip, hub.by_addr = {}, {}, {}
        hub.monitor = None
        hub.mute_until, hub.force_mute, hub.talking, hub.play_id = 0.0, False, None, 0
        hub.barge, hub.aec = atoms.BargeDetector(), aec.AecManager()
        self.fallback_calls = 0
        hub.barge.feed = lambda *a, **k: setattr(self, "fallback_calls", self.fallback_calls + 1)   # the loudness detector: counted, silent
        hub._barged, hub._barge_toy, hub._barge_frames = False, None, []
        self.heard, self.cut = [], []
        hub.on_audio = lambda toy, pcm: self.heard.append((toy, pcm.copy()))
        hub.on_barge = lambda toy: self.cut.append(toy)
        hub.on_playback = None
        hub.on_button = lambda *a: None
        hub.sock = types.SimpleNamespace(sendto=lambda *a: None)
        for toy, ip in (("dyno", "10.0.0.1"), ("sage", "10.0.0.2")):
            a = atoms.Atom(mac=toy, ip=ip, toy=toy, last_seen=time.time())
            hub.atoms[toy], hub.by_ip[ip] = a, a
        hub.floor.human_start = lambda: None
        return hub

    def test_residual_goes_to_the_segmenter_only_after_the_child_cuts_in(self):
        hub = self.make_hub()
        sc = S.Scenario(seed=3, child_at=2.5, child_over_echo=6, dur=6)
        refs, mic, echo, child, _ = S._make(sc)
        rng = np.random.default_rng(5)
        nfr = len(mic) // 320
        frames = np.round(np.clip(mic[: nfr * 320], -32768, 32767)).astype("<i2").reshape(nfr, 320)
        clock = [0.0]
        fake_time = types.SimpleNamespace(monotonic=lambda: clock[0], time=lambda: clock[0] + 1e9, sleep=time.sleep)
        real = atoms.time
        atoms.time = fake_time
        try:
            hub.talking, hub.mute_until = "dyno", 1e18          # a brain clip is playing: mics gated
            t_play = sc.mic_epoch + sc.t_play
            hub.aec.begin("dyno", refs[0][1], t_play - 0.12)
            playing = False
            cut_at = None
            for k in range(nfr):
                clock[0] = sc.mic_epoch + (k + 1) * 0.02 + 0.004
                if not playing and clock[0] >= t_play - 0.05:
                    hub.aec.playing("dyno", t_play - 0.045)
                    playing = True
                hub._handle(b"M" + ((sc.seq0 + k) & 0xFFFF).to_bytes(2, "little") + frames[k].tobytes(), "10.0.0.2", 0)
                if self.cut and cut_at is None:
                    cut_at = k
                    hub.aec.stopped("dyno", clock[0])
        finally:
            atoms.time = real
        self.assertEqual(self.cut, ["sage"])
        onset = int(2.5 * 50)
        self.assertIsNotNone(cut_at)
        self.assertGreaterEqual(cut_at, onset)                  # not before the child began
        self.assertLess(cut_at - onset, 30)                     # within 0.6 s
        self.assertGreater(self.fallback_calls, 10)             # until the echo model is up (first ~0.65 s) the loudness detector listens
        self.assertTrue(self.heard, "the child's words must reach the segmenter before play() has even returned")
        self.assertTrue(all(t == "sage" for t, _ in self.heard))
        self.assertGreater(len(self.heard), 40)
        # no frame from before the child began (apart from the pre-roll) was handed on while the toy talked
        self.assertLessEqual(len(self.heard), nfr - onset + 30)


class DirectorGlueTests(unittest.TestCase):
    def test_flush_after_a_barge_keeps_the_childs_utterance_and_a_segment_in_progress(self):
        from brain import director as dmod
        d = dmod.Director.__new__(dmod.Director)
        d.utter_q = queue.Queue()
        t = time.time()
        old = types.SimpleNamespace(end=t - 5.0)
        new = types.SimpleNamespace(end=t + 0.1)
        d.utter_q.put(old)
        d.utter_q.put(new)
        resets = []
        d.segs = {"sage": types.SimpleNamespace(active=True, reset=lambda: resets.append("sage")),
                  "dyno": types.SimpleNamespace(active=False, reset=lambda: resets.append("dyno"))}
        d._barge_t = t
        d._flush()
        self.assertIs(d.utter_q.get_nowait(), new)
        self.assertTrue(d.utter_q.empty())
        self.assertEqual(resets, ["dyno"])                    # the child is mid-sentence on sage: do not cut it
        d._barge_t = 0.0                                      # no barge: the old behaviour, everything dropped
        d.utter_q.put(new)
        d._flush()
        self.assertTrue(d.utter_q.empty())
        self.assertEqual(sorted(resets), ["dyno", "dyno", "sage"])


if __name__ == "__main__":
    unittest.main()
