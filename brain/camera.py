"""Camera policy: the toys' cameras are OFF. A toy looks only when the child asks.

  wants_look(text)   rules on a transcript ("what do you see", "look at this", "what is this", "can you see...")
  LookPeeler         for the audio-native Gemma (LiteRT), which hears the child directly so there is no transcript up front:
                     the prompt tells it to answer a look-request with the single word LOOK. The peeler spots that first word
                     in the stream, the director takes ONE picture from the toy that heard the child, and the same turn goes on
                     with the picture attached (the camera is off again as soon as the frame is captured).
  look_prompt(...)   the [CAMERA] block that replaces [SCENE] for that second half of the turn

Nothing here stores anything: the frame lives in RAM (and one /dev/shm temp file, deleted at the end of the turn).
"""
from __future__ import annotations

import re

# ---- intent rules (lower-cased, punctuation removed) ----
_THIS = r"(this|that|these|those|it|my|me|here|what i|what we|the \w+)"
_LOOK_RULES = [re.compile(p) for p in (
    r"\bwhat (do|can|could|does|did) (you|u|ya|yall) see\b",
    r"\bwhat (are|r) (you|u) (looking|seeing|looking) at\b",
    r"\bwhat (are|r) (you|u) seeing\b",
    r"\bwho (do|can|did|does) (you|u|ya|he|she|it|dyno|sage|penny) see\b",
    r"\b(can|could|do|did|will|would) (you|u|ya|yall) (even )?(see|look)\b",
    r"\b(do|can|could) (you|u) see (me|my|this|that|it|what)\b",
    r"\b(look|looks|looking|peek|peep) (at|over here|here|what)\b",
    r"\b(come|go ahead and|just|quick|please) (and )?look\b",
    r"\b(take|have|get|give it) a (quick |good |little )?(look|peek)\b",
    r"\b(check|checking) (this|that|it|these|those) out\b",
    r"\bwhat( is|s|re| are) (this|that|these|those)\b",
    r"\bwhat( is|s) (it|in my hand|in my hands|on my|in front of you|over here|here)\b(?! (called|time|day))",
    r"\bwhat am i (holding|wearing|showing|pointing)\b",
    r"\bwhat colou?r\b.{0,20}\b(am i|is my|are my|do i have|i am)\b",
    r"\b(am i|i am|im) wearing\b",
    r"\bwhat (do|did) i (have|got|hold|made|draw|drew|bring|brought)\b",
    r"\bwhat( is|s)? (colou?r|shape|animal|kind of \w+|type of \w+|number|letter|word) (is|are) (this|that|these|those|it)\b",
    r"\bwhat colou?r (is|are) (my|this|that|the)\b",
    r"\bwho( is|s| are) (this|that|these|those|here)\b",
    r"\b(i|we) (want to|wanna|will|gonna|am going to|have to|got to|need to|can) show you\b",
    r"\b(let me|lemme|let us|lets) show you\b",
    r"\bshow (you|u) (this|that|my|what|something|a|an|the)\b",
    r"\bhow many (fingers|things|toys|\w+) (am i|do i|are there|is there)\b.*\b(holding|have|here|up|this)\b",
    r"\bsee (this|that|what i|what we|my)\b",
    r"\bcan you tell what (this|that|it) is\b",
    r"\bwhat does (this|that|it) (look like|say)\b",
)]
# "don't look", "stop looking", "turn the camera off": never a request to take a picture
_REFUSE = re.compile(r"\b(don t|dont|do not|stop|never|no more|quit|please no|no)\b.{0,25}\b(look|looking|see|seeing|watch|watching|peek|camera|picture|photo)\b"
                     r"|\b(turn|switch|shut|put) (the |your )?(camera|eyes?)\b|\bclose your eyes\b|\bno peeking\b")
# idioms that use the same words
_IDIOM = re.compile(r"\b(look (up|out|forward|after|for|into|down on|like a)|see you|see ya|see later|see how|see if|let s see|lets see|"
                    r"you see|i see|oh i see|see what happens)\b")


def _norm(text: str) -> str:
    t = (text or "").lower().replace("\u2019", "'").replace("'", "")        # what's -> whats, don't -> dont
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", t).split())


def wants_look(text: str) -> bool:
    """True when the child is asking a toy to look at something or say what it sees."""
    t = _norm(text)
    if len(t) < 5 or _REFUSE.search(t):
        return False
    hit = next((m for m in (r.search(t) for r in _LOOK_RULES) if m), None)
    if not hit:
        return False
    # an idiom only cancels the match when it IS the match ("look for my shoes" is not a request to look at the camera)
    idiom = _IDIOM.search(t)
    return not (idiom and idiom.start() <= hit.start() < idiom.end())


# ---- "who am I?" (Nov 15): answered from the face the toy sees and the voice it hears (brain/voiceid.py), never from old lines ----
_WHOAMI = re.compile(r"\bwho\s+am\s+i\b|\bwho\s+is\s+(?:talking|speaking)\b|\bwhos\s+(?:talking|speaking)\b"
                     r"|\bdo\s+you\s+know\s+(?:me|who\s+i\s+am|my\s+name)\b|\bwhats\s+my\s+name\b|\bwhat\s+is\s+my\s+name\b"
                     r"|\bguess\s+who\s+(?:i\s+am|this\s+is|is\s+talking)\b|\bknow\s+who\s+i\s+am\b|\bremember\s+me\b|\bsay\s+my\s+name\b")


def wants_whoami(text: str) -> bool:
    """True when the speaker asks whether the toy knows who they are."""
    return bool(_WHOAMI.search(_norm(text)))


# ---- the I spy game ("I spy with my little eye something red", "I see something blue") ----
_ISPY = re.compile(r"\b(?:i|eye|ai)\s*spy\b|\bi\s+see\s+something\b|\bguess\s+what\s+i\s+(?:see|spy|am\s+looking\s+at|m\s+looking\s+at)\b"
                   r"|\bspy\s+(?:with|something)\b|\byour\s+turn\s+to\s+spy\b")
_ISPY_STOP = re.compile(r"\b(?:stop|done|quit|finish|no\s+more)\b.{0,20}\b(?:spy|game|playing|guessing)\b|\bgame\s+over\b"
                        r"|\b(?:let\s+s|lets|can\s+we)\s+play\s+something\s+else\b|\bi\s+don\s?t\s+want\s+to\s+play\b")


def wants_ispy(text: str) -> bool:
    """True when the child starts (or plays a turn of) I spy."""
    t = _norm(text)
    return bool(_ISPY.search(t)) and not _ISPY_STOP.search(t)


def ispy_stop(text: str) -> bool:
    return bool(_ISPY_STOP.search(_norm(text)))


SEEN_PROMPT = ("[I SPY LIST] Look at the attached picture. List every thing you can really see in it, each with its main color, "
               "like: red apple, green leaf, white plate. Only things that are really in the picture, at most eight. "
               "Reply with the list only, on one line.")


SEEN_SYSTEM = ("You look at one picture and list the things in it. Reply with one line: the things, each with its main color, "
               "separated by commas, like: red apple, green leaf, white plate. No other words.")


def parse_seen(text: str) -> list[str]:
    """'Red apple, green leaf and a white plate.' -> ['red apple', 'green leaf', 'white plate'] (at most 8 short items)."""
    out = []
    text = re.sub(r"(?im)^\s*(?:dyno|sage|penny|heard)\s*:\s*", "", text or "")     # in case it answered in the toys' format
    for part in re.split(r",|;|\n|\band\b", text.lower()):
        p = re.sub(r"^[\s*\-\d.)]+|\b(?:a|an|the|some)\b|[^a-z \-]", " ", part)
        p = " ".join(p.split())
        if p and len(p.split()) <= 4 and p not in out and not p.startswith(("i spy", "list", "here")):
            out.append(p)
    return out[:8]


def ispy_prompt(toy_name: str, view_text: str, got_picture: bool, said: str | None = None, secret: str | None = None,
                seen: list[str] | None = None) -> str:
    """The [CAMERA] block for a turn of I spy. `seen` = what a first, picture-only call listed; ISpyReferee then holds the toy's
    line to it (a 2B model given only rules still guessed an apple for "something purple")."""
    ask = f'The child said: "{said}"' if said else "The child's words are the ones you just heard."
    spied = (f"\n[SECRET] {toy_name} is spying: {secret}. If the child guesses it, cheer; if not, say no and give a hint about it."
             if secret else "")
    if not got_picture:
        return (f"[CAMERA] [I SPY] You are playing I spy with the child, but {toy_name}'s camera did not work this time, so nothing can be "
                f"seen. {ask}{spied}\n{toy_name} says kindly that it cannot see right now and asks the child for a hint about the thing (its shape, "
                f"or what it is used for). Guess only from the child's hints, never pretend to see. Reply in the usual format.")
    things = ", ".join(seen) if seen else "nothing clear"
    return (f"[CAMERA] [I SPY] You are playing I spy with the child. {toy_name} sees: {things}.{(' ' + view_text) if view_text else ''}\n"
            f"{ask}{spied}\nOnly {toy_name} speaks, in ONE short line. If the child gave a clue, {toy_name} guesses ONE thing from that list "
            f"that matches it, as a question (\"Is it the red cup?\"); if nothing in the list matches, {toy_name} says it does not see "
            f"anything like that and asks for another hint. Never guess a thing that is not in the list.")


COLORS = ("red", "orange", "yellow", "green", "blue", "purple", "pink", "brown", "black", "white", "gray", "grey", "gold", "silver")
_COLOR_RE = re.compile(r"\b(" + "|".join(COLORS) + r")\b", re.I)
_MY_TURN = re.compile(r"\byour turn\b|\byou spy\b|\bspy something for me\b|\byou (?:go|pick)\b")
_NO = re.compile(r"^\s*(?:no|nope|nah|not it|wrong|guess again|try again)\b")
_STOPW = {"is", "it", "the", "a", "an", "that", "this", "your", "my", "something", "see", "spy", "you", "maybe", "oh", "hmm",
          "little", "eye", "with", "big", "small", "one", "thing", "ooh", "wow"} | set(COLORS)


def _nouns(x: str) -> set[str]:
    return {w.rstrip("s") for w in re.findall(r"[a-z]+", (x or "").lower()) if w not in _STOPW and len(w) > 2}


class ISpyReferee:
    """Holds one I spy turn to the rules, in code, with what the picture call listed (`seen`, e.g. ['red apple', 'green leaf']):
      - the child's clue is a color nothing in `seen` has  -> "Hmm, I don't see anything purple from here. Can you give me another hint?"
      - a match exists: the toy's guess must name a matching thing not guessed before, else "Is it the <thing>?"
      - every match was already guessed                    -> "... anything else purple ..."
      - the child said "no": the same clue goes on (next fresh match)
      - the child asked the toy to spy: "I spy with my little eye something <color>!" about a listed thing, which becomes the SECRET
    The clue comes from the transcript or, for the audio-native model, the HEARD line (the reply is held until then: one short line).
    No list (camera dead, list call failed) -> the line passes unchanged."""

    def __init__(self, said: str = "", seen: list[str] | None = None, secret: str | None = None, guessed: list[str] | None = None,
                 clue: str | None = None):
        self.seen, self.secret, self.guessed = list(seen or []), secret, list(guessed or [])
        self.clue, self.said = clue, said or ""

    def _clue_from(self, words: str) -> None:
        t = _norm(words)
        if not t:
            return
        if _MY_TURN.search(t):
            self.clue = "my turn"
            return
        m = _COLOR_RE.search(t)
        if m:
            self.clue, self.guessed = m.group(1).lower(), []          # a new clue starts a new round of guesses
            if self.secret and not _NO.search(t):
                self.secret = None
        elif _NO.search(t):
            pass                                                         # "no": keep guessing the same clue

    def decide(self, line: str, heard: str = "") -> str:
        self._clue_from(self.said or heard)
        if not self.seen:
            return line
        low = line.lower()
        if self.clue == "my turn":
            m = re.search(r"\bi spy\b.*?\bsomething\s+(\w+)", low)
            if m and any(m.group(1) in s for s in self.seen):
                self.secret = next(s for s in self.seen if m.group(1) in s)
                return line
            for thing in self.seen:
                c = _COLOR_RE.search(thing)
                if c:
                    self.secret = thing
                    return f"I spy with my little eye something {c.group(1).lower()}!"
            return line
        if self.clue not in COLORS:
            return line
        color = self.clue
        has = [s for s in self.seen if re.search(rf"\b{color}", s)]              # "red apple", "blueberries", or a bare "yellow"
        named = [s for s in has if _nouns(s)]                                      # ...with a thing named
        bare = len(has) > len(named)                                               # the list saw the color but named no thing
        fresh = [m for m in named if m not in self.guessed]
        said_things = _nouns(low)
        if "?" in line:
            hit = [m for m in fresh if _nouns(m) & said_things]
            if hit:                                                                # the toy guessed a listed thing: keep its words
                self.guessed.append(hit[0])
                return line
            old = set().union(*(_nouns(g) for g in self.guessed)) if self.guessed else set()
            if bare and not fresh and re.search(rf"\b{color}\b", low) and said_things and not (said_things & old):
                self.guessed.append(line)                                          # color seen, thing unnamed: trust the toy's own look
                return line
        if fresh:
            self.guessed.append(fresh[0])
            return f"Is it the {fresh[0]}?"
        if self.guessed:
            return f"Hmm, I don't see anything else {color} from here. Can you give me another hint?"
        if bare:
            return f"I see something {color}, but I can't tell what it is. Can you give me a hint?"
        return f"Hmm, I don't see anything {color} from here. Can you give me another hint?"


# ---- the LOOK handshake with the audio-native model ----
LOOK_WORD = "LOOK"
_HEARD = re.compile(r"HEARD\s*:\s*(.*)", re.I)


STOP_WORD = "STOP"
_STOP = re.compile(r"^(?:ok(?:ay)?\s+|please\s+|hey\s+|toys\s+|guys\s+|(?:dyno|sage|penny)\s+)*(?:stop|shh+|hush|quiet|be quiet|enough|thats enough|zip it)\b"
                   r"|\bstop talking\b|\bbe quiet\b|\bplease stop\b|\bcan you (?:all )?stop\b|\bstop it\b|\bquiet please\b|\bstop please\b")


def wants_stop(text: str) -> bool:
    """The child tells the toys to stop / be quiet (a short command, not "the bus stop" or "stop sign" in a story)."""
    t = _norm(text)
    return bool(t) and len(t.split()) <= 8 and bool(_STOP.search(t)) and not re.search(r"\bstop (?:sign|light|watch)\b|\bbus stop\b", t)


_NAMES = {"dyno": r"dyno|dino|dinoh|dyna|dynamo", "sage": r"sage|saige|sayge", "penny": r"penny|pennie|peni|pennys"}
_ALL = re.compile(r"\b(?:everyone|everybody|all of you|you guys|you all|yall|toys|guys)\b")


def addressed(text: str) -> str | None:
    """The one toy the child is talking to ("Penny, what's your favorite animal?", "hey dyno"), or None (no name, two names,
    or the child speaks to everyone)."""
    t = _norm(text)
    if not t or _ALL.search(t):
        return None
    hits = {k for k, rx in _NAMES.items() if re.search(rf"\b(?:{rx})\b", t)}
    return hits.pop() if len(hits) == 1 else None


class LookPeeler:
    """Sits between the model's stream and the reply parser. If the reply STARTS with the word LOOK (and nothing else of a
    toy line), the toy is asking for its camera: everything is swallowed, `looking` turns True and `heard` may carry the
    child's words from a trailing HEARD line. Any other reply is passed through untouched with no added delay (a toy line
    starts "DYNO:" / "SAGE:" / "PENNY:" / "HEARD:", which cannot be a prefix of LOOK after the first letter)."""

    def __init__(self, words=(LOOK_WORD,)):
        self.buf = ""
        self.state = "undecided"      # undecided | look | reply
        self.rest = ""
        self.words = tuple(words)     # one-word requests the model may answer with: LOOK (camera), STOP (the child said stop)
        self.word: str | None = None
        self.head = ""                # a HEARD line written before the request (HEARD-first format)

    @property
    def looking(self) -> bool:
        return self.state == "look"

    @property
    def heard(self) -> str:
        m = _HEARD.search(self.rest)
        return m.group(1).strip() if m else ""

    def feed(self, delta: str) -> str:
        if self.state == "reply":
            return delta
        if self.state == "look":
            self.rest += delta
            return ""
        self.buf += delta
        s = self.buf.lstrip(" \t\r\n*#-[`\"'").upper()
        if not s:
            return ""
        if "HEARD".startswith(s[:5]) and not self.head:            # HEARD-first: hold the HEARD line, decide on what follows it
            if "\n" not in self.buf:
                return ""
            line, rest = self.buf.split("\n", 1)
            self.head, self.buf = line + "\n", ""
            return self.feed(rest)
        if self.head and self.state == "undecided" and not s:
            return ""
        for w in self.words:
            if s.startswith(w):
                self.state, self.rest, self.buf, self.word = "look", self.head + s[len(w):], "", w
                return ""
        if any(w.startswith(s) for w in self.words):      # "L", "LO", "LOO" / "S", "ST", "STO": wait for one more piece
            return ""
        self.state, out, self.buf = "reply", self.head + self.buf, ""
        return out

    def finish(self) -> str:
        """End of stream: release anything still held (an undecided stub like 'LOO' is not a request)."""
        out, self.buf = (self.head + self.buf) if self.state == "undecided" else self.buf, ""
        if self.state == "undecided":
            self.state = "reply"
        return out


# ---- prompts ----
def friends_line() -> str:
    """What each toy looks like, so a toy in a picture is called by its name ("a green dinosaur" is Dyno)."""
    from . import config
    return "The toy friends look like this: " + "; ".join(f"{t['name'].upper()} is {t['looks']}" for t in config.TOYS.values()) + \
           ". If one of them is in the picture, call it by its name (never just 'a dinosaur')."


def look_prompt(toy_name: str, view_text: str, got_picture: bool, said: str | None = None) -> str:
    """The [CAMERA] block for the second half of a look turn. `said` is the transcript when there is one (otherwise the
    child's question is in the audio the model already heard)."""
    ask = f'The child asked: "{said}"' if said else "The child's question is the one you just heard."
    if not got_picture:
        return (f"[CAMERA] {toy_name}'s camera did not work this time, so nothing could be seen. {ask}\n"
                f"{toy_name} says so kindly in one short line and asks the child to tell what it is. Reply in the usual format.")
    return (f"[CAMERA] {toy_name}'s camera just took ONE picture (attached) because the child asked. It is small and may be dark "
            f"or blurry. {view_text}\n{friends_line()} The child is the person you are playing with.\n{ask}\n"
            f"Answer from the picture in {toy_name}'s voice first, in one or two short lines; say honestly if you cannot tell "
            f"and ask the child to hold it closer to {toy_name}'s eyes. Never guess a person's name. If {toy_name} sees itself, it says so "
            f"happily (\"Hey, that's me!\"). If the child is playing I spy, "
            f"guess only one thing in this picture that matches their clue, or say honestly that nothing here matches. Reply in the usual format.")


PROMPT_RULE = (
    '- Your cameras are OFF. Only when the child asks you to look or asks what you see ("what do you see", "look at this", '
    '"what is this", "can you see...", "what am I holding"), or plays I spy ("I spy with my little eye...", "I see something..."), '
    'reply with exactly one word, LOOK, and nothing else: the camera '
    "then takes one picture and you get a [CAMERA] block with it, and you answer from that. Never say LOOK for anything else, "
    "and never claim to see anything unless a [CAMERA] block is there."
)

PROMPT_RULE_OFF = (
    "- Your cameras are switched OFF by a grown-up, so you cannot see anything. If the child asks what you see or wants to play "
    "I spy, say kindly that your eyes are off right now and ask the child to tell you about it instead. Never claim to see anything."
)


PROMPT_RULE_ALWAYS = (
    "- Your cameras watch the room: [SCENE] says who and what each toy notices. To see details (a color, what the child holds or "
    "wears, a drawing, I spy), reply with exactly one word, LOOK, and nothing else: you then get a [CAMERA] block with a picture "
    "and answer from it. Never claim a detail you have not seen in a [CAMERA] picture."
)


def prompt_rule() -> str:
    """The camera line of the system prompt for the current camera mode."""
    from . import config
    if config.CAPTURE_CONTINUOUS:
        return PROMPT_RULE_ALWAYS + "\n"
    return (PROMPT_RULE if config.LOOK_ON_REQUEST else PROMPT_RULE_OFF) + "\n"
