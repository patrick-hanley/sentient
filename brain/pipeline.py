"""Bounded synthesis/playback overlap; complete toy lines preserve speaker order."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import queue
import threading
import time

import random

from . import canned, config, debugrec


class SpeechPipeline:
    def __init__(self, hub, voices, trace, on_dispatch=None, before_play=None):
        self.hub, self.voices, self.trace = hub, voices, trace
        self.on_dispatch = on_dispatch or (lambda toy, text: None)
        self.before_play = before_play or (lambda: None)
        self.renders = ThreadPoolExecutor(max_workers=1, thread_name_prefix="reply-tts")
        self.pending = queue.Queue(maxsize=3)   # renders run ahead of playback so the next toy is ready at the handoff
        self.errors = []
        self.bridges, self.last_bridge = 0, None
        self.last_end = None   # monotonic end of the previous line, to measure dead air between toys
        self.closed = False
        self.player = threading.Thread(target=self._play, name="reply-playback", daemon=True)
        self.player.start()

    def submit(self, toy, text):
        if self.closed:
            raise RuntimeError("Speech pipeline is closed")

        def render():
            config.pin(config.TTS_CORES)
            with self.trace.span("tts_ms"):
                pcm = self.voices.render(toy, text)
            if pcm:
                self.trace.mark("first_pcm_ready_ms")
                debugrec.save("out", toy, pcm)
            return pcm
        self.pending.put((toy, text, self.renders.submit(render)))

    def _play(self):
        while True:
            item = self.pending.get()
            if item is None:
                return
            toy, text, future = item
            try:
                self._bridge(toy, future)
                pcm = future.result()
                if self.errors:
                    continue
                if not pcm or toy not in self.hub.online():
                    raise RuntimeError(f"No playable audio for {toy}")

                def dispatched():
                    self.trace.mark("first_audio_post_ms")
                    if self.last_end is not None:
                        gap = (time.monotonic() - self.last_end) * 1000
                        with self.trace.lock:
                            self.trace.durations["handoff_gap_ms"] = self.trace.durations.get("handoff_gap_ms", 0.) + gap
                            self.trace.durations["handoff_gap_max_ms"] = max(self.trace.durations.get("handoff_gap_max_ms", 0.), gap)
                    self.on_dispatch(toy, text)

                with self.trace.span("filler_wait_ms"):
                    self.before_play()
                with self.trace.span("audio_post_and_playback_ms"):
                    self.hub.play(toy, pcm, on_dispatch=dispatched, raise_on_error=True)
                self.trace.mark("last_playback_ack_ms", first=False)
                self.last_end = time.monotonic()
            except Exception as exc:
                self.errors.append(exc)

    def _bridge(self, toy, future):
        """Dead air before this line (synthesis still running): the speaker reacts with a canned clip
        that lives in the Atom's flash, so it starts at once and costs the brain no synthesis."""
        if future.done() or not config.PLAY_FILLERS or self.bridges >= config.MAX_BRIDGES:
            return
        atom = getattr(self.hub, "atoms", {}).get(toy)
        clip_id = getattr(self.voices, "clip_id", None)
        if not atom or not clip_id:
            return
        try:
            future.exception(timeout=config.BRIDGE_WAIT_S)   # a brief wait is natural; longer is dead air
        except Exception:   # noqa: BLE001 — timeout means still rendering
            pass
        if future.done():
            return
        options = [t for t in canned.FILLERS.get(toy, []) if clip_id(toy, t) in atom.clips and t != self.last_bridge]
        if not options:
            return
        self.last_bridge = random.choice(options)
        self.bridges += 1
        with self.trace.span("bridge_ms"):
            self.hub.play_line(toy, self.last_bridge, self.voices)
        self.trace.mark("first_bridge_ms")

    def finish(self):
        if self.closed:
            return
        self.closed = True
        self.pending.put(None)
        self.player.join()
        self.renders.shutdown(wait=True)
        if self.errors:
            raise RuntimeError("Speech output failed: " + str(self.errors[0])) from self.errors[0]
