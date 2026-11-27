"""Turn-taking: utterance/event in -> Gemma -> one or two toy lines out."""
from __future__ import annotations

import collections
import dataclasses
import difflib
import logging
import os
import queue
import random
import re
import tempfile
import threading
import time
import wave

import numpy as np

from . import voiceid
from . import camera, canned, config, convlog, curriculum, curriculum_picks, debugrec, factcheck, jokes, nonspeech, scripted, story, toytalk, warm
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
    format_rule = ("Reply ONLY in this exact format and nothing else. The HEARD line comes FIRST, then the toy lines:\n"
                   "HEARD: <the child's words, or - if there are none>\n<TOY NAME>: <exactly what that toy says out loud>"
                   if config.HEARD_FIRST else
                   "Reply ONLY in this exact format and nothing else. The toy lines come FIRST, the HEARD line LAST:\n"
                   "<TOY NAME>: <exactly what that toy says out loud>\nHEARD: <the child's words, or - if there are none>")
    stop_rule = ('FIRST: if the child tells the toys to stop, be quiet, hush or stop talking, your whole reply is the one word STOP '
                 '(then the HEARD line). Example: the child says "Stop talking please" -> you reply:\nSTOP\nHEARD: Stop talking please\n'
                 if config.CHILD_LEADS and not config.HEARD_FIRST else "")
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
{format_rule}
{stop_rule}Rules:
{child_rule}
- One to four toy lines; when the toys chat by themselves, usually let all three join in. The order is free and a toy may speak again after another toy (Dyno, Sage, Dyno, Penny), but never twice in a row. Toys react to the line before. If [ORDER] is given, write exactly one line per entry in exactly that order. Each line under 20 words. Words a 2nd to 5th grader knows. Warm, playful, curious.
- When the toys chat by themselves (an [EVENT]), or the child has no subject of their own, talk about these things:
{topics}
- If the child brings up something not right for a child (violence, scary or grown-up things), say kindly it is not a toy topic and offer something else.
- Never sing or recite song lyrics or movie lines.
{facts_rule}
- Penny is whimsical and silly through wordplay, playful comparisons and clearly marked make-believe. She gives careful answers and never makes deliberate factual or spelling mistakes.
- The toys know their names: Dyno, Sage and Penny. If the child says a toy's name, ONLY that toy answers; the others stay quiet. Otherwise the toy in [HEARD BY] answers first. Toys may talk to each other.
- If [SCENE] says a toy sees ITSELF, that toy says so happily ("Hey, that's me!").
- If a toy sees someone or a pet by name in [SCENE], use that name. "the child" means the child you are playing with.
- [SPEAKER] says who is talking when the toys know them by voice or face: talk to that person and use their name. If they ask who they are, tell them by that name.
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


RAW_DEBUG = os.environ.get("SENTIENT_DEBUG_RAW") == "1"
INLINE_NAME = re.compile(r"^\s*[*]*(" + "|".join(NAMES.values()) + r")\s*[*]*\s*:\s*[*]*\s*", re.I)
BY_NAME = {v.upper(): k for k, v in NAMES.items()}
INLINE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[*]*(?:" + "|".join(NAMES.values()) + r")\s*[*]*\s*:)", re.I)
LEAD_TAG = re.compile(r"^\s*\{([a-z_]+)\}\s*")
SOUND_ASKED = re.compile(r"\b(?:sounds?|noises?|roar|rawr|growl|honk|sing|song|loud|pretend|animal|make a|what does|how does)\b", re.I)


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
        self.heard_text: str | None = None   # the HEARD line, once seen
        # the fact guard checks every piece before it is spoken (wrong sums, letter counts, spellings, ... are fixed or dropped)
        self.guard = guard if guard is not None else (factcheck.FactGuard() if config.FACT_GUARD else None)
        self.line_so_far = ""   # what has been spoken of the line in progress (after fixes): claims can straddle a clause cut
        self.buffer = ""
        self.header, self.closed, self.in_thought, self.count = False, False, False, 0
        self.by_name = {value: key for key, value in NAMES.items()}
        self.pieces = 0   # chunks handed to TTS so far in this reply
        self.cur, self.spoken = None, 0   # (toy, allowed) of the line in progress; chars of it already spoken
        self.warm, self.child = None, None   # warm.Guard and a callable giving the child's words (set by the director on child turns)
        self.lead_sound = None    # callable(tag, child words) -> may this line open with that sound? (set by the director on child turns)

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
            if self.warm:
                self.warm.start()
        text = clean(raw_text)
        parts = INLINE_SPLIT.split(text)
        if len(parts) > 1:                # several toys' words in one piece: each part by itself
            for part in parts:
                self._speak(self.cur[0] if self.cur else toy, part)
            return
        m = INLINE_NAME.match(text)       # live Nov 27: "PENNY: Penny: C-A-T! Dyno: I like that word! Sage: ..." all in Penny's line and voice
        if m:
            who = BY_NAME[m.group(1).upper()]
            if who == toy:
                text = text[m.end():]
            else:                         # another toy's words: its own line (and its own turn at the line limit), never this toy's voice
                self.cur = None
                return self._speak(who, text[m.end():])
        if self.cur[1] and text and self.lead_sound and not self.line_so_far:   # a roar or honk before every answer is not how anyone talks
            m = LEAD_TAG.match(text)
            if m and not self.lead_sound(m.group(1), self.heard_text if self.heard_text not in (None, "-", "") else (self.child() if self.child else "")):
                text = text[m.end():]
        if self.cur[1] and text and self.warm:   # "I am a toy, so I cannot love like a person" is not how a bond question is met
            text = self.warm.piece(text, self.heard_text if self.heard_text not in (None, "-", "") else (self.child() if self.child else ""))
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
            # HEARD-first (config.HEARD_FIRST): the child's words arrive before any toy line, so the director can route the
            # turn (the named toy only, stop, the I spy clue). Answer-first: HEARD closes the reply (a second draft is never spoken).
            if self.heard_text is not None and self.count:
                self.closed = True
                return
            self.heard_text = text
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
                if self.heard_text is not None:                                 # HEARD came first: the clue is known now
                    self._release_ispy(self.heard_text)
            self.cur = None
        elif who in self.by_name:
            # Speak the rest of the line now that it's complete (sentences already
            # spoken by _partial are skipped); no HEARD gate, which cost ~1-1.5 s.
            body = match.group(2)
            remainder = match.group(2)[spoken:]
            if text and (remainder.strip() or self.cur is None):
                self._speak(self.by_name[who], remainder if spoken else body)
            if self.warm and self.cur and self.cur[1]:
                extra = self.warm.end()
                if extra:
                    self.pieces += 1
                    self.on_line(self.cur[0], extra)
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
        self._release_ispy(self.heard_text or "")


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
        self._story_until = 0.0                    # story mode (brain/story.py): the child reads, the toys only add sounds
        self._story_text: list[str] = []           # the story so far (RAM only), for one kind line at "the end"
        self._story_last: dict = {}                # sound -> when it last played (no bark on every sentence)
        self._story_n = 0
        self._story_q = None                       # story sounds waiting to play (one worker thread)
        self._story_qlock = threading.Lock()
        self._story_ears_log: list = []            # what the fast recogniser heard since the last sentence (for the log, RAM only)
        self._story_start_fast = 0.0               # when the fast recogniser last heard "I'm going to read you a story"
        self._ears_recent: collections.deque = collections.deque(maxlen=120)   # (time, toy, words) from the fast recogniser, RAM only
        self._cur_utt = None                       # the child's utterance being answered (not in story mode)
        self._jokes, self._joke_t = jokes.Teller(), 0.0   # the joke list, and when a toy last told one
        self._cont = None                          # (utterance, time): cut by the child going on before any line was spoken
        self._story_end_fast = 0.0                 # when the fast recogniser last heard "the end"
        self._story_fast_t = 0.0                   # when the fast recogniser last started a sound
        self._story_cur = None                     # (toy, since) while a story sound plays
        self._story_fast: list = []                # sounds the fast recogniser started since the last sentence (for the log)
        self._story_rms = 0.0                      # how loud the child's reading is at the toys (running average)
        self._story_sound_t = (0.0, 0.0)           # when the last story sound played (wall clock)
        self._last_child_t = 0.0                   # when the child last spoke (toy chats wait IDLE_AFTER_CHILD_S after it)
        self.turn_lines: list = []                 # lines handed to speech this turn (recorded even when the speakers are muted)
        self.last_look = None                      # the dashboard look: what the recogniser found + annotated frame (popped at once)
        self._since_sound = 99                     # child turns since a reply last opened with a recorded sound
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
        self.voiceid = None                        # brain.voiceid.VoiceID, set by main (who is talking, by voice)
        self._vox_cand: dict = {}                  # entry id -> voice prints waiting for agreement (RAM only, see _learn_voice)
        self._vox_t: dict = {}                     # entry id -> when a print was last learned (rate limit)
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
        if self._story_on() or config.CHILD_LEADS and (time.time() - self._last_child_t < config.IDLE_AFTER_CHILD_S or time.time() < self._quiet_until):
            return                           # the child is talking with the toys (or said stop): no greeting cutting in
        self.child_contact()
        if thing.label.startswith("itself"):
            n = NAMES[toy]
            self.events.put({"text": f"{n} just saw ITSELF, {n} ({config.TOYS[toy]['looks']}), in a mirror or a picture. {n} says happily "
                                     f"that it is {n}, e.g. \"Hey, that's me, {n}!\". One short line.",
                             "exclude": [t for t in config.TOYS if t != toy], "self_seen": toy})
            return
        n, label = NAMES[toy], thing.label
        if thing.kind == "person" and not label.startswith("a "):
            how = f"{n} greets {label} warmly by name in one short line."
        elif thing.kind == "pet":
            how = f"{n} says hi to the {label.split()[-1] if label.startswith('a ') else label} in one short line."
        else:          # an unknown person: no name to use (it once called a parent "cat")
            how = f"{n} says a short friendly hello in one short line, without guessing a name."
        self.events.put(f"{n} just noticed {label}. {how}")

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
        if config.CONTINUE and self._cur_utt is not None and not self.last_lines:
            self._cont = (self._cur_utt, time.time())   # nothing answered yet: the child is still on the same thought
        for s in self.segs.values():   # the interrupting words may be one short "Stop!": do not drop them as noise
            s.short_until = time.monotonic() + config.BARGE_SHORT_S
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
                c = self._cont
                if c and time.time() - c[1] > config.CONTINUE_ALONE_S and not self.child_speaking() and not self.paused:
                    self._cont = None        # nothing more came: the first part is answered as it is
                    self._turn(utt=c[0])
                    continue
                self.live.tick()   # metrics: close a session that has been idle too long
                self._maybe_event()
                continue
            if self.paused:
                continue
            u = arbitrate(u, self.utter_q, expected_toys=self.hub.online())
            if self._story_on() and self._story_echo(u):
                continue
            self._barge_t = 0.0   # the interrupting words are being answered now
            u = self._continued(u)
            u.arbitrated = time.monotonic()
            self.child_contact()
            log.info("utterance: %s %.1fs rms=%.0f", u.toy, len(u.pcm) / config.SAMPLE_RATE, u.rms)
            self._turn(utt=u)

    def _went_on(self, utt, gen) -> bool:
        """The child is talking again and nothing has been answered: drop this turn, the two parts are answered together."""
        if not config.CONTINUE or self._gen != gen or self.last_lines or getattr(self.hub, "talking", None):
            return False
        # new speech only: another mic still finishing the SAME words (it reports a moment later) is not the child going on
        # ("Stop talking." was answered 3 s late as "Stop talking. Stop talking.", live Nov 26)
        if not any(getattr(s, "active", False) and getattr(s, "start", 0) >= utt.end - 0.1 for s in self.segs.values()):
            return False
        self._cont = (utt, time.time())
        self._barge_t = time.time()      # the words now being said must outlive this turn's _flush()
        self._gen += 1
        log.info("the child is going on: this turn waits for the rest")
        return True

    def _continued(self, u):
        """The child went on talking over the toy's first sound, before any answer: both parts are one utterance."""
        c, self._cont = self._cont, None
        if not c or time.time() - c[1] > config.CONTINUE_S or self._story_on():
            return u
        first = c[0]
        gap = np.zeros(int(config.CONTINUE_GAP_S * config.SAMPLE_RATE), dtype=first.pcm.dtype)
        u = dataclasses.replace(u, toy=first.toy, start=first.start, pcm=np.concatenate([first.pcm, gap, u.pcm]),
                                rms=max(first.rms, u.rms), speech_ms=first.speech_ms + u.speech_ms)
        u.continued = True
        log.info("the child went on: two parts answered as one turn (%.1fs)", len(u.pcm) / config.SAMPLE_RATE)
        return u

    _FILL = frozenset("a an and are at be but can did do does for from have i i'm in is it it's me my no not of oh ok okay on or so "
                      "that the then there this to too um was we what when with yes you your".split())

    def _ears_heard(self, utt) -> list[str]:
        """What the fast recogniser made of this utterance: its word runs, the longest first."""
        t0 = utt.start - 0.6
        return sorted({x.strip() for t, _toy, x in list(self._ears_recent) if t >= t0 and x.strip()}, key=len, reverse=True)

    def _heard_gate(self, utt, text: str) -> tuple[str, str]:
        """Is the model's transcript something a microphone heard? ("ok" | "noise" | "reask", the recogniser's words)."""
        ears = getattr(self, "ears", None)
        if not config.HEARD_GUARD or not getattr(ears, "ok", False) or not self._ears_recent:
            return "ok", ""           # no recogniser, or it has not heard a word yet since the start (cold): nothing to compare with
        runs = self._ears_heard(utt)
        behind = lambda: getattr(getattr(ears, "q", None), "qsize", lambda: 0)() > 5      # mic frames it has not decoded yet
        until = time.time() + config.HEARD_GUARD_WAIT_S
        late = time.time() + config.HEARD_GUARD_BEHIND_S
        while not runs and (time.time() < until or (behind() and time.time() < late)):
            time.sleep(0.03)
            runs = self._ears_heard(utt)
        words = lambda s: re.findall(r"[a-z']+", s.lower())
        ew, mw = {w for r in runs for w in words(r)}, words(text)
        best = runs[0] if runs else ""
        log.info("heard guard: the model wrote %d words, the recogniser heard %d", len(mw), len(ew))    # counts, never the words
        # said twice is said: the same words again right after being turned away are a child repeating, not a noise
        prev, self._rejected = getattr(self, "_rejected", None), None
        if mw and prev and time.time() - prev[0] < config.HEARD_GUARD_REPEAT_S and len(set(mw) & prev[1]) * 2 >= len(set(mw)):
            return "ok", best
        if not mw:                    # no transcript: answering is fine only if somebody said something (two words or more:
            return ("ok" if len(words(best)) >= 2 else "noise"), best      # a ding is one "word" to the recogniser)
        if not ew:                    # a whole sentence the recogniser has no word of: invented (a short "yes" may slip past it)
            if len(mw) >= 3:
                self._rejected = (time.time(), set(mw))
            return ("noise" if len(mw) >= 3 else "ok"), ""
        mc = [w for w in mw if w not in self._FILL] or mw
        ec = [w for w in ew if w not in self._FILL] or list(ew)
        same = lambda a, b: a == b or (min(len(a), len(b)) >= 4 and a[:4] == b[:4]) or difflib.SequenceMatcher(None, a, b).ratio() >= 0.75
        hit = sum(any(same(a, b) for b in ec) for a in mc)
        if hit * 3 >= len(mc) or len(mw) < 3:      # a word or two may be all the recogniser missed
            return "ok", best
        # the one word that carries the meaning differs but the rest is the same sentence ("do you LIKE me" for "do you love me",
        # live Nov 26: the question got silence): somebody did speak, so answer, from the recogniser's words when it has a run of them
        if sum(any(same(a, b) for b in ew) for a in mw) * 2 >= len(mw):
            return ("reask" if len(words(best)) >= 3 else "ok"), best
        if len(words(best)) < 4:
            self._rejected = (time.time(), set(mw))
        return ("reask" if len(words(best)) >= 4 else "noise"), best       # its own words may be an echo's: only a real run of them

    def _maybe_event(self):
        if self.paused or self.busy or not self.hub.online():
            return
        try:
            ev = self.events.get_nowait()
        except queue.Empty:
            ev = None
            now = time.time()
            if (self.idle_on and not self.is_quiet() and now - self.last_activity > self.live.idle_banter_s(config.IDLE_BANTER_S)
                    and now >= self._quiet_until and not self._story_on() and now - self._last_child_t > (config.IDLE_AFTER_CHILD_S if config.CHILD_LEADS else 0)
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
            seen = [x.label for x in v.things if x.kind == "toy" and not x.label.startswith("itself")]
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
            story_on = tl["story"] = bool(utt) and self._story_on()   # the child is reading: no words from the toys this turn
            self._cur_utt = utt if utt is not None and not story_on else None
            if getattr(utt, "continued", False):
                tl["flags"]["continued"] = True
            if utt and not story_on:
                self._since_sound += 1
            if utt and config.PLAY_FILLERS and not story_on:
                ftoy = toy if toy not in config.SPEAKER_BAD else next((t for t in online if t not in config.SPEAKER_BAD), toy)
                f = random.choice(canned.FILLERS.get(ftoy, ["Hmm!"]))

                answer_ready = threading.Event()         # set when the first line of the answer is about to play

                def fill():
                    until = time.time() + max(config.CONTINUE_HOLD_S if config.CONTINUE else 0, config.FILLER_AFTER_S)
                    while time.time() < until:           # is the child going on? then no sound: the mics stay open
                        if self._gen != gen or self._went_on(utt, gen) or answer_ready.is_set():
                            return                       # ...and an answer that is ready needs no "Let me think!"
                        time.sleep(0.02)
                    self.hub.play_line(ftoy, f, self.voices)
                filler = threading.Thread(target=fill, daemon=True)
                filler.answer_ready = answer_ready
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
            speakers = [t for t in speakers if t not in config.SPEAKER_BAD] or speakers   # a toy with a broken speaker gets no lines
            asked_look = event.get("look") if isinstance(event, dict) else None   # the dashboard's "what do you see?"
            self_seen = event.get("self_seen") if isinstance(event, dict) else None
            if asked_look in online:
                toy, speakers = asked_look, [asked_look]
            event_text = event["text"] if isinstance(event, dict) else event
            here = ", ".join(NAMES[t] for t in speakers)
            prompt = f"[TOYS HERE] {here} (only these toys may speak)\n[SCENE] {scene}\n"
            wav = None
            said = ""
            vox = None
            if utt:
                vox = self._start_voice(utt, toy)     # who is talking: a voice print, in parallel with the prompt (~85 ms)
                wav = self._wav(utt.pcm)
                debugrec.save("in", toy, normalize(utt.pcm).tobytes())
                tmp_files.append(wav)
                prompt += f"[HEARD BY] {NAMES[toy]} (closest to the child).\n"
                if self.llm.hears_audio:
                    prompt += (story.LISTEN + (story.LISTEN_SOUNDS if config.STORY_MODEL_SOUNDS else "")) if story_on else \
                        "The child just spoke (audio attached). Reply."
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
            looks = self._can_look(toy) and not story_on
            stop_now = bool(said and config.CHILD_LEADS and camera.wants_stop(said)) and not story_on   # story mode decides in _story_heard
            story_now = bool(said and config.STORY_MODE and not story_on and not stop_now and story.wants_story(said))
            if (utt and not said and not story_on and config.STORY_MODE and not stop_now
                    and time.time() - self._story_start_fast < config.STORY_START_FAST_S + len(utt.pcm) / config.SAMPLE_RATE):
                # the fast recogniser heard the opening line while it was being said: story mode starts whatever the model then
                # writes down or leaves out (it answered with no transcript once in eight, live Nov 22)
                story_now, tl["flags"]["start_by_ears"], self._story_start_fast = True, True, 0.0
                self.last_heard = tl["heard"] = "I'm going to read you a story."
            named = camera.addressed(said) if said and config.CHILD_LEADS and not stop_now and not story_on else None
            if named and named in speakers:   # the child spoke to one toy: only that toy answers
                prompt = prompt.replace(f"[TOYS HERE] {here} ", f"[TOYS HERE] {NAMES[named]} ", 1)
                speakers, toy = [named], named
            if asked_look and config.LOOK_ON_REQUEST and self._has_cam(toy):
                prompt, image = self._look_turn(toy, prompt, scene, "What do you see right now?", image, tmp_files, trace)
            if said and camera.ispy_stop(said):
                self._ispy_until = 0.0
            ispy = bool(utt) and not story_on and config.ISPY and (self._ispy_on() or bool(said and camera.wants_ispy(said)))
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
            speaker = self._speaker_block(vox, toy) if vox else ""      # after the log line: names are never logged
            if speaker:
                prompt = prompt.replace("[HEARD BY]", speaker + "\n[HEARD BY]", 1)
            if said and utt and not story_on and camera.wants_whoami(said):
                prompt += "\n" + self._whoami_prompt(named or toy, vox, toy).split("\n", 1)[1]
            prompt = "".join(b + "\n" for b in (notes, topics) if b) + prompt

            def dispatched(who, text):
                self.live.toy_line(text)   # metrics: question/invite flags only
                self.last_lines.append((who, text))
                self.last_latency = trace.snapshot()["milestones_ms"]["first_audio_post_ms"] / 1000

            pipeline = SpeechPipeline(self.hub, self.voices, trace, dispatched,
                                      before_play=(lambda: (filler.answer_ready.set(), filler.join())) if filler else None,
                                      cancelled=lambda: self._gen != gen,
                                      gate=lambda: (self._wait_cue(), bool(utt) and not story_on and self._went_on(utt, gen)))
            deflected = []

            def gate(text):
                """Once per turn, before anything is spoken: was this utterance really said? (config.HEARD_GUARD)"""
                if "hg" in tl:
                    return tl["hg"]
                check = bool(utt) and self.llm.hears_audio and not said and not story_on and not stop_now and not story_now
                verdict, ears_text = self._heard_gate(utt, text) if check else ("ok", "")
                tl["hg"] = verdict
                if verdict != "ok":
                    tl["mute"], parser.closed = True, True
                    tl["flags"]["unheard" if verdict == "noise" else "reheard"] = True
                    if text:
                        tl["flags"]["rejected"] = text[:80]       # for review (RAM, like the rest of this log)
                    if verdict == "reask":
                        tl["reask"] = ears_text
                    log.info("heard guard: %s", verdict)          # the verdict only, never the words
                elif check and not text and len(ears_text.split()) >= 2:
                    tl["ears_text"] = ears_text                   # no transcript from the model: the recogniser's words go in the log
                    # ...and "stop" / "tell me a joke" still count (the stock model left the transcript out for 3 lines of 7,
                    # live Nov 26)
                    if config.CHILD_LEADS and camera.wants_stop(ears_text):
                        heard(ears_text)
                    elif config.JOKE_BANK and jokes.wants(ears_text, time.time() - self._joke_t < config.JOKE_AGAIN_S):
                        at = camera.addressed(ears_text)
                        at = at if at in parser.online else (toy if toy in parser.online else sorted(parser.online)[0])
                        tl["ack"], tl["ack_line"], tl["flags"]["joke"] = at, self._jokes.next(at), True
                        self._joke_t, parser.closed = time.time(), True
                return verdict

            def line_ready(who, text):
                if self._gen != gen:
                    return
                if utt and not story_on and (gate(parser.heard_text if parser.heard_text not in (None, "-") else "") != "ok" or tl.get("mute")):
                    return
                if tl.get("ack") and (tl["flags"].get("stop") or tl["flags"].get("joke")) and (who, text) != (tl["ack"], tl.get("ack_line")):
                    return                       # stop / a joke from the list was decided from the recogniser's words: no model line
                if tl.get("story"):   # the child is reading: whatever the model wrote is not spoken (a lone sound tag may be used)
                    tl.setdefault("story_lines", []).append(text)
                    return
                if self_seen == who and not self.turn_lines and not re.search(r"\b(?:me|myself|i'?m|i am)\b", text, re.I):
                    text = "Hey, that's me! " + text     # the toy saw itself: it must say so, whatever the model wrote
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
                if not utt:
                    return                       # an [EVENT] turn has no child audio: a HEARD line there is old words repeated
                if not story_on and gate(text) != "ok":
                    return                       # nobody said this: nothing is routed, remembered or answered
                if not text and tl.get("story") and self._story_ears_log:
                    # the model gave no transcript ("HEARD: -" for every sentence of one story, live Nov 22, so "the end" was
                    # never seen and the story stayed on): the fast recogniser's words for this stretch stand in
                    text, tl["flags"]["heard_by_ears"] = max((e[1] for e in self._story_ears_log), key=len).strip(), True
                if text and tl.get("story"):
                    text = story.tidy(text)
                if text and tl.get("story"):
                    self._story_heard(text, toy, tl, online)
                elif text and utt and config.STORY_MODE and not self._story_on() and not camera.wants_stop(text) and story.wants_story(text):
                    # "I'm going to read you a story": from the next sentence on the toys only add sounds
                    self._story_begin()
                    tl["flags"]["story"] = "start"
                    if not parser.count:     # nothing spoken yet: one short "I'm listening" and no more
                        at = toy if toy in speakers else speakers[0]
                        tl["ack"], tl["ack_line"] = at, canned.STORY_START.get(at, "A story! I'm listening.")
                        parser.closed, parser.count = True, 1
                if tl.get("story") or tl["flags"].get("story") == "start":
                    pass
                elif text and utt and config.ISPY and (looks or config.CAPTURE_CONTINUOUS):
                    # audio-native model: the words arrive only now. A child who started I spy keeps the game (and its pictures) on
                    if camera.ispy_stop(text):
                        self._ispy_until = 0.0
                    elif camera.wants_ispy(text):
                        self._ispy_until = time.time() + config.ISPY_GAME_S
                if text and utt and config.CHILD_LEADS and not parser.count and not tl["flags"].get("stop") and not tl.get("story"):
                    # HEARD-first: nothing spoken yet. "stop" -> say nothing but "I'm listening"; a toy's name -> only that toy
                    if camera.wants_stop(text):
                        tl["flags"]["stop"], tl["ack"] = True, toy
                        self._quiet(toy)
                        parser.closed, parser.count = True, 1
                    elif config.JOKE_BANK and jokes.wants(text, time.time() - self._joke_t < config.JOKE_AGAIN_S):
                        # a joke from the list, told by the toy that was asked (or that heard the child): no model line is spoken
                        at = camera.addressed(text)
                        at = at if at in parser.online else (toy if toy in parser.online else sorted(parser.online)[0])
                        tl["ack"], tl["ack_line"], tl["flags"]["joke"] = at, self._jokes.next(at), True
                        self._joke_t = time.time()
                        parser.closed, parser.count = True, 1
                    else:
                        who = camera.addressed(text)
                        if who and who in parser.online:
                            parser.online, parser._max_lines = {who}, 1
                            tl["flags"]["named"] = who
                        look_toy = tl["flags"].get("named") or toy
                        if camera.wants_whoami(text):
                            # "who am I?": answered from the face and voice the toys know, in a fresh round (the model
                            # repeated its last camera answer five times, Nov 15)
                            tl["force_whoami"], parser.closed = look_toy, True
                        elif (not image and not tl.get("looked") and camera.wants_look(text) and self._can_look(look_toy)):
                            # "who do you see?": the code takes the picture itself (the model often answers from [SCENE] instead)
                            tl["force_look"], parser.closed = look_toy, True
                        elif (not image and not tl.get("looked") and config.ISPY and camera.wants_ispy(text)
                              and self._can_look(look_toy)):
                            # "can we play I spy?": the tuned models answered without LOOK ("What do you see?", live Nov 26), so
                            # the code starts the game: one picture, the I spy prompt, the referee
                            tl["force_look"], tl["force_game"], parser.closed = look_toy, "ispy", True
                if text and utt and config.CHILD_LEADS and camera.wants_stop(text) and not tl["flags"].get("stop") and not tl.get("story"):
                    # the audio-native model wrote toy lines instead of STOP (it hears the child, the words come last): cut what is
                    # queued now, then one "I'm listening" after the turn, and quiet
                    tl["flags"]["stop"], tl["ack"] = True, toy
                    self._quiet(toy)
                    self.interrupt()
                if text and utt and vox:
                    self._learn_intro(vox, text, tl)
                if text:
                    self.last_heard = text
                    tl["heard"] = text
                    self._remember(text)
                    self.live.child_text(text)   # audio-mode models report the words here (no-op once STT supplied them)

            # context for the fact guard: a question asked at the end of the last turn (or by the child) is answered now
            guard = factcheck.FactGuard(context=[t for _w, t in prev_lines[-1:]] + [said]) if config.FACT_GUARD else None
            referee = (camera.ISpyReferee(said, self._ispy_seen, self._ispy_secret, self._ispy_guessed, self._ispy_clue)
                       if ispy and self._ispy_seen is not None else None)
            def lead_sound(tag, child):
                """May this reply to the child open with a recorded sound? Yes when the child's words call for it ("roar for me",
                the sound's own name), else once in SOUND_LEAD_GAP turns."""
                child = child or ""
                ok = (tl["flags"].get("sound_led") or bool(SOUND_ASKED.search(child))
                      or any(len(w) > 3 and w in child.lower() for w in tag.split("_"))
                      or self._since_sound >= config.SOUND_LEAD_GAP)
                if ok and not tl["flags"].get("sound_led"):
                    tl["flags"]["sound_led"] = True
                    self._since_sound = 0
                return ok

            def warmed(p):
                if utt and not story_on:
                    p.child = lambda: tl.get("heard") or tl.get("reask") or said or ""
                    p.lead_sound = lead_sound
                    if config.WARM_GUARD:
                        p.warm = warm.Guard(lambda: tl["flags"].__setitem__("warmed", True))
                return p

            parser = warmed(ReplyLines(speakers, line_ready, heard, guard, referee,
                                       max_lines=(1 if named else config.CHILD_MAX_LINES) if utt and config.CHILD_LEADS else None))
            if named:
                tl["flags"]["named"] = named
            kwargs = dict(wav=wav if self.llm.hears_audio else None, image=image)
            stream = getattr(self.llm, "stream", None)
            words = ((camera.LOOK_WORD,) if looks else ()) + ((camera.STOP_WORD,) if config.CHILD_LEADS else ())
            peel = camera.LookPeeler(words) if words and utt and not image and not story_on else None   # round 0 may be the one-word LOOK / STOP
            if stop_now:      # transcript said stop: no model call at all, just "I'm listening" and quiet
                tl["flags"]["stop"] = True
                self._quiet(toy)
                line_ready(toy, canned.LISTENING.get(toy, "Okay, I'm listening."))
                parser.count = 1
            elif story_now:   # transcript said "I'll read you a story": no model call, one "I'm listening", story mode on
                self._story_begin()
                tl["flags"]["story"] = "start"
                line_ready(toy, canned.STORY_START.get(toy, "A story! I'm listening."))
                parser.count = 1
            with trace.span("llm_ms"):
                if tl.get("story") and not said and len(utt.pcm) < 3.0 * config.SAMPLE_RATE:
                    # "The end." — the fast recogniser has it about now (its pause is 0.45 s, the turn's 0.5 s): no need for Gemma
                    # to transcribe two words first (1 s, and the kind line came 4 s after "the end", Mac mic, Nov 21)
                    for _ in range(8):
                        if time.time() - self._story_end_fast < config.STORY_END_FAST_S:
                            said, tl["flags"]["end_fast"] = "The end.", True
                            break
                        time.sleep(0.025)
                for round_ in ((0, 1) if not (stop_now or story_now) else ()):
                    if tl.get("story") and said:      # a transcript is already here: nothing to ask the model while the child reads
                        chunks = iter([f"HEARD: {said}\n"])
                    else:
                        chunks = stream(prompt, **kwargs) if stream else iter([self.llm.ask(prompt, **kwargs)])
                    try:
                        for delta in chunks:
                            if self._gen != gen or tl.get("mute") or (tl.get("force_look") and not tl.get("looked")) or (
                                    tl.get("force_whoami") and not tl.get("whoami_done")) or (tl.get("story") and tl.get("story_done")):
                                break
                            if peel:
                                delta = peel.feed(delta)
                            if delta:
                                trace.mark("first_model_text_ms")
                                if tl.get("story") or tl.get("story_end"):
                                    tl["raw"] = (tl.get("raw", "") + delta)[:400]
                                if RAW_DEBUG:            # SENTIENT_DEBUG_RAW=1: the model's own text, RAM only, for a debugging session
                                    with open("/dev/shm/sentient-raw.txt", "a") as fh:
                                        fh.write(delta)
                                parser.feed(delta)
                        if peel:
                            parser.feed(peel.finish())
                    finally:
                        close = getattr(chunks, "close", None)
                        if close:
                            close()
                    if tl.get("story"):
                        parser.finish()
                        if not tl["heard"] and not said and self._gen == gen:   # no HEARD: label, only the words
                            heard(story.loose(tl.get("raw", "")))
                        nxt = tl.pop("story_next", None)
                        if not nxt or round_ or self._gen != gen:
                            break
                        # "the end", or a question to one toy: this one turn is answered in words, in a fresh round
                        tl["story"] = False
                        base = prompt[:prompt.index(story.LISTEN)] if story.LISTEN in prompt else prompt.split("The child said:")[0]
                        if nxt[0] == "end":
                            tl["story_end"] = True
                            at = toy if toy in speakers else speakers[0]
                            line_ready(at, canned.STORY_END.get(at, story.END_LINE))   # at once; the model's own line follows
                            at2 = next((t for t in speakers if t != at), at)     # another toy adds the line about the story
                            tl["story_end"], tl["raw"] = at2, ""
                            prompt = base + story.end_prompt(nxt[1], NAMES[at2])
                            parser = ReplyLines([at2], line_ready, lambda _t: None, guard, None, max_lines=1)
                        else:
                            prompt = base + story.ask_prompt(nxt[1])
                            parser = ReplyLines([nxt[2]], line_ready, heard, guard, None, max_lines=1)
                        kwargs = dict(wav=None, image=None)
                        continue
                    if tl.get("reask") and not tl.get("reasked") and round_ == 0 and self._gen == gen:
                        # the transcript shares nothing with what the microphones heard: asked again, from the recogniser's words
                        tl["reasked"], tl["mute"], tl["hg"] = True, False, "ok"
                        prompt = prompt.replace("The child just spoke (audio attached). Reply.", f'The child said: "{tl["reask"]}"\nReply.')
                        self.last_heard = tl["heard"] = tl["reask"]
                        kwargs, peel = dict(wav=None, image=image), None
                        parser = warmed(ReplyLines(speakers, line_ready, heard, guard, None,
                                                   max_lines=(1 if named else config.CHILD_MAX_LINES) if config.CHILD_LEADS else None))
                        continue
                    if tl.get("mute"):
                        break
                    if peel and peel.looking and peel.word == camera.STOP_WORD and self._gen == gen:
                        # the child said stop: one short "I'm listening", then quiet (no toy-to-toy chat for STOP_QUIET_S)
                        tl["flags"]["stop"] = True
                        if peel.heard:
                            heard(peel.heard)
                        self._quiet(toy)
                        line_ready(toy, canned.LISTENING.get(toy, "Okay, I'm listening."))
                        parser.count = 1
                        break
                    if tl.get("force_whoami") and not tl.get("whoami_done") and round_ == 0 and self._gen == gen:
                        tl["whoami_done"] = tl["flags"]["whoami"] = True
                        who_toy = tl["force_whoami"]
                        prompt = self._whoami_prompt(who_toy, vox, toy)
                        kwargs, peel = dict(wav=None, image=None), None
                        parser = ReplyLines([who_toy], line_ready, heard, guard, None, max_lines=1)
                        continue
                    forced = tl.get("force_look") and not tl.get("looked")
                    if not (((peel and peel.looking) or forced) and round_ == 0 and self._gen == gen):
                        break
                    # The child asked the toy to look: one picture from the toy that was named (or heard them), camera off again,
                    # same turn; only that toy answers.
                    if peel and peel.looking and peel.heard:
                        heard(peel.heard)
                    look_toy = tl.get("force_look") or tl["flags"].get("named") or toy
                    tl["looked"] = True
                    game = tl.get("force_game") or ("ispy" if config.ISPY and camera.wants_ispy(tl.get("heard") or "") else None)
                    prompt, image = self._look_turn(look_toy, prompt, scene, (tl.get("heard") or None) if game else None, None,
                                                    tmp_files, trace, replace=False, game=game)
                    kwargs, peel = dict(wav=None, image=image), None
                    if game:       # the game is on from this turn; the referee holds the line to what the picture list shows
                        ispy, self._ispy_until = True, time.time() + config.ISPY_GAME_S
                        referee = (camera.ISpyReferee(tl.get("heard") or "", self._ispy_seen, self._ispy_secret, self._ispy_guessed,
                                                      self._ispy_clue) if self._ispy_seen is not None else None)
                    parser = ReplyLines([look_toy], line_ready, heard, guard, referee if game else None, max_lines=1 if game else 2)
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
            if tl.get("story") and self._gen == gen and not tl["flags"].get("stop"):   # still reading: at most one sound, no words
                snd = getattr(self.voices, "sounds", None)
                name = tl.get("story_sound")
                if not name and config.STORY_MODEL_SOUNDS:      # no word in the table fits: a sound the model proposed, if any
                    name = story.model_sound(tl.get("story_lines"), set(snd.pcm) if snd else None)
                    if name and time.time() - self._story_last.get(name, 0) >= config.STORY_REPEAT_S:
                        self.turn_lines += self._story_play([name], toy, online)
                    else:
                        name = None
                tl["flags"]["story"] = name or "quiet"
            at2 = tl.pop("story_end", None)
            if at2 and not parser.count:   # "the end": the model put another toy's name on its line, or said nothing (the canned
                extra = story.end_line(tl.get("raw", "")) if self._gen == gen else ""      # line was said either way)
                if extra:
                    line_ready(at2, extra)
                parser.count = 1
            if not parser.count and not tl.get("story") and not tl.get("ack") and not tl.get("mute") and not (
                    self._gen != gen and self._cont):      # cut by the child going on: answered with the rest, not a failure
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
                filler.answer_ready.set()
                filler.join()
            if tl.get("ack"):
                try:
                    ack = tl.get("ack_line") or canned.LISTENING.get(tl["ack"], "Okay, I'm listening.")
                    self.hub.play_line(tl["ack"], ack, self.voices)
                    self.turn_lines.append((tl["ack"], ack))
                except Exception:  # noqa: BLE001
                    log.warning("listening line failed")
            for f in tmp_files:
                try:
                    os.unlink(f)
                except OSError:
                    pass
            self._cur_utt = None
            if self._gen != gen and self._cont:
                tl["flags"]["went_on"] = True      # the child was still talking: answered with the rest, next turn
            if not tl["heard"] and tl.get("ears_text"):
                tl["heard"], tl["flags"]["heard_by_ears"] = tl["ears_text"], True
            self._flush()
            self.hub.response_active.clear()
            self.busy = False
            self.last_activity = time.time()
            self.live.child_unresolved(status)   # metrics: count the utterance's timing even if no words were reported
            self.live.turn_close(status)
            trace.finish(status)
            if tl.get("raw"):   # story turns: exactly what the model wrote, for review (RAM only, like the rest of this log)
                tl["flags"]["raw"] = tl["raw"]
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
        if self._story_on():
            t = 1.0     # the child reads on while the brain works: every sentence heard meanwhile is the next turn
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
            # a sentence in progress is the child's (the mics are closed while a toy talks, so it is not toy echo): let it
            # finish. Resetting it cut "Dyno, what color shirt am I wearing?" down to "color shirt am I wearing".
            if not getattr(s, "active", False):
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
        return hasattr(self.eyes, "snap") and bool(a and getattr(a, "cam", False)) and config.LOOK_ON_REQUEST

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
        self._story_until = 0.0
        log.info("child said stop: quiet for %.0f s", config.STOP_QUIET_S)

    # ---------- story mode (brain/story.py) ----------
    def _story_on(self) -> bool:
        return config.STORY_MODE and time.time() < getattr(self, "_story_until", 0.0)

    def _story_begin(self):
        self._story_until = time.time() + config.STORY_IDLE_S
        self._story_text, self._story_last, self._story_rms = [], {}, 0.0
        self._story_suspect = False
        self._story_short()
        log.info("story mode on: the toys only add sounds")
        def warm():      # the line for "the end", rendered now so it plays at once then
            for t in self.hub.online():
                try:
                    self.voices.render(t, canned.STORY_END.get(t, story.END_LINE), persist=True)
                except Exception:  # noqa: BLE001
                    pass
        threading.Thread(target=warm, daemon=True, name="story-warm").start()

    def _story_echo(self, u) -> bool:
        """The mics stay open during a story sound, so a mic can catch the sound itself. That is far quieter than the child
        reading: something heard during a sound at under a third of the child's level is the sound, not a sentence."""
        p0, p1 = getattr(self, "_story_prev", (0.0, 0.0))
        if min(u.end, p1) - max(u.start, p0) > 0.5 * (u.end - u.start):
            log.info("story: ignored the same sentence from another mic")
            return True
        self._story_prev = (u.start, u.end)
        t0, t1 = self._story_sound_t
        inside = u.start > t0 - 0.3 and u.end < t1 + config.MIC_TAIL_S     # began and ended while a story sound played
        if self._story_rms and u.start < t1 + config.MIC_TAIL_S and u.end > t0 and u.rms < (
                config.STORY_ECHO_INSIDE if inside else config.STORY_ECHO_RATIO) * self._story_rms:
            log.info("story: ignored a toy's own sound in a mic (%.0f%% of the child's level)", 100 * u.rms / self._story_rms)
            self._story_prev = (p0, p1)
            return True
        # as loud as the reading but wholly inside a sound (a mic next to the toy that played it): "stop" and "the end" still count,
        # nothing else does (live Nov 21: the model wrote "Wow!" and "That sounds like a fun game!" for a bark and a crow)
        self._story_suspect = bool(inside and u.end > t0)
        if not self._story_suspect:
            self._story_rms = u.rms if not self._story_rms else 0.7 * self._story_rms + 0.3 * u.rms
        return False

    def _story_short(self, on=True):
        """While the child reads, a very short utterance counts: "The end." and "Stop!" are under half a second."""
        for s in getattr(self.segs, "values", lambda: ())():
            s.short_until = time.monotonic() + config.STORY_IDLE_S if on else 0.0

    def _story_heard(self, text, toy, tl, online):
        """One sentence of the story (or the child talking to the toys in the middle of it)."""
        self._story_until = time.time() + config.STORY_IDLE_S
        self._story_short()
        if camera.wants_stop(text) and story.is_command(text):
            tl["flags"]["stop"], tl["ack"] = True, toy
            self._quiet(toy)
            self._story_short(False)
            log.info("story mode off (stop)")
            return
        if story.ends(text):
            self._story_until = 0.0
            tl["flags"]["story"] = "end"
            tl["story_next"] = ("end", " ".join(self._story_text)[-config.STORY_RECALL_CHARS:])
            self._story_short(False)
            log.info("story mode off (the end)")
            return
        who = next((k for k, rx in camera._NAMES.items() if k in online and story.asks_toy(text, rx)), None)
        if who:
            tl["flags"]["story"], tl["flags"]["named"] = "ask", who
            tl["story_next"] = ("ask", text, who)
            return
        fast, self._story_fast = self._story_fast, []
        ears, self._story_ears_log = self._story_ears_log, []
        if ears:
            tl["flags"]["ears"] = ears
        if fast:        # already playing: the fast recogniser heard the word while the child was still reading
            self.turn_lines += fast
            tl["story_sound"] = "+".join(n.strip("{}") for _w, n in fast)
        if getattr(self, "_story_suspect", False):
            tl["story_done"] = True
            log.info("story: heard something during a toy's sound, not used")
            return
        self._story_text.append(text)
        now = time.time()
        snd = getattr(self.voices, "sounds", None)
        names = story.pick_all(text, set(snd.pcm) if snd else None,
                               {n for n, t in self._story_last.items() if now - t < config.STORY_REPEAT_S}, config.STORY_CHORUS_MAX)
        if names and now - self._story_fast_t < config.STORY_BACKUP_AFTER_S:
            names = []    # the fast recogniser already gave this sentence its sounds: one added now would come seconds late and
                          # out of order (live Nov 21: the bray 2.5 s and the bark 6 s after "brayed, barked, mewed and crowed")
        if names:     # played at once: every tenth of a second later is further into the child's next sentence
            tl["story_sound"] = "+".join(filter(None, [tl.get("story_sound")] + names))
            self.turn_lines += self._story_play(names, toy, online)
        tl["story_done"] = bool(names) or not config.STORY_MODEL_SOUNDS   # nothing more is needed from the model this turn

    def story_words(self, toy, text, final):
        """The fast recogniser (brain/storyears.py) heard these words so far: start the sounds whose word has been said. Runs on
        its thread, during the reading; Gemma's transcript of the whole sentence comes later and adds only what this missed."""
        try:
            self._ears_recent.append((time.time(), toy, text))
            if not self._story_on():      # also mid-sentence: the line is whole once "...read you a story" is out
                if config.STORY_MODE and not self.hub.talking and story.ears_start(text):
                    self._story_start_fast = time.time()      # the turn for this utterance begins the story
                return
            if final and self._story_on() and story.fast_end(text):
                self._story_end_fast = time.time()     # the turn for this utterance (starting about now) ends the story at once
                return
            if not self._story_on() or not final:
                return    # only at a pause: a sound started mid-sentence drowns the rest of the sentence in every mic (live
                          # Nov 21: with the bray playing, "the hound barked" was heard as "the hambard" and the bark never came)
            online = self.hub.online()
            snd = getattr(self.voices, "sounds", None)
            now = time.time()
            names = story.heard_so_far(text, final, set(snd.pcm) if snd else None,
                                       {n for n, t in self._story_last.items() if now - t < config.STORY_REPEAT_S})
            if final:     # for the conversation log (RAM, like the transcript): what the fast recogniser made of this stretch
                self._story_ears_log = self._story_ears_log[-30:] + [[toy, text[-120:], "+".join(names)]]
            if names and online:
                self._story_until = now + config.STORY_IDLE_S
                self._story_fast_t = now
                self._story_fast += self._story_play(names, toy, online)
        except Exception:  # noqa: BLE001
            log.exception("story words failed")

    def _story_play(self, names, heard_toy, online) -> list:
        """Play the story sounds, one after another, without holding up the reading: each on the toy that owns it (Dyno's roar),
        else on a toy that is not the one closest to the child (its mic hears the reading best), taking turns.
        Returns [(toy, "{sound}")]."""
        snd = getattr(self.voices, "sounds", None)
        good = [t for t in online if t not in config.SPEAKER_BAD] or list(online)     # a toy whose speaker is broken plays no sounds
        others = [t for t in good if t != heard_toy] or good
        plan = []
        for name in names:
            owner = (snd.index.get(name) or {}).get("toy") if snd else None
            plan.append((owner if owner in good else others[self._story_n % len(others)], name))
            self._story_n += 1
            self._story_last[name] = time.time()
        log.info("story sound: %s", ", ".join(f"{n} on {w}" for w, n in plan))
        with self._story_qlock:
            if self._story_q is None:
                self._story_q = queue.Queue()
                threading.Thread(target=self._story_sounds, daemon=True, name="story-sound").start()
        for item in plan:
            self._story_q.put(item + (len(plan) > 1,))
        cur = self._story_cur        # a sound is still playing: it gives way, so this one is not late ("barked" must not wait
        if cur:                      # for the whole bray)
            threading.Timer(max(0.0, cur[1] + config.STORY_CUT_AFTER_S - time.time()), self._story_cut, args=(cur,)).start()
        return [(who, "{%s}" % name) for who, name in plan]

    def _story_cut(self, cur):
        if self._story_cur is cur:
            self.hub.stop(cur[0])

    def _story_sounds(self):
        """One sound at a time, in the order asked for."""
        while True:
            who, name, chorus = self._story_q.get()
            try:
                if not self._story_on():
                    continue       # "stop" or "the end" came first
                pcm = story.trim_lead(self.voices.render(who, "{%s}" % name))
                limit = config.STORY_CHORUS_S if chorus or not self._story_q.empty() else config.STORY_SOUND_MAX_S
                cap = int(limit * config.SAMPLE_RATE)
                if len(pcm) // 2 > cap:      # a short sound: the reading goes on underneath
                    x = np.frombuffer(pcm, "<i2")[:cap].astype(np.float32)
                    n = int(0.2 * config.SAMPLE_RATE)
                    x[-n:] *= np.linspace(1.0, 0.0, n)
                    pcm = x.astype("<i2").tobytes()
                if len(pcm) // 2 < config.STORY_TWICE_UNDER_S * config.SAMPLE_RATE:   # one bark is over before anyone hears it
                    pcm = pcm + b"\0\0" * int(0.12 * config.SAMPLE_RATE) + pcm
                # every toy's speaker loses the first ~0.1 s of a clip (measured with the Mac's mic): silence goes first
                pcm = b"\0\0" * int(config.STORY_LEAD_MS * config.SAMPLE_RATE / 1000) + pcm
                t0 = self._story_sound_t[0] if time.time() < self._story_sound_t[1] else time.time()   # a chorus is one window
                self._story_sound_t = (t0, time.time() + len(pcm) / 2 / config.SAMPLE_RATE + 0.5)
                self._story_cur = (who, time.time())
                self.hub.play(who, pcm, open_mics=True)   # the mics stay open: the child is already on the next sentence
            except Exception:  # noqa: BLE001
                log.warning("story sound failed")
            finally:
                self._story_cur = None

    def _ispy_on(self) -> bool:
        """An I spy game is going: the child started it and spoke again within ISPY_GAME_S."""
        on = time.time() < self._ispy_until
        if not on:
            self._ispy_secret, self._ispy_guessed, self._ispy_clue = None, [], None   # game over: forget what was spied and guessed
        return on

    # ---------- who is talking (brain/voiceid.py) ----------
    def _store(self):
        t = getattr(self.parent, "teacher", None) if self.parent else None
        return t.store if t else None

    def _start_voice(self, utt, toy):
        if not self.voiceid or not self._store():
            return None
        vox = {"done": threading.Event()}
        threading.Thread(target=self._voice_work, args=(utt, toy, vox), daemon=True, name="voiceid").start()
        return vox

    @staticmethod
    def _vox_wait(vox, timeout=1.0):
        if vox:
            vox["done"].wait(timeout)
        return vox or {}

    def _voice_work(self, utt, toy, vox):
        try:
            vec = self.voiceid.embed(utt.pcm)
            vox["vec"] = vec
            store = self._store()
            if vec is None or store is None:
                return
            vox["who"] = voiceid.match(store.gallery().voices, vec)
            log.info("voice print: %s", "known voice" if vox["who"] else "unknown voice")   # never who
            vox["done"].set()                     # the prompt can go now; learning below may take a few ms more
            pending = store.take_pending_voice()  # the Parent Board's "Learn voice"
            if pending:
                store.add_voice(pending, vec)
                vox["learned"] = "board"
                return
            face = self._face_of(toy)
            if face:
                self._learn_voice(store, store.person_for(label=face), vec, vox, why="face")
        except Exception:  # noqa: BLE001 — never break a turn over a voice print
            log.exception("voice print failed")
        finally:
            vox["done"].set()

    def _face_of(self, toy) -> str | None:
        """The one known person `toy`'s camera sees right now ("dad", "the child"), or None (nobody, several, or a stranger)."""
        v = self.eyes.views.get(toy) if toy else None
        if not v or not getattr(v, "eyes", False) or not (0 <= time.time() - v.ts <= config.VISION_MAX_AGE_S):
            return None
        ppl = [t for t in v.things if t.kind in ("person", "child")]
        return ppl[0].label if len(ppl) == 1 and ppl[0].label != "a person" else None

    def _learn_voice(self, store, eid, vec, vox, why):
        """Add a print to an enrolled person. A person with few prints collects candidates in RAM first and keeps them only
        once MIN_PRINTS of them sound alike (someone else talking while Dad is in view does not become Dad's voice)."""
        if not eid or vec is None:
            return
        who = vox.get("who")
        if who and who[0] != eid:
            return                                   # sounds like someone else the toys know
        now = time.time()
        if why == "face" and now - self._vox_t.get(eid, 0) < 5:
            return
        mine = store.voice_prints(eid)
        if len(mine) >= voiceid.MIN_PRINTS:
            if voiceid.agrees(mine, vec):
                store.add_voice(eid, vec)
                self._vox_t[eid], vox["learned"] = now, why
            return
        if why == "intro":                           # they said who they are: trust it
            store.add_voice(eid, vec)
            self._vox_t[eid], vox["learned"] = now, why
            return
        cand = (self._vox_cand.get(eid, []) + [vec])[-8:]
        self._vox_cand[eid] = cand
        best = max(([c for c in cand if voiceid.agrees([x], c)] for x in cand), key=len)
        if len(best) >= voiceid.MIN_PRINTS:
            for c in best:
                store.add_voice(eid, c)
            self._vox_cand.pop(eid, None)
            self._vox_t[eid], vox["learned"] = now, why

    def _learn_intro(self, vox, text, tl):
        name = voiceid.introduced(text)
        store = self._store()
        if not name or not store:
            return
        vox = self._vox_wait(vox)
        try:
            self._learn_voice(store, store.person_for(name=name), vox.get("vec"), vox, why="intro")
        except Exception:  # noqa: BLE001
            log.exception("voice print failed")
        if vox.get("learned"):
            tl["flags"]["voice_learned"] = vox["learned"]

    def _who(self, vox, toy, also=None):
        """(name to say, how the toy knows) of who is talking, or (None, None). Voice first, then the one face in view."""
        vox = self._vox_wait(vox)
        w = vox.get("who")
        face = self._face_of(toy) or (self._face_of(also) if also and also != toy else None)
        if w:
            label = "the child" if w[2] == "child" else w[1]
            name = w[1] if w[1].strip().lower() not in ("child", "the child") else "the child"
            return name, "knows their voice" + (" and sees their face" if face and face.lower() == label.lower() else "")
        if face:
            if face == "the child":
                store = self._store()
                eid = store.person_for(label="the child") if store else None
                nm = next((e["name"] for e in (store.list() if eid else []) if e["id"] == eid), "the child")
                face = nm if nm.strip().lower() not in ("child", "the child") else "the child"
            return face, "sees their face"
        return None, None

    def _speaker_block(self, vox, toy) -> str:
        try:
            name, how = self._who(vox, toy)
        except Exception:  # noqa: BLE001
            return ""
        return f"[SPEAKER] The one talking is {name} (the toy {how}). Talk to them by that name if it fits." if name else ""

    def _whoami_prompt(self, who_toy, vox, heard_toy) -> str:
        n = NAMES[who_toy]
        try:
            name, how = self._who(vox, who_toy, also=heard_toy)
        except Exception:  # noqa: BLE001
            name = how = None
        if name:
            say = "You're " + (name.title() if name != "the child" else "my best friend") + "!"
            return (f"[TOYS HERE] {n} (only this toy may speak)\n[WHO] The one asking who they are is {name}: {n} {how}. "
                    f"{n} tells them warmly who they are, by name, in one short line, like \"{say}\". Nothing about pictures or blur.")
        return (f"[TOYS HERE] {n} (only this toy may speak)\n[WHO] {n} does not know yet who is talking (it has not learned this "
                f"face or voice). {n} says so kindly and asks their name, in one short line.")

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
