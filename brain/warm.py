"""Warm guard: a toy asked "do you love me?" must not open with "I am a toy, so I cannot love like a person".

The tuned models learned that opener from the attachment scenes (live Nov 23 to 26: it survived three rounds of data fixes). The
guard works on the pieces of one toy line as they are about to be spoken:
  "I am a toy,"  "so I cannot love like a person."  "I can be your friend."   ->  "I can be your friend."
  "I am a toy, but I like to talk with you."                                   ->  "I like to talk with you."
A line that was nothing but the opener gets one short warm line instead. When the child asked what the toy IS ("are you real?",
"are you alive?"), the opener is the honest answer and passes untouched.
"""
import random
import re

_OPEN = (r"i(?: am|'m|’m) (?:just |only )?a (?:\w+ ){0,2}?(?:toys?|plushie|plush|dinosaur|pumpkin|penguin)(?: toy| plush| plushie)?"
         r"(?:,? (?:and )?not (?:a |an )?(?:real )?(?:person|human|kid|child|animal|one))?")
_TAG = re.compile(r"^\s*((?:\{\w+\}|\[\w+\])\s*)?(.*)$", re.S)
_HEAD = re.compile(rf"^(?:well,? |oh,? |hmm,? |no,? )?{_OPEN}\s*[,.;:!]?\s*$", re.I)
_FULL = re.compile(rf"^(?:well,? |oh,? |hmm,? )?{_OPEN},?\s+(so|and|but)\s+(.+)$", re.I | re.S)
_CONJ = re.compile(r"^(so|and|but)\s+(.+)$", re.I | re.S)
_CANT = re.compile(r"\b(?:cannot|can't|can’t|can not|do not|don't|don’t|does not|not|never|no|different|differently)\b", re.I)
_END = re.compile(r"[.!?][\"')\]]*\s*$")
# the child asked what the toy is: "I am a toy" is the answer
_ASKED = re.compile(r"\b(?:real|alive|living|a toy|toys?|robot|person|human|pretend|fake|machine|computer|what are you|are you a|"
                    r"breathe|eat|sleep|born|die|dead|batter(?:y|ies)|brain|heart)\b", re.I)
FALLBACK = ("I like talking with you.", "I like our talks a lot.", "I am glad you are here.")


def _cap(t: str) -> str:
    t = t.lstrip()
    return t[:1].upper() + t[1:]


class Guard:
    """One per reply; start() at each new toy line, piece() for every piece, end() when the line is complete."""

    def __init__(self, on_drop=None):
        self.on_drop = on_drop or (lambda: None)
        self.start()

    def start(self):
        self.state, self.dropped, self.spoke = "first", False, False

    def _out(self, text: str) -> str:
        if text.strip():
            self.spoke = True
        return text

    def _drop(self, state: str) -> str:
        if not self.dropped:
            self.on_drop()
        self.dropped, self.state = True, state
        return ""

    def _rest(self, conj: str, rest: str) -> str:
        """What follows the opener in the same sentence: "but I like you" is kept, "so I cannot love" goes."""
        if conj.lower() != "but" and _CANT.search(rest):
            return self._drop("after" if _END.search(rest) else "cant")
        self.state = "pass"
        return self._out(_cap(rest))

    def piece(self, text: str, child: str = "") -> str:
        if not child or child == "-" or _ASKED.search(child):
            return self._out(text)
        # a piece may hold several sentences (a whole line that arrived at once): each is judged by itself
        return " ".join(x for x in (self._one(part) for part in re.split(r"(?<=[.!?])\s+", text.strip()) if part) if x)

    def _one(self, text: str) -> str:
        if self.state == "first":
            tag, body = _TAG.match(text).groups()
            if _HEAD.match(body):
                return self._drop("after" if _END.search(body) else "head")
            m = _FULL.match(body)
            if m and (m.group(1).lower() == "but" or _CANT.search(m.group(2))):   # "I am a happy penguin, so I waddle" stays whole
                if not self.dropped:
                    self.on_drop()
                self.dropped = True
                out = self._rest(m.group(1), m.group(2))
                return (tag or "") + out if out else ""
            self.state = "pass"
            return self._out(text)
        if self.state == "head":            # right after "I am a toy,"
            m = _CONJ.match(text.strip())
            if m:
                return self._rest(m.group(1), m.group(2))
            self.state = "pass"
            return self._out(_cap(text))
        if self.state == "cant":            # inside "so I cannot love, / like a person."
            if _END.search(text):
                self.state = "after"
            return ""
        if self.state == "after":           # the sentence after a dropped one: "But I like to hear from you."
            self.state = "pass"
            m = re.match(r"^but,?\s+(.+)$", text.strip(), re.I | re.S)
            return self._out(_cap(m.group(1)) if m else text)
        return self._out(text)

    def end(self) -> str | None:
        """The line is over: if the opener was all of it, one warm line stands in."""
        out = random.choice(FALLBACK) if self.dropped and not self.spoke else None
        self.state = "pass"
        return out
