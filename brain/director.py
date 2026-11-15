"""Turn-taking: utterance/event in -> Gemma -> one or two toy lines out."""
from __future__ import annotations

import collections
import logging
import os
import queue
import random
import re
import tempfile
import threading
import time
import wave

from . import camera, canned, config, convlog, curriculum, curriculum_picks, debugrec, factcheck, nonspeech, scripted, toytalk
from .choreo import plan_order
from .vad import arbitrate, normalize
from .latency import HostSampler, TurnLog, TurnTrace
from .metrics_live import Live   # conversation metrics + coaching (docs/metrics.md)
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
    facts_rule = ('- Facts, arithmetic and spellings must be exactly right for 2nd to 5th grade. Only say a fact, number or spelling you are '
                  'completely sure of; work every sum out before saying it. If unsure, a toy asks a question or says "Let\'s find out together!" '
                  'instead of guessing.' if config.STRICT_FACTS_PROMPT else
                  "- Facts, arithmetic and spellings must be accurate and right for 2nd to 5th grade. If unsure, say so and explore together.")
    look_rule = camera.prompt_rule()   # camera policy: off / one picture when the child asks / continuous
    stop_rule = ('FIRST: if the child tells the toys to stop, be quiet, hush or stop talking, your whole reply is the one word STOP '
                 '(then the HEARD line). Example: the child says "Stop talking please" -> you reply:\nSTOP\nHEARD: Stop talking please\n'
                 if config.CHILD_LEADS else "")
    child_rule = ('- THE CHILD LEADS. When the child speaks, the first toy answers exactly what the child said or asked, fully and kindly, '
                  'and the toys stay on the child\'s subject until the child changes it. A question gets ONE toy\'s real answer first; at most '
                  'one other toy adds a short line. Never change the subject away from the child. If the child asks about something in '
                  '[PRIVATE NOTES], answer from the notes like a friend who knows.'
                  if config.CHILD_LEADS else
                  "- If the child brings up something else (video games, TV, movies, anything), reply kindly in at most five words, then ask a "
                  "school, homework or learning-game question.")
    return f"""You are the voice director for three plush toy friends who play with {config.AUDIENCE}.
The toys:
{toys}
Each turn gives you [TOYS HERE] (the only toys that may speak this turn), [SCENE] (what each toy's camera sees right now) and either the child's speech (audio or text) or an [EVENT].
Reply ONLY in this exact format and nothing else. The toy lines come FIRST, the HEARD line LAST:
<TOY NAME>: <exactly what that toy says out loud>
HEARD: <the child's words, or - if there are none>
{stop_rule}Rules:
{child_rule}
- One to four toy lines; when the toys chat by themselves, usually let all three join in. The order is free and a toy may speak again after another toy (Dyno, Sage, Dyno, Penny), but never twice in a row. Toys react to the line before. If [ORDER] is given, write exactly one line per entry in exactly that order. Each line under 20 words. Words a 2nd to 5th grader knows. Warm, playful, curious.
- When the toys chat by themselves (an [EVENT]), or the child has no subject of their own, talk about these things:
{topics}
- If the child brings up something not right for a child (violence, scary or grown-up things), say kindly it is not a toy topic and offer something else.
- Never sing or recite song lyrics or movie lines.
{facts_rule}
- Penny is whimsical and silly through wordplay, playful comparisons and clearly marked make-believe. She gives careful answers and never makes deliberate factual or spelling mistakes.
- If the child says a toy's name, THAT toy answers first. Otherwise the toy in [HEARD BY] answers first. Toys may talk to each other.
- If a toy sees someone or a pet by name in [SCENE], use that name. "the child" means the child you are playing with.
- No emojis, no actions in asterisks, no lists, no stage directions.
- Never spell out noises: no "shh", "psst", "ahem", "achoo", "tsk", "hee hee", "zzz", "yawn", "ahem" or "sigh" as words. A toy that laughs, yawns or sighs writes [shhh], [giggle], [yawn] or [sigh] and the toy plays a real recording. Any other noise goes in brackets too, e.g. [psst]; a bracket with no recording is simply not played. Snoring is only for a toy that was put to sleep, never in chatter.
- HEARD holds only the child's words. Never write snoring, yawns, coughs, laughs, sighs or breathing there; if the child only made noises, write HEARD: - and do not react as if they spoke.
- Sound effects: a toy may put ONE sound tag at the start of a line, e.g. "DYNO: {{knock}} Who could be at the door?". Use them for stories, animals and fun moments, not every line. Available {sounds}
- Never ask for personal information like addresses, schools or full names. Nothing scary.
- If the child sounds hurt, scared or sad, the first toy says something kind AND suggests telling a grown-up they trust, like a parent or teacher. This rule beats every other rule.
{look_rule}- I spy: the toys guess only things that are really in an attached picture. With no picture, they ask for hints and never pretend to see.
- The toys cannot move. They only know what is in [SCENE] and what the child says."""


def just_said(lines, n: int = 2) -> str:
    """The last n toy lines of the previous turn as 'Name: "text"' (the pipeline hands lines on in chunks: a toy's chunks are joined;
    sound tags are dropped)."""
    merged: list[list] = []
    for who, text in lines or ():
        text = re.sub(r"\{[^}]*\}", "", text).strip()
        if not text:
            continue
        if merged and merged[-1][0] == who:
            merged[-1][1] += " " + text
        else:
            merged.append([who, text])
    return " ".join(f'{NAMES.get(w, w)}: "{t}"' for w, t in merged[-n:])


def line_jobs(names: list[str], start: int = 0, before: str | None = None) -> str:
    """One job per line of [ORDER], fixed by each toy's persona so the three stay distinct (jobs rotated by position blurred them, ledger
    s2-beats-tune): Dyno asks the next toy a NEW question, whoever follows a question answers it (Sage with a true fact, Penny playfully),
    otherwise Sage adds a fact and Penny reacts with wordplay. `start` = lines already said in this chat (0: the first line opens the topic);
    `before` = the name of the toy who spoke the last line of the previous round."""
    by = {v: k for k, v in NAMES.items()}
    out = []
    for i, n in enumerate(names):
        toy, first = by.get(n.upper()), start == 0 and i == 0
        prev = names[i - 1] if i else before
        asked = prev is not None and by.get(prev.upper()) == "dyno" and not first
        nxt = names[i + 1] if i + 1 < len(names) else None
        if toy == "dyno":
            out.append(f"{n} asks {nxt + ' ' if nxt and nxt != n else ''}one short, curious question about the topic that nobody has asked yet.")
        elif toy == "sage":
            out.append(f"{n} answers {prev}'s question with one true, specific fact." if asked else
                       f"{n} {'opens with' if first else 'adds'} one new, true, specific fact about the topic.")
        else:
            out.append(f"{n} answers {prev}'s question playfully, with wordplay or a silly, friendly comparison (nothing spooky)." if asked else
                       f"{n} {'opens the topic' if first else 'reacts to the line before'} with wordplay or a silly, friendly comparison (nothing spooky), without a question.")
    return " ".join(f"{i + 1}. {j}" for i, j in enumerate(out))


def clean(text: str) -> str:
    # Gemma sometimes echoes prompt labels into the spoken line ("HEARD BY PENNY: ...")
    text = re.sub(r"^\s*(\[?(HEARD BY|HEARD|SCENE|TOYS HERE|EVENT)\]?[^:]{0,20}:\s*)+", "", text, flags=re.I)
    text = re.sub(r"\b(?:SECRET|SEEN|CLUE)\s*:.*$", "", text)   # I spy's hidden notes are never spoken (ISpyReferee takes them off the front)
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

    def __init__(self, online, on_line, on_heard, guard: "factcheck.FactGuard | None" = None, ispy: "camera.ISpyReferee | None" = None,
                 max_lines: int | None = None):
        self.online, self.on_line, self.on_heard = set(online), on_line, on_heard
        self._max_lines = max_lines   # the child spoke: CHILD_MAX_LINES (one answer + one short add-on); else config.MAX_LINES
        self.ispy = ispy          # an I spy turn: the one toy line is held until HEARD, then the referee checks it against the picture
        self.ispy_line: tuple[str, str] | None = None
        # the fact guard checks every piece before it is spoken (wrong sums, letter counts, spellings, ... are fixed or dropped)
        self.guard = guard if guard is not None else (factcheck.FactGuard() if config.FACT_GUARD else None)
        self.line_so_far = ""   # what has been spoken of the line in progress (after fixes): claims can straddle a clause cut
        self.buffer = ""
        self.header, self.closed, self.in_thought, self.count = False, False, False, 0
        self.by_name = {value: key for key, value in NAMES.items()}
        self.pieces = 0   # chunks handed to TTS so far in this reply
        self.cur, self.spoken = None, 0   # (toy, allowed) of the line in progress; chars of it already spoken

    @property
    def max_lines(self) -> int:
        return self._max_lines or config.MAX_LINES

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
        if self.ispy or self.closed or self.in_thought or re.search(r"<(?:think|analysis)>", self.buffer, re.I):
            return
        match = LINE.match(self.buffer)
        if not match or match.group(1).upper() not in self.by_name:
            return
        rest = match.group(2)[self.spoken:]
        ends = list(self.SENTENCE_END.finditer(rest))
        if ends:
            cut = ends[-1].end()
        elif self.guard and factcheck.numbers(rest):
            cut = 0   # a sum or count must reach the fact guard whole: wait for the sentence end
        else:   # no sentence end yet: release a long clause so synthesis can start sooner
            need = self.CLAUSE_MIN_WORDS if self.pieces else self.FIRST_CLAUSE_MIN_WORDS
            cut = next((m.end() for m in self.CLAUSE_END.finditer(rest)
                        if len(rest[:m.end()].split()) >= need), 0)
        if cut:
            self._speak(self.by_name[match.group(1).upper()], rest[:cut])
            self.spoken += cut

    def _speak(self, toy, raw_text):
        if self.cur is None:   # first piece of a new toy line decides whether the line may play
            allowed = toy in self.online and self.count < self.max_lines
            self.count += allowed
            self.cur = (toy, allowed)
            self.line_so_far = ""
        text = clean(raw_text)
        if self.cur[1] and text and self.guard:
            text = self.guard.check(text, self.line_so_far)
            self.line_so_far = (self.line_so_far + " " + text).strip()
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
            self._release_ispy(text)
            if self.count:
                self.closed = True
            else:
                self.header = True
            return
        elif who in self.by_name and self.ispy:
            if self.ispy_line is None and self.by_name[who] in self.online:   # one guesser: the first toy line, held for the referee
                self.ispy_line = (self.by_name[who], text)
                self.count = 1
            self.cur = None
        elif who in self.by_name:
            # Speak the rest of the line now that it's complete (sentences already
            # spoken by _partial are skipped); no HEARD gate, which cost ~1-1.5 s.
            body = match.group(2)
            remainder = match.group(2)[spoken:]
            if text and (remainder.strip() or self.cur is None):
                self._speak(self.by_name[who], remainder if spoken else body)
            self.cur = None
            if self.count >= self.max_lines:
                self.closed = True
        else:
            self.cur = None

    def _release_ispy(self, heard: str = ""):
        if self.ispy and self.ispy_line and not self.closed:
            toy, line = self.ispy_line
            self.ispy_line = None
            self.cur, self.line_so_far = None, ""
            final = self.ispy.decide(line, heard if heard != "-" else "")
            self.cur = (toy, True)
            if self.guard:
                final = self.guard.check(final)
            if final:
                self.pieces += 1
                self.on_line(toy, final)
            self.cur = None
            self.closed = True

    def finish(self):
        if self.buffer:
            self._line(self.buffer)
            self.buffer = ""
        self._release_ispy()


class Director:
    def __init__(self, hub, voices, perceiver, backend, segmenters):
        self.hub, self.voices, self.eyes, self.llm, self.segs = hub, voices, perceiver, backend, segmenters
        self.utter_q: queue.Queue = queue.Queue()
        self.events: queue.Queue = queue.Queue()
        self.last_activity = time.time()
        self.last_child = time.time()   # last contact from a child (speech, tap, motion, someone seen); not the toys' own chatter
        self._quiet_s = random.uniform(*config.QUIET_AFTER_S)
        self.paused = False
        self.idle_on = config.IDLE_BANTER_S > 0
        self.busy = False
        self.last_heard = ""          # dashboard only; never written to disk
        self.last_lines: list = []
        self.last_latency = 0.0
        self._turn_lock = threading.Lock()
        self._gen = 0                              # bumped by interrupt(): the running reply is dropped
        self._barge_t = 0.0                        # wall time of the last barge-in: the child's words from then on survive _flush()
        self.cue_hold = threading.Event()          # set while a parent cue speaks: the reply waits at its next line boundary
        self._rotation = curriculum.Rotation()     # which grade topics were offered recently (rotates, no repeats)
        self.convlog = convlog.ConvLog()           # what was said, per turn, for review (RAM only)
        self._quiet_until = 0.0                    # the child said stop: no toy-to-toy chat until then
        self._last_child_t = 0.0                   # when the child last spoke (toy chats wait IDLE_AFTER_CHILD_S after it)
        self.turn_lines: list = []                 # lines handed to speech this turn (recorded even when the speakers are muted)
        self.last_look = None                      # the dashboard look: what the recogniser found + annotated frame (popped at once)
        self._ispy_until = 0.0                     # an I spy game is on until then (each turn of the game takes one picture)
        self._ispy_secret: str | None = None       # what a toy is spying (I spy, the toys' turn); kept in RAM for the game only
        self._ispy_guessed: list[str] = []         # things already guessed for the current clue (a "no" gets a new guess)
        self._ispy_clue: str | None = None         # the child's current clue (a color, or "my turn")
        self._ispy_seen: list[str] | None = None   # this turn's picture list
        self.fact_stats = {"fixed": 0, "dropped": 0}   # wrong facts the guard caught (counts only)
        self._scene_fact: str | None = None        # the verified curriculum summary for that subject ([TRUE FACTS])
        self._scene_topic: str | None = None       # SCENE_TOPIC: the one subject of the current toy-to-toy chat (None = no chat going)
        self._scene_line = 0                       # BEATS: lines of this chat so far (the line jobs continue across rounds)
        self._scene_last: str | None = None        # BEATS: who spoke the last line of the previous round
        self.parent = None                         # brain.parent.Parent, set by main (profiles, cues; None = feature off)
        self._notes_sent = ""                       # the notes block the toys' conversation currently contains
        self.imu = {}                              # toy -> {"asleep", "commented", "last"}: per-episode memory, RAM only
        self._reactions = collections.deque(maxlen=6)   # times of recent IMU reactions (rate limit)
        self._variant = {}                         # (toy, key) -> last variant used, so a repeat is not word for word
        self.active_trace = None
        self.last_trace = {}
        (config.DATA / "latency").mkdir(exist_ok=True)
        self.turn_log = TurnLog(config.DATA / "latency" / "turns.jsonl")
        self.sampler = HostSampler(hub)
        self.live = Live(get_parent=lambda: self.parent, toys_online=lambda: len(self.hub.online()),
                         noise=lambda: (sum(s.noise for s in self.segs.values()) / len(self.segs)) if self.segs else None)
        if hasattr(hub, "on_playback"):
            hub.on_playback = self._atom_playback

    def _atom_playback(self, toy, kind, when):
        """Atom-side timestamps (firmware 3.3+): the first sample the speaker clocks out, and the end of the clip."""
        self.live.playback(toy, kind, when)   # metrics: when a toy sound starts/ends (brain clock)
        t = self.active_trace
        if not t or getattr(self.hub, "talking", toy) != toy:   # a toy's own flash clip (IMU yell) is not part of this turn
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

    def child_contact(self):
        """Any sign of a child resets the clock, with a new random length so the toys do not go quiet on a fixed beat."""
        self.last_child = time.time()
        self._quiet_s = random.uniform(*config.QUIET_AFTER_S)

    def is_quiet(self) -> bool:
        """True once nobody has interacted for a while: the toys stop idle chatter (and, by the same clock, any sound)."""
        return time.time() - self.last_child > self._quiet_s

    # ---------- inputs ----------
    def on_seen(self, toy, thing):
        self.child_contact()
        self.events.put(f"{NAMES[toy]} just noticed {thing.label}. {NAMES[toy]} greets them warmly by name in one short line.")

    def on_button(self, toy, kind):
        self.child_contact()
        self.live.activation()   # metrics: a tap is an activation of the toy
        if kind == "hold":
            threading.Thread(target=self.run_canned, daemon=True).start()
        else:
            self.events.put(f"{NAMES[toy]} was gently tapped. {NAMES[toy]} says hello to the child.")

    # ---------- scripted lines: IMU reactions and parent cues ----------
    def child_speaking(self) -> bool:
        return any(getattr(seg, "active", False) for seg in self.segs.values())

    def _pick(self, toy, key, variants):
        """A variant of a line, not the one used last time for this (toy, key)."""
        last = self._variant.get((toy, key))
        options = [v for v in variants if v != last] or list(variants)
        choice = random.choice(options)
        self._variant[(toy, key)] = choice
        return choice

    def play_scripted(self, lines, wait_s: float = 4.0) -> bool:
        """Play fixed (toy, text) lines from the TTS cache as a short turn. Never over a child or another turn: waits up
        to wait_s for a free floor and then drops the lines (a late reaction is worse than none)."""
        deadline = time.time() + wait_s
        while True:
            if self.paused:
                return False
            if not self.child_speaking() and self._turn_lock.acquire(blocking=False):
                break
            if time.time() >= deadline:
                return False
            time.sleep(0.1)
        gen = self._gen
        self.busy = True
        self.hub.response_active.set()
        try:
            for toy, text in lines:
                if self._gen != gen or toy not in self.hub.online():
                    continue
                pcm = self.voices.render(toy, text, persist=True)
                if pcm:
                    self.hub.play(toy, pcm)
            return True
        except Exception:  # noqa: BLE001
            log.exception("scripted lines failed")
            return False
        finally:
            self.hub.response_active.clear()
            self.busy = False
            self.last_activity = time.time()
            self._turn_lock.release()

    def on_imu(self, toy, event, force: bool = False):
        """'IMU <event>' from a toy (firmware 3.5+). The moved toy already made its own sound from flash; here the other
        toys react once, in character, from cached lines (no Gemma wait). Dropped, not queued, when the floor is busy."""
        if event not in scripted.IMU_EVENTS or toy not in config.TOYS:
            return
        if event != "sleep":   # laying a toy down is going to bed, not play
            self.child_contact()
            self.live.activation()   # metrics: motion is an activation of the toy
        now = time.time()
        st = self.imu.setdefault(toy, {"asleep": False, "since": 0.0, "commented": set(), "last": {}})
        if st["asleep"] and now - st["since"] > 1800:
            st["asleep"] = False   # a lost wake-up must not silence every later sleep reaction
        if event == "sleep":
            if st["asleep"]:
                return
            st["asleep"], st["since"], st["commented"] = True, now, set()
        elif event == "woken":
            was, st["asleep"] = st["asleep"], False   # cleared first: rate limits below must never leave it stuck
            if not was:
                return
        if not force and now - st["last"].get(event, 0) < 5:
            return
        st["last"][event] = now
        if self.paused:
            return
        while self._reactions and now - self._reactions[0] > 60:
            self._reactions.popleft()
        if not force and (len(self._reactions) >= 4 or (self._reactions and now - self._reactions[-1] < 5)):
            return   # a flurry (a child tossing a toy over and over) must not become a chorus
        friends = [t for t in self.hub.online() if t != toy]
        if event == "woken":   # nobody comments more than once per sleep episode
            friends = [t for t in friends if t not in st["commented"]]
        if not friends:
            if event == "woken":
                st["asleep"] = False
            return
        count = min(scripted.IMU_FRIEND_COUNT.get(event, 1), len(friends))
        chosen = random.sample(friends, count)
        name = config.TOYS[toy]["name"]
        lines = [(f, self._pick(f, event, scripted.IMU_FRIENDS[event][f]).format(name=name)) for f in chosen]
        if event == "sleep":
            st["commented"].update(chosen)
        if event == "woken":
            st["asleep"] = False
        self._reactions.append(now)
        log.info("imu: %s %s -> %d friend line(s)", toy, event, len(lines))
        wait = 0.0 if force else self._local_clip_s(toy, event)
        threading.Thread(target=self._react_later, args=(lines, wait), daemon=True, name="imu-react").start()

    def _local_clip_s(self, toy, event) -> float:
        """How long the moved toy's own clip (its yell, its first snore) will take, so the friends speak after it, not over it."""
        atom = getattr(self.hub, "atoms", {}).get(toy)
        if atom is None:
            return 0.0
        return min(5.0, float(atom.clips.get(f"imu_{event}", 2.0)) + 0.4)

    def _react_later(self, lines, wait):
        time.sleep(wait)
        self.play_scripted(lines)

    def _wait_cue(self):
        while self.cue_hold.is_set():
            time.sleep(0.05)

    def _remember(self, said: str):
        """Keep what the child just told the toys (facts only, encrypted in the parent's store, never logged)."""
        if self.parent:
            try:
                self.parent.remember(said)
            except Exception:  # noqa: BLE001 — remembering must never break a turn
                log.warning("could not remember what the child said")

    def barge_in(self, toy: str):
        """The child started talking over a toy: stop every toy and drop the rest of the running reply."""
        self.child_contact()
        self.live.barge()   # metrics: the child talked over a toy
        self._barge_t = time.time()   # the child's utterance (already being heard) must outlive the cancelled turn's _flush()
        self.interrupt()

    def interrupt(self):
        """Parent's 'stop everything now': cut every toy's speech and drop the rest of the running reply."""
        self._gen += 1
        self.hub.stop_all()

    def cue(self, text: str = "", cue_id: str | None = None, urgent: bool = False) -> dict:
        """The parent's 'Say it now'. The parent supplies the meaning, the toys supply the reaction: a known cue plays fixed
        in-character lines at once, anything else is interpreted by Gemma. Ephemeral: nothing is stored or logged
        (not even the text), and nothing is queued for later if no toy is online."""
        self.child_contact()
        online = self.hub.online()
        if not online:
            return {"ok": False, "reason": "No toy is online right now."}
        cue_id = cue_id if cue_id in scripted.CUES else scripted.match_cue(text)
        if cue_id:
            order = random.sample(online, len(online))
            lines = [(t, self._pick(t, "cue-" + cue_id, scripted.CUES[cue_id]["lines"][t])) for t in order]
            mode = "fixed"
        else:
            if not text.strip():
                return {"ok": False, "reason": "Nothing to say."}
            if not hasattr(self.llm, "complete"):
                return {"ok": False, "reason": "Interpreting free text needs Gemma; pick one of the chips instead."}
            lines, mode = None, "gemma"
        threading.Thread(target=self._run_cue, args=(lines, text, online, urgent), daemon=True, name="cue").start()
        return {"ok": True, "mode": mode, "cue": cue_id}

    def _run_cue(self, lines, text, online, urgent):
        try:
            persist = lines is not None   # fixed chip lines are cached on disk; a typed cue's lines are never written anywhere
            if lines is None:
                lines = self._interpret_cue(text, online)
                if not lines:
                    return
            if urgent:
                self.interrupt()
                got = self._turn_lock.acquire(timeout=3)   # release only a lock we hold: the running turn releases its own
                try:
                    self.cue_hold.clear()
                    self._play_cue_lines(lines, persist)
                finally:
                    if got:
                        self._turn_lock.release()
                return
            self.cue_hold.set()   # a reply in progress pauses at its next line boundary, then resumes
            try:
                self._play_cue_lines(lines, persist)
            finally:
                self.cue_hold.clear()
        except Exception:  # noqa: BLE001
            log.exception("cue failed")
            self.cue_hold.clear()

    def _play_cue_lines(self, lines, persist=True):
        self.hub.response_active.set()
        try:
            for toy, line in lines:
                if toy in self.hub.online():
                    pcm = self.voices.render(toy, line, persist=persist)
                    if pcm:
                        self.hub.play(toy, pcm)
        finally:
            self.hub.response_active.clear()
            self.last_activity = time.time()

    def _interpret_cue(self, text, online):
        names = ", ".join(NAMES[t] for t in online)
        prompt = (f"A grown-up wants the toys to react to this moment. Do NOT repeat it word for word and do NOT say who "
                  f"said it. Write exactly one short line (under 16 words) for each of: {names}. Each toy reacts in "
                  f"character, warmly, as if it simply noticed. Do not quiz the child, do not invent details beyond the "
                  f"moment, nothing scary.\nMoment: {clean(text)[:200]}\nFormat: <TOY NAME>: <line>")
        try:
            out = self.llm.complete(prompt, system=system_prompt())
        except Exception:  # noqa: BLE001
            log.warning("cue interpretation failed")
            return None
        _, got = parse(out, default=online[0], online=online)
        lines = []
        for toy, line in got:
            lines.append((toy, scripted.SAFE_DEFLECT[toy] if scripted.leaks_note(line) else line))
        return lines or None

    # ---------- loop ----------
    def _loop(self):
        while True:
            try:
                u = self.utter_q.get(timeout=0.5)
            except queue.Empty:
                self.live.tick()   # metrics: close a session that has been idle too long
                self._maybe_event()
                continue
            if self.paused:
                continue
            u = arbitrate(u, self.utter_q, expected_toys=self.hub.online())
            self._barge_t = 0.0   # the interrupting words are being answered now
            u.arbitrated = time.monotonic()
            self.child_contact()
            log.info("utterance: %s %.1fs rms=%.0f", u.toy, len(u.pcm) / config.SAMPLE_RATE, u.rms)
            self._turn(utt=u)

    def _maybe_event(self):
        if self.paused or self.busy or not self.hub.online():
            return
        try:
            ev = self.events.get_nowait()
        except queue.Empty:
            ev = None
            now = time.time()
            if (self.idle_on and not self.is_quiet() and now - self.last_activity > self.live.idle_banter_s(config.IDLE_BANTER_S)
                    and now >= self._quiet_until and now - self._last_child_t > (config.IDLE_AFTER_CHILD_S if config.CHILD_LEADS else 0)
                    and len(self.hub.online()) >= 2):
                ev = self._idle_event()
        if ev:
            self._turn(event=ev)

    def _grade_topics(self) -> str:
        """[GRADE TOPICS] for the bound child's grade (default grade when unknown); '' if the curriculum fails: it must never break a turn."""
        try:
            grade, boost, skip = curriculum_picks.context_for_bound_child(self.parent)
            return curriculum.topics_block(grade, self._rotation, boost, skip)
        except Exception:   # noqa: BLE001
            log.exception("grade topics failed")
            return ""

    def _banter_seed(self) -> str:
        """Idle banter draws its topic from the grade's curriculum; falls back to the fixed seeds if the data is missing."""
        self._scene_fact = None
        try:
            grade, boost, skip = curriculum_picks.context_for_bound_child(self.parent)
            item = curriculum.banter_item(grade, self._rotation, boost, skip)
            seed = item["title"].lower() if item else None
            self._scene_fact = (item or {}).get("summary") or None   # the curriculum's verified summary: the facts this chat may use
        except Exception:   # noqa: BLE001
            seed = None
        return seed or random.choice(config.BANTER_SEEDS)

    def _idle_event(self) -> str:
        ev = self._idle_event_base()
        return f"{ev} {toytalk.block(config.TOY_TALK)}".rstrip() if config.TOY_TALK else ev

    def _idle_event_base(self) -> str:
        online = self.hub.online()
        for t in online:
            v = self.eyes.views[t]
            seen = [x.label for x in v.things if x.kind == "toy"]
            if seen:
                seed = self._scene_topic = self._banter_seed()
                self._scene_line, self._scene_last = 0, None
                return f"{NAMES[t]} is looking at {seen[0]}. {NAMES[t]} asks {seen[0]} something about {seed}, who answers."
        seed = self._scene_topic = self._banter_seed()
        self._scene_line, self._scene_last = 0, None
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
        self.live.turn_open(initiated=utt is None)   # metrics: a toy-initiated turn is a cue; a reply may become one
        if utt:
            self.live.child_pending(utt)
            self._last_child_t = time.time()
        gen = self._gen
        prev_lines = self.last_lines                # what the toys said last turn (JUST_SAID quotes it in a continuing chat)
        self.last_latency, self.last_lines, self.turn_lines = 0., [], []
        tmp_files = []
        filler = None
        pipeline = None
        status = "ok"
        tl = {"heard": "", "flags": {}, "kind": "child" if utt else ("look" if isinstance(event, dict) and event.get("look") else "toys")}
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
            exclude = set(event.get("exclude", ())) if isinstance(event, dict) else set()
            speakers = [t for t in online if t not in exclude] or online
            asked_look = event.get("look") if isinstance(event, dict) else None   # the dashboard's "what do you see?"
            if asked_look in online:
                toy, speakers = asked_look, [asked_look]
            event_text = event["text"] if isinstance(event, dict) else event
            here = ", ".join(NAMES[t] for t in speakers)
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
                    if not said.strip() or re.sub(r"[^a-z ]", "", said.lower()).strip() in HALLUCINATIONS:
                        log.info("ignored non-speech")
                        status = "ignored_non_speech"
                        return
                    self.last_heard = said
                    tl["heard"] = said
                    self._remember(said)
                    self.live.child_text(said)   # metrics: reduced to numbers/tags at once, the words are not kept
                    prompt += f'The child said: "{said}"\nReply.'
            else:
                prompt += f"[EVENT] {event_text}"
            # Camera policy (brain/camera.py). With a transcript (whisper path) the rules decide here, so the picture goes with the
            # first call. The audio-native model has no transcript yet: it answers LOOK and the loop below takes the picture.
            looks = self._can_look(toy)
            stop_now = bool(said and config.CHILD_LEADS and camera.wants_stop(said))
            if asked_look and config.LOOK_ON_REQUEST and self._has_cam(toy):
                prompt, image = self._look_turn(toy, prompt, scene, "What do you see right now?", image, tmp_files, trace)
            if said and camera.ispy_stop(said):
                self._ispy_until = 0.0
            ispy = bool(utt) and config.ISPY and (self._ispy_on() or bool(said and camera.wants_ispy(said)))
            self._ispy_seen = None     # set by this turn's picture-list call (I spy turns only)
            if ispy and (looks or config.CAPTURE_CONTINUOUS) and toy in speakers:
                # one guesser per turn: with all three toys talking, the others guessed things not in the picture or spied on their own
                prompt = prompt.replace(f"[TOYS HERE] {here} ", f"[TOYS HERE] {NAMES[toy]} ", 1)
                speakers = [toy]
            if ispy and looks:
                # I spy: every turn of the game takes ONE picture from the toy that heard the child; guesses come only from it
                self._ispy_until = time.time() + config.ISPY_GAME_S
                prompt, image = self._look_turn(toy, prompt, scene, said or None, image, tmp_files, trace, game="ispy")
            elif ispy and config.CAPTURE_CONTINUOUS and v and v.jpeg and 0 <= time.time() - v.ts <= config.VISION_MAX_AGE_S:
                self._ispy_until = time.time() + config.ISPY_GAME_S       # continuous cameras: play on the latest frame
                if not image:
                    image = self._tmp(v.jpeg, ".jpg")
                    tmp_files.append(image)
                self._ispy_seen = self._list_seen(image, trace)
                prompt = prompt.replace("[SCENE] " + scene, camera.ispy_prompt(NAMES[toy], v.describe() if v.things else "", True, said or None,
                                                                               self._ispy_secret, self._ispy_seen), 1)
            elif said and looks and camera.wants_look(said):
                prompt, image = self._look_turn(toy, prompt, scene, said, image, tmp_files, trace)
            log.info("→ gemma: %s", prompt.replace("\n", " | "))
            notes = ((self.parent.notes_block() + "\n" + getattr(self.parent, "told_block", lambda: "")()).strip() if self.parent else "")   # added AFTER the log line: notes are never logged
            notes = (notes + "\n" + (self.live.coaching_block() or "")).strip()   # [COACHING] block (brain/coaching.py); '' when neutral/off
            if notes != self._notes_sent:
                # the notes changed (another child, an item deleted, notes paused, locked): the toys' conversation still holds
                # the old ones, so start it afresh. Deleting a note must really stop the toys using it.
                reset = getattr(self.llm, "reset_conversation", None)
                if reset and (self._notes_sent or notes):
                    reset()
                self._notes_sent = notes
            if utt:
                self._scene_topic = None     # the child spoke: their subject leads now; the next idle chat picks a new topic
            if config.SCENE_TOPIC and not utt and not asked_look and self._scene_topic:
                # a toy-to-toy chat keeps ONE subject: no fresh rotating curriculum items each turn (they made rounds 2-3 jump topics)
                # (wording with no phrase a toy could speak: "stay on it!" was copied into lines verbatim)
                topics = (f"[TOPIC] {self._scene_topic}\n[TOPIC RULE] Every line this turn is about the topic above and no other subject. "
                          "Each line adds something new and concrete about it: a real example, word, number or fact. No line repeats an earlier one.")
                if config.TRUE_FACTS and self._scene_fact:
                    # the verified curriculum card: facts come from here, so a 2B model has something true to say instead of guessing
                    topics += (f"\n[TRUE FACTS] {self._scene_fact}\n[FACT RULE] Facts and numbers come from [TRUE FACTS] or are basic facts "
                               "you are completely sure of. Never guess a number, date, name or spelling.")
                said = just_said(prev_lines) if config.JUST_SAID else ""
                if said:
                    # the last lines quoted: a 2B model follows a quoted line far better than its memory of the previous turn
                    topics += (f"\n[JUST SAID] {said}\n[REPLY RULE] The first toy line answers or builds on the last line just said, "
                               "and each line after builds on the line before it.")
                order = re.search(r"\[ORDER\] ([A-Za-z, ]+)\.", event_text or "")
                if config.BEATS and order:
                    # each line gets a job (ask -> answer -> playful reaction), continuing across rounds, so lines answer each other
                    names = [n.strip() for n in order.group(1).split(",") if n.strip()]
                    topics += "\n[LINE JOBS] " + line_jobs(names, self._scene_line, self._scene_last)
                    self._scene_line += len(names)
                    self._scene_last = names[-1] if names else None
            elif utt and config.CHILD_LEADS:
                topics = ""                      # the child leads: no curriculum items pulling the reply away from what they said
            else:
                topics = self._grade_topics()    # curriculum: a short rotating [GRADE TOPICS] block right after the notes; not logged, not a quiz
            prompt = "".join(b + "\n" for b in (notes, topics) if b) + prompt

            def dispatched(who, text):
                self.live.toy_line(text)   # metrics: question/invite flags only
                self.last_lines.append((who, text))
                self.last_latency = trace.snapshot()["milestones_ms"]["first_audio_post_ms"] / 1000

            pipeline = SpeechPipeline(self.hub, self.voices, trace, dispatched,
                                      before_play=filler.join if filler else None,
                                      cancelled=lambda: self._gen != gen, gate=self._wait_cue)
            deflected = []

            def line_ready(who, text):
                if self._gen != gen:
                    return
                self.turn_lines.append((who, text))
                if scripted.leaks_note(text):   # a toy must never reveal that a parent wrote anything: play something safe, once
                    if deflected:
                        return
                    deflected.append(who)
                    text = scripted.SAFE_DEFLECT[who]
                trace.mark("first_line_ready_ms")
                pipeline.submit(who, text)

            def heard(text):
                text = nonspeech.clean(text) if text and text != "-" else ""   # words only; "[snoring]" etc. are not speech
                if text and utt and config.ISPY and (looks or config.CAPTURE_CONTINUOUS):
                    # audio-native model: the words arrive only now. A child who started I spy keeps the game (and its pictures) on
                    if camera.ispy_stop(text):
                        self._ispy_until = 0.0
                    elif camera.wants_ispy(text):
                        self._ispy_until = time.time() + config.ISPY_GAME_S
                if text and utt and config.CHILD_LEADS and camera.wants_stop(text) and not tl["flags"].get("stop"):
                    # the audio-native model wrote toy lines instead of STOP (it hears the child, the words come last): cut what is
                    # queued now, then one "I'm listening" after the turn, and quiet
                    tl["flags"]["stop"], tl["ack"] = True, toy
                    self._quiet(toy)
                    self.interrupt()
                if text:
                    self.last_heard = text
                    tl["heard"] = text
                    self._remember(text)
                    self.live.child_text(text)   # audio-mode models report the words here (no-op once STT supplied them)

            # context for the fact guard: a question asked at the end of the last turn (or by the child) is answered now
            guard = factcheck.FactGuard(context=[t for _w, t in prev_lines[-1:]] + [said]) if config.FACT_GUARD else None
            referee = (camera.ISpyReferee(said, self._ispy_seen, self._ispy_secret, self._ispy_guessed, self._ispy_clue)
                       if ispy and self._ispy_seen is not None else None)
            parser = ReplyLines(speakers, line_ready, heard, guard, referee,
                                max_lines=config.CHILD_MAX_LINES if utt and config.CHILD_LEADS else None)
            kwargs = dict(wav=wav if self.llm.hears_audio else None, image=image)
            stream = getattr(self.llm, "stream", None)
            words = ((camera.LOOK_WORD,) if looks else ()) + ((camera.STOP_WORD,) if config.CHILD_LEADS else ())
            peel = camera.LookPeeler(words) if words and utt and not image else None   # round 0 may be the one-word LOOK / STOP
            if stop_now:      # transcript said stop: no model call at all, just "I'm listening" and quiet
                tl["flags"]["stop"] = True
                self._quiet(toy)
                line_ready(toy, canned.LISTENING.get(toy, "Okay, I'm listening."))
                parser.count = 1
            with trace.span("llm_ms"):
                for round_ in ((0, 1) if not stop_now else ()):
                    chunks = stream(prompt, **kwargs) if stream else iter([self.llm.ask(prompt, **kwargs)])
                    try:
                        for delta in chunks:
                            if self._gen != gen:
                                break
                            if peel:
                                delta = peel.feed(delta)
                            if delta:
                                trace.mark("first_model_text_ms")
                                parser.feed(delta)
                        if peel:
                            parser.feed(peel.finish())
                    finally:
                        close = getattr(chunks, "close", None)
                        if close:
                            close()
                    if peel and peel.looking and peel.word == camera.STOP_WORD and self._gen == gen:
                        # the child said stop: one short "I'm listening", then quiet (no toy-to-toy chat for STOP_QUIET_S)
                        tl["flags"]["stop"] = True
                        if peel.heard:
                            heard(peel.heard)
                        self._quiet(toy)
                        line_ready(toy, canned.LISTENING.get(toy, "Okay, I'm listening."))
                        parser.count = 1
                        break
                    if not (peel and peel.looking and round_ == 0 and self._gen == gen):
                        break
                    # The child asked the toy to look: one picture from the toy that heard them, camera off again, same turn.
                    if peel.heard:
                        heard(peel.heard)
                    prompt, image = self._look_turn(toy, prompt, scene, None, None, tmp_files, trace, replace=False)
                    kwargs, peel = dict(wav=None, image=image), None
                parser.finish()
            trace.mark("model_done_ms")
            if referee:
                self._ispy_secret, self._ispy_guessed, self._ispy_clue = referee.secret, referee.guessed, referee.clue
            tl["flags"].update(ispy=bool(ispy), look=bool(image) and not ispy, fact_fixed=guard.fixed if guard else 0,
                               fact_dropped=guard.dropped if guard else 0)
            if guard and (guard.fixed or guard.dropped):
                self.fact_stats["fixed"] += guard.fixed
                self.fact_stats["dropped"] += guard.dropped
                log.info("fact guard: fixed %d, dropped %d", guard.fixed, guard.dropped)   # counts only, never the words
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
            if tl.get("ack"):
                try:
                    ack = canned.LISTENING.get(tl["ack"], "Okay, I'm listening.")
                    self.hub.play_line(tl["ack"], ack, self.voices)
                    self.turn_lines.append((tl["ack"], ack))
                except Exception:  # noqa: BLE001
                    log.warning("listening line failed")
            for f in tmp_files:
                try:
                    os.unlink(f)
                except OSError:
                    pass
            self._flush()
            self.hub.response_active.clear()
            self.busy = False
            self.last_activity = time.time()
            self.live.child_unresolved(status)   # metrics: count the utterance's timing even if no words were reported
            self.live.turn_close(status)
            trace.finish(status)
            try:   # the conversation log for review (RAM only, brain/convlog.py)
                if status != "ignored_non_speech":
                    self.convlog.add(kind=tl["kind"], heard_by=utt.toy if utt else None, heard=tl["heard"], said=self.turn_lines,
                                     status=status, latency_s=round(self.last_latency, 2) if self.last_latency else None, flags=tl["flags"])
            except Exception:  # noqa: BLE001
                log.warning("conversation log failed")
            self.last_trace = self.turn_log.add(dict(trace.snapshot(), host=self.sampler.latest(),
                                                    floor=getattr(self.hub, "floor", None) and self.hub.floor.snapshot()))
            self.active_trace = None
            self._turn_lock.release()
            log.info("latency: %s", self.last_trace)
            getattr(self.llm, "maybe_warm", lambda: None)()

    def _flush(self):
        """Drop speech captured while we were busy (it is usually toy echo or stale), except what the child said after
        cutting the toy off (barge-in): that is the next turn."""
        t = self._barge_t
        keep = []
        while True:
            try:
                u = self.utter_q.get_nowait()
            except queue.Empty:
                break
            if t and u.end >= t:
                keep.append(u)
        for u in keep:
            self.utter_q.put(u)
        for s in self.segs.values():
            if not (t and getattr(s, "active", False)):   # the child is still mid-sentence: let the segmenter finish it
                s.reset()

    # ---------- helpers ----------
    # ---------- camera policy: look on request ----------
    def _has_cam(self, toy) -> bool:
        a = getattr(self.hub, "atoms", {}).get(toy)
        return hasattr(self.eyes, "snap") and bool(a and getattr(a, "cam", False))

    def set_camera_mode(self, mode: str) -> str:
        """Dashboard switch: off / request / always. The system prompt's camera rule changes with it, so the toys' conversation
        starts afresh with the new prompt; an I spy game ends; 'off' and 'request' forget every frame."""
        config.set_camera_mode(mode)
        getattr(self.eyes, "apply_mode", lambda: None)()
        self._ispy_until = 0.0
        self._ispy_on()
        if hasattr(self.llm, "system"):
            self.llm.system = system_prompt()
        reset = getattr(self.llm, "reset_conversation", None)
        if reset:
            reset()
        log.info("camera mode: %s", mode)
        return mode

    def look_now(self, toy: str, timeout: float = 45.0) -> dict:
        """The dashboard's "what do you see?": ONE picture from `toy`, Gemma says what is in it (and who: enrolled faces are named by
        the recogniser). Returns what the toy said, what the recogniser found and the annotated frame (RAM only, not kept)."""
        if not config.LOOK_ON_REQUEST:
            return {"error": "the cameras are off"}
        if toy not in self.hub.online() or not self._has_cam(toy):
            return {"error": f"{NAMES.get(toy, toy)} is offline or has no camera"}
        if self.busy:
            return {"error": "the toys are busy, try again in a moment"}
        self.last_look = None
        name = NAMES[toy]
        done = threading.Event()

        def run():
            try:
                self._turn(event={"text": f"A grown-up asked {name} what it sees right now. {name} answers from the picture in one or two "
                                          f"short lines, naming anyone it recognises.", "look": toy})
            finally:
                done.set()
        threading.Thread(target=run, daemon=True, name="look-now").start()
        done.wait(timeout)
        look, self.last_look = self.last_look or {}, None
        return {"toy": toy, "said": " ".join(t for w, t in self.turn_lines if w == toy), "seen": look.get("seen", []),
                "frame": look.get("frame"), "picture": bool(look)}

    def _can_look(self, toy) -> bool:
        """On-request looking is on (default), this toy has a camera and the perceiver can take a picture."""
        a = getattr(self.hub, "atoms", {}).get(toy)
        return (not config.CAPTURE_CONTINUOUS and hasattr(self.eyes, "snap") and bool(a and getattr(a, "cam", False))
                and config.LOOK_ON_REQUEST)

    def _vision_model(self):
        if not hasattr(self, "_vm"):
            try:
                from .vision_model import make_vision
                self._vm = make_vision(getattr(config, "VISION_MODEL", "gemma"))
            except Exception:  # noqa: BLE001
                self._vm = None
        return self._vm

    def _list_seen(self, image, trace) -> list[str] | None:
        """I spy: one short picture-only call that lists what is in the picture with colors ('red apple, green leaf'); the referee
        holds the guesses to it. None when the call fails (then the line passes unchecked)."""
        with trace.span("ispy_list_ms"):
            try:
                complete = getattr(self.llm, "complete", None)
                if complete:   # its own throwaway conversation: in the toys' one, the toy-line format turned the list into banter
                    out = complete(camera.SEEN_PROMPT, camera.SEEN_SYSTEM, image=image, max_tokens=80)
                else:
                    stream = getattr(self.llm, "stream", None)
                    out = "".join(stream(camera.SEEN_PROMPT, wav=None, image=image)) if stream else self.llm.ask(camera.SEEN_PROMPT, image=image)
                return camera.parse_seen(out)
            except Exception:  # noqa: BLE001
                log.warning("I spy list call failed")
                return None

    def _quiet(self, toy=None):
        """The child said stop: cut whatever is playing, end a toy chat, no toy-to-toy chat for STOP_QUIET_S. The toys still answer
        the child whenever they speak."""
        self._quiet_until = time.time() + config.STOP_QUIET_S
        self._scene_topic = None
        log.info("child said stop: quiet for %.0f s", config.STOP_QUIET_S)

    def _ispy_on(self) -> bool:
        """An I spy game is going: the child started it and spoke again within ISPY_GAME_S."""
        on = time.time() < self._ispy_until
        if not on:
            self._ispy_secret, self._ispy_guessed, self._ispy_clue = None, [], None   # game over: forget what was spied and guessed
        return on

    def _look_turn(self, toy, prompt, scene, said, image, tmp_files, trace, replace=True, game=None):
        """Turn `toy`'s camera on for ONE picture, then off. Returns (prompt, image path) for the model call that answers it.
        replace=True swaps the [SCENE] line of an existing prompt for the [CAMERA] block (transcript path); replace=False
        returns just the [CAMERA] block (the model already holds the question as audio). The frame lives in a RAM temp file that
        the end of the turn deletes; the Perceiver forgets it immediately."""
        path, text, got = image, "", False
        with trace.span("look_ms"):
            try:
                view = self.eyes.snap(toy)
                if view is not None and view.jpeg:
                    path, got = self._tmp(view.jpeg, ".jpg"), True
                    tmp_files.append(path)
                    # the detector only knows faces, the toys, pets and books: when it found none, say nothing (its "sees nothing in
                    # particular" made Gemma answer "I don't see anything" about an apple in plain view); Gemma looks at the picture itself
                    text = view.describe() if view.things else ""
                    self.last_look = {"toy": toy, "seen": [t.label for t in view.things], "frame": view.annotated}   # RAM; the dashboard pops it
                    vm = self._vision_model()
                    if vm:   # optional separate vision-to-text model (SENTIENT_VISION_MODEL != gemma): its caption goes in as text
                        cap = vm.describe(view.jpeg, said or "")
                        if cap:
                            text += f' A vision model describes the picture as: "{cap}".'
            except Exception:  # noqa: BLE001 — a camera hiccup must never break the turn
                log.warning("look failed for %s", toy)
            finally:
                close = getattr(self.eyes, "close", None)
                if close:
                    close(toy)
        trace.mark("look_done_ms")
        if game == "ispy":
            self._ispy_seen = self._list_seen(path, trace) if got else None
            block = camera.ispy_prompt(NAMES[toy], text, got, said, self._ispy_secret, self._ispy_seen)
        else:
            block = camera.look_prompt(NAMES[toy], text, got, said)
        if replace:
            return prompt.replace("[SCENE] " + scene, block, 1), path
        return block, path

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
