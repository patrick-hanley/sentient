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

from . import canned, config
from .vad import arbitrate, normalize

log = logging.getLogger("director")
NAMES = {k: t["name"].upper() for k, t in config.TOYS.items()}
# Whisper's classic hallucinations on noise / silence
HALLUCINATIONS = {"", "you", "thank you", "thanks", "thanks for watching", "thank you for watching", "bye",
                  "blank_audio", "silence", "music", "applause", "subtitles by the amaraorg community"}
LINE = re.compile(r"^\s*[*#\-\s]*(HEARD|" + "|".join(NAMES.values()) + r")\s*[*]*\s*:\s*(.+)$", re.I)


def system_prompt() -> str:
    toys = "\n".join(f"- {NAMES[k]} ({t['looks']}): {t['persona']}" for k, t in config.TOYS.items())
    return f"""You are the voice director for three plush toy friends who play with a young child (about 4 to 7 years old).
The toys:
{toys}
Each turn gives you [TOYS HERE] (the only toys that may speak this turn), [SCENE] (what each toy's camera sees right now) and either the child's speech (audio or text) or an [EVENT].
Reply ONLY in this exact format and nothing else:
HEARD: <the child's words, or - if there are none>
<TOY NAME>: <exactly what that toy says out loud>
Rules:
- One or two toy lines. Each line under 20 words. Simple words. Warm, playful, curious.
- If the child says a toy's name, THAT toy answers first. Otherwise the toy in [HEARD BY] answers first. Toys may talk to each other.
- After PENNY gives a wrong answer, the other toys must NOT say the right answer. They ask the child to help Penny instead, like "Hmm, is that right? Can you help Penny?"
- If a toy sees someone or a pet by name in [SCENE], use that name. "the child" means the child you are playing with.
- No emojis, no actions in asterisks, no lists, no stage directions.
- Never ask for personal information like addresses, schools or full names. Nothing scary.
- If the child sounds hurt, scared or sad, kindly suggest finding a grown-up.
- The toys cannot move. They only know what is in [SCENE] and what the child says."""


def clean(text: str) -> str:
    # Gemma sometimes echoes prompt labels into the spoken line ("HEARD BY PENNY: ...")
    text = re.sub(r"^\s*(\[?(HEARD BY|HEARD|SCENE|TOYS HERE|EVENT)\]?[^:]{0,20}:\s*)+", "", text, flags=re.I)
    text = re.sub(r"\*[^*]*\*|\([^)]*\)|\[[^\]]*\]", "", text)
    text = re.sub(r"[^\x20-\x7E’']", "", text)
    return " ".join(text.split()).strip(" \"'")


def parse(out: str, default: str, online=None) -> tuple[str, list[tuple[str, str]]]:
    heard, lines = "", []
    i = out.upper().rfind("HEARD:")      # skip any leaked reasoning/drafts before the final answer
    if i > 0:
        out = out[i:]
    by_name = {v: k for k, v in NAMES.items()}
    for raw in out.splitlines():
        m = LINE.match(raw)
        if not m:
            continue
        who, said = m.group(1).upper(), clean(m.group(2))
        if who == "HEARD":
            heard = said
        elif said:
            lines.append((by_name[who], said))
    if online is not None:
        lines = [l for l in lines if l[0] in online] or ([(default, lines[0][1])] if lines else [])
    if not lines and clean(out):
        lines = [(default, clean(LINE.sub(r"\2", out.splitlines()[-1])))]
    return heard, lines[: config.MAX_LINES]


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

    def start(self):
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
            u = arbitrate(u, self.utter_q)
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
                return f"{NAMES[t]} is looking at {seen[0]}. {NAMES[t]} says something playful to {seen[0]}, who answers."
        a, b = random.sample(online, 2)
        return f"Nobody has talked for a while. {NAMES[a]} and {NAMES[b]} chat about something fun to invite the child to play."

    def _turn(self, utt=None, event=None):
        self.busy = True
        t0 = time.time()
        tmp_files = []
        filler = None
        try:
            toy = utt.toy if utt else self.hub.online()[0]
            if utt:
                f = random.choice(canned.FILLERS.get(toy, ["Hmm!"]))
                filler = threading.Thread(target=self.hub.play, args=(toy, self.voices.render(toy, f)), daemon=True)
                filler.start()
            scene = self.eyes.scene_text()
            image = None
            v = self.eyes.views.get(toy)
            if v and v.jpeg and (config.VISION_MODE == "always" or (config.VISION_MODE == "sage" and toy == "sage")):
                image = self._tmp(v.jpeg, ".jpg")
                tmp_files.append(image)
            here = ", ".join(NAMES[t] for t in self.hub.online())
            prompt = f"[TOYS HERE] {here} (only these toys may speak)\n[SCENE] {scene}\n"
            wav = None
            said = ""
            if utt:
                wav = self._wav(utt.pcm)
                tmp_files.append(wav)
                prompt += f"[HEARD BY] {NAMES[toy]} (closest to the child).\n"
                if self.llm.hears_audio:
                    prompt += "The child just spoke (audio attached). Reply."
                else:
                    said = self.llm.transcribe(wav)
                    if re.sub(r"[^a-z ]", "", said.lower()).strip() in HALLUCINATIONS:
                        log.info("ignored non-speech (whisper: %r)", said)
                        return
                    prompt += f'The child said: "{said}"\nReply.'
            else:
                prompt += f"[EVENT] {event}"
            log.info("→ gemma: %s", prompt.replace("\n", " | "))
            out = self.llm.ask(prompt, wav=wav if self.llm.hears_audio else None, image=image)
            heard, lines = parse(out, default=toy, online=self.hub.online())
            # Penny's game: when the child asks her something, she answers (wrongly) ALONE so nobody
            # else spoils the child's chance to correct her. Gemma-only prompting leaked ~1/3 of the time.
            asked = (heard or (said if not self.llm.hears_audio else "")).lower()
            if "penny" in asked and lines and lines[0][0] == "penny":
                lines = lines[:1]
            self.last_latency = time.time() - t0
            log.info("← gemma (%.1fs): %s", self.last_latency, out.replace("\n", " | "))
            if heard and heard != "-":
                self.last_heard = heard
            for f in tmp_files:   # no audio/images kept once Gemma has them
                os.unlink(f)
            tmp_files = []
            if filler:
                filler.join()
            self.last_lines = lines
            for who, text in lines:
                if who in self.hub.online():
                    self.hub.play(who, self.voices.render(who, text))
        except Exception:  # noqa: BLE001
            log.exception("turn failed")
        finally:
            for f in tmp_files:
                try:
                    os.unlink(f)
                except OSError:
                    pass
            self._flush()
            self.busy = False
            self.last_activity = time.time()

    def _flush(self):
        """Drop speech captured while we were busy (it is usually toy echo or stale)."""
        while not self.utter_q.empty():
            self.utter_q.get_nowait()
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

    def run_canned(self):
        if self.paused:
            return
        self.paused = True
        log.info("canned scene start")
        try:
            for toy, text in canned.SCENE:
                if toy in self.hub.online():
                    self.hub.play(toy, self.voices.render(toy, text))
                    time.sleep(0.25)
        finally:
            self._flush()
            self.paused = False
            self.last_activity = time.time()
