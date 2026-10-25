"""Bounded synthesis/playback overlap; complete toy lines preserve speaker order."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import queue
import threading


class SpeechPipeline:
    def __init__(self, hub, voices, trace, on_dispatch=None, before_play=None):
        self.hub, self.voices, self.trace = hub, voices, trace
        self.on_dispatch = on_dispatch or (lambda toy, text: None)
        self.before_play = before_play or (lambda: None)
        self.renders = ThreadPoolExecutor(max_workers=1, thread_name_prefix="reply-tts")
        self.pending = queue.Queue(maxsize=2)
        self.errors = []
        self.closed = False
        self.player = threading.Thread(target=self._play, name="reply-playback", daemon=True)
        self.player.start()

    def submit(self, toy, text):
        if self.closed:
            raise RuntimeError("Speech pipeline is closed")

        def render():
            with self.trace.span("tts_ms"):
                pcm = self.voices.render(toy, text)
            if pcm:
                self.trace.mark("first_pcm_ready_ms")
            return pcm
        self.pending.put((toy, text, self.renders.submit(render)))

    def _play(self):
        while True:
            item = self.pending.get()
            if item is None:
                return
            toy, text, future = item
            try:
                pcm = future.result()
                if self.errors:
                    continue
                if not pcm or toy not in self.hub.online():
                    raise RuntimeError(f"No playable audio for {toy}")

                def dispatched():
                    self.trace.mark("first_audio_post_ms")
                    self.on_dispatch(toy, text)

                with self.trace.span("filler_wait_ms"):
                    self.before_play()
                with self.trace.span("audio_post_and_playback_ms"):
                    self.hub.play(toy, pcm, on_dispatch=dispatched, raise_on_error=True)
                self.trace.mark("last_playback_ack_ms", first=False)
            except Exception as exc:
                self.errors.append(exc)

    def finish(self):
        if self.closed:
            return
        self.closed = True
        self.pending.put(None)
        self.player.join()
        self.renders.shutdown(wait=True)
        if self.errors:
            raise RuntimeError("Speech output failed: " + str(self.errors[0])) from self.errors[0]
