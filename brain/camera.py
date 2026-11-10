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
    r"\b(can|could|do|did|will|would) (you|u|ya|yall) (even )?(see|look)\b",
    r"\b(do|can|could) (you|u) see (me|my|this|that|it|what)\b",
    r"\b(look|looks|looking|peek|peep) (at|over here|here|what)\b",
    r"\b(come|go ahead and|just|quick|please) (and )?look\b",
    r"\b(take|have|get|give it) a (quick |good |little )?(look|peek)\b",
    r"\b(check|checking) (this|that|it|these|those) out\b",
    r"\bwhat( is|s|re| are) (this|that|these|those)\b",
    r"\bwhat( is|s) (it|in my hand|in my hands|on my|in front of you|over here|here)\b(?! (called|time|day))",
    r"\bwhat am i (holding|wearing|showing|pointing)\b",
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


# ---- the LOOK handshake with the audio-native model ----
LOOK_WORD = "LOOK"
_HEARD = re.compile(r"HEARD\s*:\s*(.*)", re.I)


class LookPeeler:
    """Sits between the model's stream and the reply parser. If the reply STARTS with the word LOOK (and nothing else of a
    toy line), the toy is asking for its camera: everything is swallowed, `looking` turns True and `heard` may carry the
    child's words from a trailing HEARD line. Any other reply is passed through untouched with no added delay (a toy line
    starts "DYNO:" / "SAGE:" / "PENNY:" / "HEARD:", which cannot be a prefix of LOOK after the first letter)."""

    def __init__(self):
        self.buf = ""
        self.state = "undecided"      # undecided | look | reply
        self.rest = ""

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
        if s.startswith(LOOK_WORD):
            self.state, self.rest, self.buf = "look", s[len(LOOK_WORD):], ""
            return ""
        if LOOK_WORD.startswith(s):      # "L", "LO", "LOO": wait for one more piece
            return ""
        self.state, out, self.buf = "reply", self.buf, ""
        return out

    def finish(self) -> str:
        """End of stream: release anything still held (an undecided stub like 'LOO' is not a request)."""
        out, self.buf = self.buf, ""
        if self.state == "undecided":
            self.state = "reply"
        return out


# ---- prompts ----
def look_prompt(toy_name: str, view_text: str, got_picture: bool, said: str | None = None) -> str:
    """The [CAMERA] block for the second half of a look turn. `said` is the transcript when there is one (otherwise the
    child's question is in the audio the model already heard)."""
    ask = f'The child asked: "{said}"' if said else "The child's question is the one you just heard."
    if not got_picture:
        return (f"[CAMERA] {toy_name}'s camera did not work this time, so nothing could be seen. {ask}\n"
                f"{toy_name} says so kindly in one short line and asks the child to tell what it is. Reply in the usual format.")
    return (f"[CAMERA] {toy_name}'s camera just took ONE picture (attached) because the child asked. It is small and may be dark "
            f"or blurry. {view_text}\n{ask}\n"
            f"Answer from the picture in {toy_name}'s voice first, in one or two short lines; say honestly if you cannot tell "
            f"and ask the child to hold it closer to {toy_name}'s eyes. Never guess a person's name. Reply in the usual format.")


PROMPT_RULE = (
    '- Your cameras are OFF. Only when the child asks you to look or asks what you see ("what do you see", "look at this", '
    '"what is this", "can you see...", "what am I holding"), reply with exactly one word, LOOK, and nothing else: the camera '
    "then takes one picture and you get a [CAMERA] block with it, and you answer from that. Never say LOOK for anything else, "
    "and never claim to see anything unless a [CAMERA] block is there."
)
