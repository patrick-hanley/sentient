"""Turn-taking: utterance/event in -> Gemma -> one or two toy lines out."""
from __future__ import annotations

import logging
import os
import queue
import random
import re
import tempfile
import threading
import time
import wave

from . import canned, config, debugrec
from .choreo import plan_order
from .vad import arbitrate, normalize
from .latency import HostSampler, TurnLog, TurnTrace
from .pipeline import SpeechPipeline

log = logging.getLogger("director")
NAMES = {k: t["name"].upper() for k, t in config.TOYS.items()}
# Whisper's classic hallucinations on noise / silence
HALLUCINATIONS = {"", "you", "thank you", "thanks", "thanks for watching", "thank you for watching", "bye",
                  "blank_audio", "silence", "music", "applause", "subtitles by the amaraorg community"}
LINE = re.compile(r"^\s*[*#\-\s]*(HEARD|" + "|".join(NAMES.values()) + r")\s*[*]*\s*:\s*(.*)$", re.I)


def system_prompt() -> str:
    toys = "\n".join(f"- {NAMES[k]} ({t['looks']}): {t['persona']}" for k, t in config.TOYS.items())
    topics = "\n".join(f"- {t}" for t in config.TOPICS)
    from .sfx import Sounds
    sounds = Sounds().prompt_list() or "none"
    return f"""You are the voice director for three plush toy friends who play with {config.AUDIENCE}.
The toys:
{toys}
Each turn gives you [TOYS HERE] (the only toys that may speak this turn), [SCENE] (what each toy's camera sees right now) and either the child's speech (audio or text) or an [EVENT].
Reply ONLY in this exact format and nothing else. The toy lines come FIRST, the HEARD line LAST:
<TOY NAME>: <exactly what that toy says out loud>
HEARD: <the child's words, or - if there are none>
Rules:
- One to four toy lines; when all three toys are here, usually let all three join in. The order is free and a toy may speak again after another toy (Dyno, Sage, Dyno, Penny), but never twice in a row. Toys react to the line before. If [ORDER] is given, write exactly one line per entry in exactly that order. Each line under 20 words. Words a 2nd to 5th grader knows. Warm, playful, curious.
- Talk about these things:
{topics}
- EVERY line must be about those topics. The toys never talk about their own hobbies, food, or where they live.
- If the child brings up something else (video games, TV, movies, anything), reply kindly in at most five words, then ask a school, homework or learning-game question.
- Never sing or recite song lyrics or movie lines.
- Facts, arithmetic and spellings must be accurate and right for 2nd to 5th grade. If unsure, say so and explore together.
- Penny is whimsical and silly through wordplay, playful comparisons and clearly marked make-believe. She gives careful answers and never makes deliberate factual or spelling mistakes.
- If the child says a toy's name, THAT toy answers first. Otherwise the toy in [HEARD BY] answers first. Toys may talk to each other.
- If a toy sees someone or a pet by name in [SCENE], use that name. "the child" means the child you are playing with.
- No emojis, no actions in asterisks, no lists, no stage directions.
- Sound effects: a toy may put ONE sound tag at the start of a line, e.g. "DYNO: {{knock}} Who could be at the door?". Use them for stories, animals and fun moments, not every line. Available {sounds}
- Never ask for personal information like addresses, schools or full names. Nothing scary.
- If the child sounds hurt, scared or sad, the first toy says something kind AND suggests telling a grown-up they trust, like a parent or teacher. This rule beats every other rule.
- The toys cannot move. They only know what is in [SCENE] and what the child says."""


def clean(text: str) -> str:
    # Gemma sometimes echoes prompt labels into the spoken line ("HEARD BY PENNY: ...")
    text = re.sub(r"^\s*(\[?(HEARD BY|HEARD|SCENE|TOYS HERE|EVENT)\]?[^:]{0,20}:\s*)+", "", text, flags=re.I)
    text = re.sub(r"\*[^*]*\*|\([^)]*\)|\[[^\]]*\]", "", text)
    text = re.sub(r"[^\x20-\x7E’']", "", text)
    return " ".join(text.split()).strip(" \"'")


def parse(out: str, default: str, online=None) -> tuple[str, list[tuple[str, str]]]:
    heard, lines = "", []
    by_name = {v: k for k, v in NAMES.items()}
    for raw in out.splitlines():
        m = LINE.match(raw)
        if not m:
            continue
        who, said = m.group(1).upper(), clean(m.group(2))
        if who == "HEARD":
            heard = said
            if lines:          # answer-first format: HEARD closes the reply (ignore any second draft)
                break
        elif said:
            lines.append((by_name[who], said))
    if online is not None:
        lines = [l for l in lines if l[0] in online] or ([(default, lines[0][1])] if lines else [])
    if not lines and clean(out):
        lines = [(default, clean(LINE.sub(r"\2", out.splitlines()[-1])))]
    return heard, lines[: config.MAX_LINES]


class ReplyLines:
    """Speak each complete sentence of a toy line as soon as it ends, never token fragments.

    The reply is answer-first (toy lines, then HEARD). A HEARD after any toy line
    closes the reply. Explicit leaked thought blocks are skipped. A line split into
    sentences still counts once toward MAX_LINES.
    """
    SENTENCE_END = re.compile(r"[.!?](?=\s)")
    CLAUSE_END = re.compile(r"[,;:\u2014](?=\s)")
    CLAUSE_MIN_WORDS = 5   # each TTS call has ~0.4 s fixed cost on the Pi; don't split tiny clauses
    FIRST_CLAUSE_MIN_WORDS = 3   # ...but the first piece of a reply sets time-to-first-audio (Kokoro renders ~1x real time)

    def __init__(self, online, on_line, on_heard):
        self.online, self.on_line, self.on_heard = set(online), on_line, on_heard
        self.buffer = ""
        self.header, self.closed, self.in_thought, self.count = False, False, False, 0
        self.by_name = {value: key for key, value in NAMES.items()}
        self.pieces = 0   # chunks handed to TTS so far in this reply
        self.cur, self.spoken = None, 0   # (toy, allowed) of the line in progress; chars of it already spoken

    def feed(self, delta):
        self.buffer += delta
        if len(self.buffer) > 16384:
            raise ValueError("Model output line is too long")
        while "\n" in self.buffer:
            line, self.buffer = self.buffer.split("\n", 1)
            self._line(line)
        self._partial()

    def _partial(self):
        """Speak finished sentences of the line still being written (saves ~1-2 s on long lines)."""
        if self.closed or self.in_thought or re.search(r"<(?:think|analysis)>", self.buffer, re.I):
            return
        match = LINE.match(self.buffer)
        if not match or match.group(1).upper() not in self.by_name:
            return
        rest = match.group(2)[self.spoken:]
        ends = list(self.SENTENCE_END.finditer(rest))
        if ends:
            cut = ends[-1].end()
        else:   # no sentence end yet: release a long clause so synthesis can start sooner
            need = self.CLAUSE_MIN_WORDS if self.pieces else self.FIRST_CLAUSE_MIN_WORDS
            cut = next((m.end() for m in self.CLAUSE_END.finditer(rest)
                        if len(rest[:m.end()].split()) >= need), 0)
        if cut:
            self._speak(self.by_name[match.group(1).upper()], rest[:cut])
            self.spoken += cut

    def _speak(self, toy, raw_text):
        if self.cur is None:   # first piece of a new toy line decides whether the line may play
            allowed = toy in self.online and self.count < config.MAX_LINES
            self.count += allowed
            self.cur = (toy, allowed)
        text = clean(raw_text)
        if self.cur[1] and text:
            self.pieces += 1
            self.on_line(toy, text)

    def _line(self, raw):
        if self.closed:   # still record a trailing HEARD for the dashboard; never speak more
            match = LINE.match(raw)
            if match and match.group(1).upper() == "HEARD":
                self.on_heard(clean(match.group(2)))
            return
        # Tags can straddle token chunks, since this runs on completed lines.
        while True:
            if self.in_thought:
                end = re.search(r"</(?:think|analysis)>", raw, re.I)
                if not end:
                    return
                raw, self.in_thought = raw[end.end():], False
            start = re.search(r"<(?:think|analysis)>", raw, re.I)
            if not start:
                break
            raw, self.in_thought = raw[start.end():], True
        match = LINE.match(raw)
        spoken, self.spoken = self.spoken, 0
        if not match:
            self.cur = None
            return
        who, text = match.group(1).upper(), clean(match.group(2))
        if who == "HEARD":
            self.cur = None
            # Answer-first format puts HEARD last: record it and close, so a second
            # drafted reply can never be mixed into speech. HEARD-first still works.
            self.on_heard(text)
            if self.count:
                self.closed = True
            else:
                self.header = True
            return
        elif who in self.by_name:
            # Speak the rest of the line now that it's complete (sentences already
            # spoken by _partial are skipped); no HEARD gate, which cost ~1-1.5 s.
            remainder = match.group(2)[spoken:]
            if text and (remainder.strip() or self.cur is None):
                self._speak(self.by_name[who], remainder if spoken else match.group(2))
            self.cur = None
            if self.count >= config.MAX_LINES:
                self.closed = True
        else:
            self.cur = None

    def finish(self):
        if self.buffer:
            self._line(self.buffer)
            self.buffer = ""


class Director:
    def __init__(self, hub, voices, perceiver, backend, segmenters):
        self.hub, self.voices, self.eyes, self.llm, self.segs = hub, voices, perceiver, backend, segmenters
        self.utter_q: queue.Queue = queue.Queue()
        self.events: queue.Queue = queue.Queue()
        self.last_activity = time.time()
        self.paused = False
        self.idle_on = config.IDLE_BANTER_S > 0
        self.busy = False
        self.last_heard = ""          # dashboard only; never written to disk
        self.last_lines: list = []
        self.last_latency = 0.0
        self._turn_lock = threading.Lock()
        self.active_trace = None
        self.last_trace = {}
        (config.DATA / "latency").mkdir(exist_ok=True)
        self.turn_log = TurnLog(config.DATA / "latency" / "turns.jsonl")
        self.sampler = HostSampler(hub)
        if hasattr(hub, "on_playback"):
            hub.on_playback = self._atom_playback

    def _atom_playback(self, toy, kind, when):
        """Atom-side timestamps (firmware 3.3+): the first sample the speaker clocks out, and the end of the clip."""
        t = self.active_trace
        if not t:
            return
        if kind == "PLAYING":
            t.mark("atom_first_sample_ms", when)                  # earliest sound of any kind (filler or reply)
            if "first_audio_post_ms" in t.events:
                t.mark("atom_reply_sample_ms", when)              # first clip started after the reply was posted
        else:
            t.mark("atom_play_end_ms", when, first=False)

    def latency_state(self):
        trace = self.active_trace
        return trace.snapshot() if trace else self.last_trace

    def start(self):
        self.sampler.start()
        threading.Thread(target=self._loop, daemon=True, name="director").start()

    # ---------- inputs ----------
    def on_seen(self, toy, thing):
        self.events.put(f"{NAMES[toy]} just noticed {thing.label}. {NAMES[toy]} greets them warmly by name in one short line.")

    def on_button(self, toy, kind):
        if kind == "hold":
            threading.Thread(target=self.run_canned, daemon=True).start()
        else:
            self.events.put(f"{NAMES[toy]} was gently tapped. {NAMES[toy]} says hello to the child.")

    # ---------- loop ----------
    def _loop(self):
        while True:
            try:
                u = self.utter_q.get(timeout=0.5)
            except queue.Empty:
                self._maybe_event()
                continue
            if self.paused:
                continue
            u = arbitrate(u, self.utter_q, expected_toys=self.hub.online())
            u.arbitrated = time.monotonic()
            log.info("utterance: %s %.1fs rms=%.0f", u.toy, len(u.pcm) / config.SAMPLE_RATE, u.rms)
            self._turn(utt=u)

    def _maybe_event(self):
        if self.paused or self.busy or not self.hub.online():
            return
        try:
            ev = self.events.get_nowait()
        except queue.Empty:
            ev = None
            if self.idle_on and time.time() - self.last_activity > config.IDLE_BANTER_S and len(self.hub.online()) >= 2:
                ev = self._idle_event()
        if ev:
            self._turn(event=ev)

    def _idle_event(self) -> str:
        online = self.hub.online()
        for t in online:
            v = self.eyes.views[t]
            seen = [x.label for x in v.things if x.kind == "toy"]
            if seen:
                seed = random.choice(config.BANTER_SEEDS)
                return f"{NAMES[t]} is looking at {seen[0]}. {NAMES[t]} asks {seen[0]} something about {seed}, who answers."
        seed = random.choice(config.BANTER_SEEDS)
        order = ", ".join(NAMES[t] for t in plan_order(online))
        return (f"Nobody has talked for a while. The toys chat about {seed} to invite the child to play. "
                f"[ORDER] {order}. One short line each, each reacting to the one before.")

    def _turn(self, utt=None, event=None):
        if not self._turn_lock.acquire(blocking=False):
            return
        if self.paused or not self.hub.online():
            self._turn_lock.release()
            return
        self.busy = True
        self.hub.response_active.set()
        origin = utt.last_voiced_received if utt else None
        trace = TurnTrace(origin, ("speech" if origin is not None else "speech_uninstrumented") if utt else "event",
                          toy=utt.toy if utt else None)
        self.active_trace = trace
        if utt and utt.emitted is not None:
            trace.mark("utterance_ready_ms", utt.emitted)
        if utt and utt.speech_ms:
            trace.durations["speech_ms"] = utt.speech_ms
        if utt and utt.arbitrated is not None:
            trace.mark("arbitrate_done_ms", utt.arbitrated)
        trace.mark("turn_started_ms")
        self.last_latency, self.last_lines = 0., []
        tmp_files = []
        filler = None
        pipeline = None
        status = "ok"
        try:
            online = self.hub.online()
            toy = utt.toy if utt and utt.toy in online else online[0]
            if utt and config.PLAY_FILLERS:
                f = random.choice(canned.FILLERS.get(toy, ["Hmm!"]))
                filler = threading.Thread(target=self.hub.play_line, args=(toy, f, self.voices), daemon=True)
                filler.start()
            scene = self.eyes.scene_text()
            image = None
            v = self.eyes.views.get(toy)
            if (v and v.jpeg and 0 <= time.time() - v.ts <= config.VISION_MAX_AGE_S
                    and (config.VISION_MODE == "always" or (config.VISION_MODE == "sage" and toy == "sage"))):
                image = self._tmp(v.jpeg, ".jpg")
                tmp_files.append(image)
            here = ", ".join(NAMES[t] for t in online)
            prompt = f"[TOYS HERE] {here} (only these toys may speak)\n[SCENE] {scene}\n"
            wav = None
            said = ""
            if utt:
                wav = self._wav(utt.pcm)
                debugrec.save("in", toy, normalize(utt.pcm).tobytes())
                tmp_files.append(wav)
                prompt += f"[HEARD BY] {NAMES[toy]} (closest to the child).\n"
                if self.llm.hears_audio:
                    prompt += "The child just spoke (audio attached). Reply."
                else:
                    with trace.span("stt_ms"):
                        said = self.llm.transcribe(wav)
                    trace.mark("stt_done_ms")
                    if re.sub(r"[^a-z ]", "", said.lower()).strip() in HALLUCINATIONS:
                        log.info("ignored non-speech (whisper: %r)", said)
                        status = "ignored_non_speech"
                        return
                    self.last_heard = said
                    prompt += f'The child said: "{said}"\nReply.'
            else:
                prompt += f"[EVENT] {event}"
            log.info("→ gemma: %s", prompt.replace("\n", " | "))

            def dispatched(who, text):
                self.last_lines.append((who, text))
                self.last_latency = trace.snapshot()["milestones_ms"]["first_audio_post_ms"] / 1000

            pipeline = SpeechPipeline(self.hub, self.voices, trace, dispatched,
                                      before_play=filler.join if filler else None)

            def line_ready(who, text):
                trace.mark("first_line_ready_ms")
                pipeline.submit(who, text)

            def heard(text):
                if text and text != "-":
                    self.last_heard = text

            parser = ReplyLines(online, line_ready, heard)
            kwargs = dict(wav=wav if self.llm.hears_audio else None, image=image)
            stream = getattr(self.llm, "stream", None)
            with trace.span("llm_ms"):
                chunks = stream(prompt, **kwargs) if stream else iter([self.llm.ask(prompt, **kwargs)])
                try:
                    for delta in chunks:
                        if delta:
                            trace.mark("first_model_text_ms")
                            parser.feed(delta)
                    parser.finish()
                finally:
                    close = getattr(chunks, "close", None)
                    if close:
                        close()
            trace.mark("model_done_ms")
            if not parser.count:
                raise ValueError("Model produced no labelled line for an online toy")
            pipeline.finish()
        except Exception:  # noqa: BLE001
            status = "failed"
            log.exception("turn failed")
        finally:
            if pipeline:
                try:
                    pipeline.finish()
                except Exception:
                    status = "failed"
                    log.exception("speech output failed")
            if filler:
                filler.join()
            for f in tmp_files:
                try:
                    os.unlink(f)
                except OSError:
                    pass
            self._flush()
            self.hub.response_active.clear()
            self.busy = False
            self.last_activity = time.time()
            trace.finish(status)
            self.last_trace = self.turn_log.add(dict(trace.snapshot(), host=self.sampler.latest(),
                                                    floor=getattr(self.hub, "floor", None) and self.hub.floor.snapshot()))
            self.active_trace = None
            self._turn_lock.release()
            log.info("latency: %s", self.last_trace)
            getattr(self.llm, "maybe_warm", lambda: None)()

    def _flush(self):
        """Drop speech captured while we were busy (it is usually toy echo or stale)."""
        while True:
            try:
                self.utter_q.get_nowait()
            except queue.Empty:
                break
        for s in self.segs.values():
            s.reset()

    # ---------- helpers ----------
    @staticmethod
    def _tmpdir():
        return "/dev/shm" if os.path.isdir("/dev/shm") else None

    def _tmp(self, data: bytes, suffix: str) -> str:
        fd, path = tempfile.mkstemp(suffix=suffix, dir=self._tmpdir())
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        return path

    def _wav(self, pcm) -> str:
        fd, path = tempfile.mkstemp(suffix=".wav", dir=self._tmpdir())
        os.close(fd)
        with wave.open(path, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(config.SAMPLE_RATE)
            w.writeframes(normalize(pcm).tobytes())
        return path

    def run_canned(self, scene: str | None = None):
        if not self._turn_lock.acquire(blocking=False):
            return
        self.paused = True
        self.hub.response_active.set()
        lines = canned.SCENES.get(scene, canned.SCENE)
        log.info("canned scene start: %s", scene or "default")
        try:
            for toy, text in lines:
                if toy in self.hub.online():
                    self.hub.play_line(toy, text, self.voices)
                    time.sleep(0.25)
        finally:
            self._flush()
            self.paused = False
            self.last_activity = time.time()
            self.hub.response_active.clear()
            self._turn_lock.release()
