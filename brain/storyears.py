"""Fast ears for story mode: a small streaming speech recogniser (sherpa-onnx zipformer, CPU) hears the words WHILE the child
reads, so a sound can start within a second of its word. Gemma needs the whole sentence first (2-3 s after it ended, measured
with the Mac's mic, Nov 21) and stays as the backup. Runs only while story mode is on. Audio stays in RAM; no words are logged.

Model: offline/asr/sherpa-onnx-streaming-zipformer-en-20M-2023-02-17 (k2-fsa/sherpa-onnx releases, asr-models). Missing model or
library: the ears are simply off and story mode works as before.
"""
from __future__ import annotations

import logging
import queue
import threading

import numpy as np

from . import config

log = logging.getLogger("storyears")


class StoryEars:
    def __init__(self, on_words, active):
        """on_words(toy, text, final): the words heard so far in this stretch of speech (lower case); final=True when a pause
        ended it. active(): story mode is on."""
        self.on_words, self.active = on_words, active
        self.ok, self.rec, self.streams, self.last, self.done, self.flushed = False, None, {}, {}, {}, {}
        self.lvl = {}      # per toy: [recent speech level, seconds of quiet so far, already flushed]
        self.q: queue.Queue = queue.Queue(maxsize=600)
        self.was_on, self.dropped = False, 0
        d = config.STORY_EARS_MODEL
        try:
            if not config.STORY_EARS or not (d / "tokens.txt").exists():
                return
            import sherpa_onnx
            self.rec = sherpa_onnx.OnlineRecognizer.from_transducer(
                tokens=str(d / "tokens.txt"), encoder=str(d / "encoder-epoch-99-avg-1.int8.onnx"),
                decoder=str(d / "decoder-epoch-99-avg-1.onnx"), joiner=str(d / "joiner-epoch-99-avg-1.int8.onnx"),
                num_threads=2, sample_rate=config.SAMPLE_RATE, feature_dim=80, decoding_method="greedy_search",
                enable_endpoint_detection=True, rule1_min_trailing_silence=2.4,
                rule2_min_trailing_silence=config.STORY_EARS_PAUSE_S, rule3_min_utterance_length=30)
            self.ok = True
            threading.Thread(target=self._run, daemon=True, name="story-ears").start()
            log.info("story ears ready (streaming recogniser)")
        except Exception as exc:  # noqa: BLE001
            log.warning("story ears off (%s)", exc)

    def feed(self, toy, pcm):
        """One mic frame (int16). Costs nothing unless story mode is on."""
        if not self.ok or not self.active():
            self.was_on = False
            return
        try:
            self.q.put_nowait((toy, pcm))
        except queue.Full:
            self.dropped += 1
            if self.dropped % 250 == 1:
                log.warning("story ears behind: %d mic frames dropped", self.dropped)

    def _run(self):
        while True:
            toy, pcm = self.q.get()
            try:
                self.step(toy, pcm)
            except Exception:  # noqa: BLE001
                log.exception("story ears failed")

    def pad(self, lv, x):
        """What is fed in when the mic goes quiet: the room's own quiet from the last moments, repeated. Pure zeros are nothing
        the model ever heard."""
        q = np.concatenate(lv[3][-15:]) if lv[3] else x
        return np.tile(q, int(0.8 * config.SAMPLE_RATE) // max(1, len(q)) + 1)[:int(0.8 * config.SAMPLE_RATE)]

    def step(self, toy, pcm):
        """One mic frame through the recogniser."""
        if not self.was_on:      # story mode just began: fresh streams
            self.streams, self.last, self.lvl, self.done, self.flushed, self.was_on = {}, {}, {}, {}, {}, True
        s = self.streams.get(toy)
        if s is None:
            s = self.streams[toy] = self.rec.create_stream()
        x = np.asarray(pcm, dtype=np.float32)
        flush = False
        s.accept_waveform(config.SAMPLE_RATE, x / 32768.0)
        # The recogniser shows a word ~0.5 s after it was said and wants its own pause on top (0.95 s from the last word to the
        # sound's order, live Nov 21). So when the mic goes quiet after words, quiet is fed in at once: the last words come out
        # and the pause is seen now, not half a second later.
        lv = self.lvl.setdefault(toy, [0.0, 0.0, False, []])
        r = float(np.sqrt((x * x).mean())) if len(x) else 0.0
        lv[0] = max(lv[0] * 0.999, r)
        if r < max(80.0, 0.12 * lv[0]):
            lv[1] += len(x) / config.SAMPLE_RATE
            lv[3] = lv[3][-14:] + [x]
            if lv[1] >= config.STORY_EARS_QUIET_S and not lv[2]:
                lv[2] = flush = True
                s.accept_waveform(config.SAMPLE_RATE, self.pad(lv, x) / 32768.0)
        else:
            lv[1], lv[2] = 0.0, False
        while self.rec.is_ready(s):
            self.rec.decode_stream(s)
        text = self.rec.get_result(s).lower()
        end = self.rec.is_endpoint(s)
        # A short pause (a comma) hands over the words since the last pause as finished, but the recogniser keeps its stream:
        # restarted at every comma it lost the clause after it ("the hound barked" went missing, live Nov 21).
        done = self.done.get(toy, 0)
        part, final = text[done:], end or flush
        stale = text == self.flushed.get(toy)      # nothing new since the last pause: its last word is not handed over again
        if flush:
            self.flushed[toy] = text
        if part.strip() and not stale and (final or text != self.last.get(toy)):
            self.last[toy] = text
            self.on_words(toy, part, final)
        if flush:      # the last word may still grow ("bark" -> "barked"): it is handed over again with the next words
            self.done[toy] = text.rfind(" ") + 1 if not end else len(text)
        if end:
            self.rec.reset(s)
            self.last[toy], self.done[toy], self.flushed[toy] = "", 0, ""
