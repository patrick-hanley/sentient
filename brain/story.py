"""Story mode: the child reads (or tells) a story aloud and the toys only add sounds.

"I'm going to read you a story" turns it on. While it is on, a toy never speaks over the reading: after each sentence the
brain plays at most ONE recorded sound that fits the words ("the rain fell" -> rain), or nothing. "The end" turns it off and
a toy says one kind thing about the story; "stop" quiets the toys as always; a question to a toy by name gets one short answer.

The sound is chosen here, in code, from the child's words (the model only reports them). Nothing here is logged or stored.
"""
from __future__ import annotations

import re

# Measured on the real model (Nov 21): with this wording it writes the HEARD line and stops (1.4 s); "the child is reading a
# story ... do not answer" still got three toy lines after it (3-5 s, all thrown away).
LISTEN = "The child just spoke (audio attached). Reply with the HEARD line only. No toy speaks."
LISTEN_SOUNDS = (" If the words name something that makes one of the sound effects, add one more line with only that sound, "
                 'like "DYNO: {rain}". No other words.')


_TAIL = re.compile(r"(?:[\s,.;:!?-]+[A-Z]{3,})+[\s,.;:!?-]*$")     # "...through the window DYNO SAGE PENNY"
_LABEL = re.compile(r"^\s*[*#\-\s]*\[?[A-Z][A-Z ,]{2,30}\]?\s*[*]*\s*:")


def tidy(text: str) -> str:
    """The child's words as the model reported them, without the toy names it sometimes copies from the prompt onto the end
    of the line ("Then they burst through the window DYNO SAGE PENNY")."""
    t = (text or "").strip()
    m = _TAIL.search(t)
    if m and re.search(r"DYNO|SAGE|PENNY|AGE\b", m.group(0)) and m.start() > 0:
        t = t[:m.start()].rstrip(" ,;:-")
        if t and t[-1] not in ".!?":
            t += "."
    return t


def loose(raw: str) -> str:
    """The model forgot the HEARD: label and wrote only the words: the first line that is not a labelled line or a dash."""
    for line in (raw or "").splitlines():
        line = line.strip().strip('"')
        if len(line) > 2 and not _LABEL.match(line) and not line.startswith(("{", "[", "<")):
            return line
    return ""


def _norm(text: str) -> str:
    t = (text or "").lower().replace("’", "'").replace("'", "")
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", t).split())


_ASKS_TOYS = re.compile(r"\b(?:can|could|will|would) you\b|\b(?:read|tell) (?:me|us)\b|\byou (?:read|tell)\b")
_START = re.compile(r"\b(?:im going to|i am going to|im gonna|i will|ill|let me|i want to|can i|may i|i can) (?:read|tell)\b.{0,30}\b(?:story|book|you)\b"
                    r"|\bread(?:ing)? (?:to )?(?:you|yall|everyone|everybody|the toys)\b.{0,30}\b(?:story|book)\b"
                    r"|\blisten to (?:my|this|a|the) (?:story|book)\b|\bhear (?:my|this) (?:story|book)\b"
                    r"|^(?:its |ok(?:ay)? |now )*story ?time\b")


_START_EARS = re.compile(r"\b(?:going to|gonna|want to|let me) read\b.{0,20}\b(?:story|book)\b")     # the first word may be lost


def ears_start(text: str) -> bool:
    """wants_story for the fast recogniser's words (no punctuation, the first word sometimes clipped)."""
    t = _norm(text)
    if not re.search(r"\b(?:story|book)\b|story ?time", t):      # "let me tell you something" is not a story yet
        return False
    return wants_story(text) or (len(t.split()) <= 12 and not _ASKS_TOYS.search(t) and bool(_START_EARS.search(t)))


def wants_story(text: str) -> bool:
    """The child is about to read or tell the toys a story (not asking the toys for one)."""
    t = _norm(text)
    return bool(t) and len(t.split()) <= 16 and not _ASKS_TOYS.search(t) and bool(_START.search(t))


_END = re.compile(r"(?:^|[.!?,;]\s*)(?:and\s+)?(?:that'?s\s+|that is\s+)?the end[.!\s]*$|ever after[,.!]?\s+the end[.!\s]*$", re.I)
_END_N = re.compile(r"\b(?:story|book) is (?:over|done|finished)\b|\b(?:im|i am|were|we are) (?:all )?(?:done|finished)(?: reading| with (?:the|my|this) (?:story|book))?$"
                    r"|\b(?:done|finished) reading\b|\bfinished (?:the|my|this) (?:story|book)\b|\bthats (?:it|all|the whole story)$")


def ends(text: str) -> bool:
    """The story is over: "The end." as its own sentence, "I'm done reading", "the story is over"."""
    return bool(_END.search((text or "").replace("’", "'").strip())) or bool(_END_N.search(_norm(text)))


_END_FAST = re.compile(r"^(?:\w+ )?(?:and )?(?:thats )?the end$")


def fast_end(part: str) -> bool:
    """The fast recogniser's words since the last pause (no punctuation) are "the end" and nothing else. One leftover word in
    front is allowed (the last word before the pause is handed over again), but not "in the end", "at the end"."""
    t = _norm(part)
    return bool(_END_FAST.match(t)) and t.split()[0] not in ("in", "at", "to", "by", "near", "until", "till", "from", "before", "is", "was")


_REPORTED = re.compile(r"\b(?:said|says|cried|shouted|yelled|asked|whispered|replied|called|told|sang|growled|roared)\b")


def is_command(text: str) -> bool:
    """Short and not narration: "Stop!" is the child talking to the toys, '"Stop!" cried the wolf' is the story."""
    t = _norm(text)
    return bool(t) and len(t.split()) <= 4 and not _REPORTED.search(t)


def asks_toy(text: str, name_rx: str) -> bool:
    """The child stops reading to talk to a toy: its name comes first and they ask something or say "you". A character who
    shares a toy's name ("Penny the penguin waddled home") is just the story."""
    t = _norm(text)
    if not re.match(rf"(?:hey |ok(?:ay)? |so )?(?:{name_rx})\b", t) or _REPORTED.search(t):
        return False
    return "?" in text or bool(re.search(r"\b(?:you|your|youre)\b", t))


# sound -> (what the thing DOES, the thing itself). An action ("barked") beats a mention ("the dog").
CUES: dict[str, tuple[str, str]] = {
    "thunder": (r"thunder\w*|lightning", r"storm\w*"),
    "rain": (r"rain\w*|drizzl\w*|pouring", r"puddles?|umbrellas?"),
    "wind": (r"wind (?:blew|howled|whistled|blows)|windy|breeze|gust\w*", r"wind"),
    "knock": (r"knock\w*|rapped (?:on|at)|tapp(?:ed|ing) (?:on|at) the (?:door|window)", r""),
    "doorbell": (r"door ?bell|rang the bell|ding dong", r""),
    "door_creak": (r"creak\w*|door (?:slowly )?(?:opened|swung)|opened the (?:\w+ )?(?:door|gate)", r""),
    "footsteps": (r"foot ?steps?|tip ?toe\w*|stomp\w*|tramp(?:ed|ing|led|ling)|(?:up|down) ?(?:the )?stairs", r""),
    "birds": (r"chirp\w*|tweet\w*|birds? (?:sang|sing|sings|singing)", r"birds?|robins?|sparrows?"),
    "owl": (r"hoot\w*", r"owls?"),
    "dog": (r"bark\w*|woof|bow ?wow", r"dogs?|pupp(?:y|ies)|hounds?"),
    "donkey": (r"bray\w*|hee ?haw", r"donkeys?"),
    "glass": (r"glass (?:clattered|shattered|broke|smashed|crashed)|shatter\w*|smash\w*|broke the window|crash\w*", r""),
    "cat": (r"meow\w*|mew(?:ed|ing|s)?|purr\w*", r"cats?|kitt(?:en|ens|y|ies)"),
    "cow": (r"moo(?:ed|ing|s)?", r"cows?"),
    "pig": (r"oink\w*", r"pigs?|piglets?"),
    "sheep": (r"baa+(?:ed)?|bleat\w*", r"sheep|lambs?"),
    "duck": (r"quack\w*", r"ducks?|ducklings?|duck[iy]e?|\w+ dadd?les?"),
    "hen": (r"cluck\w*", r"hens?|henny|hen+[iy] ?pen+[iy]|honey ?penny|chickens?"),
    "goose": (r"honk\w*", r"goose|geese|goos[ei]y?|gander|\w+ poos\w*"),      # before penguin_honk: a honk is the goose's when both exist
    "turkey": (r"gobbl\w+(?! (?:\w+ ){0,3}up\b)", r"turkeys?|turkey ?lurk\w*|\w+ lurk(?:y|ey|ie)"),   # "gobbled it all up" is eating
    "goat": (r"maa+(?:ed)?", r"(?:billy |nanny )?goats?|billy (?:go|goff|gough|gruff)"),
    "hooves": (r"tr[ia]m?p tr[ia]m?p|clip ?clop\w*|clipp\w* clopp\w*|hoof ?beats?|hoo(?:fs|ves) (?:clattered|pounded|thundered)|gallop\w*|trott\w*", r""),
    "puff": (r"huff\w*|puff\w*|bl(?:ow|ew|own) (?:\w+ )?house (?:in|down)", r""),
    "slurp": (r"slurp\w*|lapp(?:ed|ing) (?:it )?up", r"porridge"),
    "crack": (r"crack\w*|(?:broke|broken) (?:\w+ ){0,2}(?:in|to|into) (?:two|half|pieces|bits)|snapped in (?:two|half)", r""),
    "snore_big": (r"snor\w*|fast asleep|sound asleep", r""),
    "trumpet": (r"trumpet\w*|fanfare|bugles?", r"procession|parade"),
    "crowd": (r"murmur\w*|whisper\w* to (?:one )?another|all the people|the whole (?:town|city|crowd)", r"crowds?"),
    "rooster": (r"cock a doodle doo|crowed|crowing", r"roosters?|cocks?|cockerels?|cocky|\w+ky lock\w*"),
    "frog": (r"ribbit\w*|croak\w*", r"frogs?|toads?"),
    "wolf": (r"howl\w*", r"wolf|wolves"),
    "bee": (r"buzz\w*", r"bees?"),
    "splash": (r"splash\w*|(?:jumped|fell|dived|dove|leaped|hopped|tumbled|tossed|threw|thrown|pushed)(?: \w+){0,2} in(?:to)? the (?:water|pond|lake|river|stream|sea|ocean|pool|puddle|pot|well)", r""),
    "bubbles": (r"bubbl\w*", r""),
    "clock": (r"tick\w* ?tock|ticking|clock struck|clock chimed", r"clocks?"),
    "school_bell": (r"school bell|bell rang|bell rings", r""),
    "applause": (r"clapp\w*|applau\w*|cheered|cheering", r""),
    "yawn": (r"yawn\w*", r""),
    "giggle": (r"giggl\w*|laughed|laughing", r""),
    "sigh": (r"sigh\w*", r""),
    "witch_cackle": (r"cackl\w*", r"witch(?:es)?"),
    "ghost_boo": (r"boo", r"ghosts?"),
    "ghost_moan": (r"moan\w*", r""),      # not "groaned": bridges and chairs groan too
    "cauldron": (r"cauldron|potion", r""),
    "crow": (r"caw\w*", r"crows?|ravens?"),
    "bones": (r"rattl\w*", r"skeletons?|bones"),
    "cat_hiss": (r"hiss\w*", r""),
    "spooky_organ": (r"organ", r"haunted"),
    "monster_laugh": (r"monster laughed|evil laugh", r"monsters?"),
    "bats": (r"bats (?:flew|flapped)", r"bats"),
    "dino_roar": (r"roar\w*", r"dinosaurs?|t ?rex|dragons?|troll\w*|ogres?|giants?"),
    "dino_growl": (r"growl\w*|snarl\w*", r"bears?"),
    "penguin_honk": (r"honk\w*", r"penguins?"),
    "sparkle": (r"sparkl\w*|twinkl\w*|magic wand", r"magic\w*|fair(?:y|ies)"),
    "pumpkin_thump": (r"thump\w*|thud|whack\w*|bonk\w*", r""),
    "candle_flicker": (r"flicker\w*", r"candles?"),
}
_RX = {name: tuple(re.compile(rf"\b(?:{p})\b") if p else None for p in pair) for name, pair in CUES.items()}
_NOT = re.compile(r"\b(?:no|not|never|without|didnt|did not|wasnt|isnt|couldnt|wouldnt|stopped)(?: \w+)?$")
_LIKE = re.compile(r"\blike(?: \w+){0,2}$")     # "a face like three rainy days": a comparison, nothing is raining


def pick(text: str, available=None, skip=()) -> str | None:
    """The one sound that fits these words, or None. An action beats a mention, then the longer match, then the later one.
    `available`: the recordings that exist (None = all); `skip`: sounds played a moment ago (no bark on every sentence)."""
    t = _norm(text)
    best = None
    for name, (act, thing) in _RX.items():
        if (available is not None and name not in available) or name in skip:
            continue
        negated = False
        for strength, rx in ((2, act), (1, thing)):
            if rx is None or negated:
                continue
            for m in rx.finditer(t):
                if _LIKE.search(t[:m.start()].rstrip()):
                    continue
                if strength == 2 and _NOT.search(t[:m.start()].rstrip()):
                    negated = True       # "the dog did not bark": no bark, and no bark for the word "dog" either
                    break
                own = strength == 2 and thing is not None and bool(thing.search(t))   # "the penguin honked": the penguin's honk
                key = (strength, own, m.end() - m.start(), m.start())
                if best is None or key > best[0]:
                    best = (key, name)
        if negated and best and best[1] == name:
            best = None
    return best[1] if best else None


def pick_all(text: str, available=None, skip=(), most: int = 4) -> list[str]:
    """Every sound the words call for, in the order they are read: "the donkey brayed, the dog barked, the cat mewed and
    the rooster crowed" is four sounds. Only actions count here (a sentence that merely mentions a dog and a cat gets one
    sound from pick). Fewer than two actions: the single best sound, as pick gives it."""
    t = _norm(text)
    found = {}
    for name, (act, thing) in _RX.items():
        if act is None or (available is not None and name not in available) or name in skip:
            continue
        for m in act.finditer(t):
            before = t[:m.start()].rstrip()
            if _LIKE.search(before) or _NOT.search(before):
                continue
            other = next((n for n, at in found.items() if at == m.start()), None)     # one word, one sound
            if other is None or (thing is not None and thing.search(t)):
                found.pop(other, None)
                found[name] = m.start()
            break
    if len(found) >= 2:
        return sorted(found, key=found.get)[:most]
    one = pick(text, available, skip)
    return [one] if one else []


def heard_so_far(text: str, final: bool, available=None, skip=()) -> list[str]:
    """Words still arriving from the fast recogniser (brain/storyears.py): the sounds they call for so far, in order. A sound
    starts at its action word ("barked") or as soon as its animal or thing is named ("the donkey ..."): waiting for the verb or
    the pause cost a second, and the recogniser often gets the verb wrong ("mewed" came out as "hued", live Nov 21). The last
    word may be half of a longer one ("boo" of "book", "cat" of "cattle"), so until a pause (final) a name at the very end
    waits for the next word, and so does a short action word."""
    t = _norm(text)
    found, acts, named = {}, {}, set()
    for name, (act, thing) in _RX.items():
        if (available is not None and name not in available) or name in skip:
            continue
        for strong, rx in ((True, act), (False, thing)):
            if rx is None:
                continue
            for m in rx.finditer(t):
                before = t[:m.start()].rstrip()
                if _LIKE.search(before) or (strong and _NOT.search(before)):
                    continue
                if not final and m.end() == len(t) and (not strong or m.end() - m.start() < 5):
                    continue
                found[name] = min(found.get(name, m.start()), m.start())
                acts.setdefault(m.start(), []).append(name) if strong else named.add(name)
                break
    for same in acts.values():       # one word, one sound: "honked" is the penguin's if a penguin is in the sentence, else the
        keep = next((n for n in same if n in named), same[0])     # first in the table (the goose)
        for n in same:
            if n != keep:
                found.pop(n, None)
    return sorted(found, key=found.get)


def trim_lead(pcm: bytes, rate: int = 16000) -> bytes:
    """A recording that starts with quiet starts late: the rooster's crow only got loud 0.63 s in, the frog 0.4 s, the donkey
    0.2 s (Nov 21). Cut to just before the sound reaches a tenth of its peak."""
    import numpy as np
    x = np.frombuffer(pcm, "<i2")
    n = rate // 100
    if len(x) < 4 * n:
        return pcm
    e = np.sqrt((x[:len(x) // n * n].astype(np.float32).reshape(-1, n) ** 2).mean(1))
    first = int(np.argmax(e > 0.1 * e.max()))
    return x[max(0, first - 2) * n:].tobytes()


def model_sound(lines, available=None) -> str | None:
    """A sound the model proposed: a toy line that is ONLY one sound tag (anything with words is not played)."""
    for text in lines or ():
        m = re.fullmatch(r"\s*\{([a-z_]+)\}\s*", text)
        if m and (available is None or m.group(1) in available):
            return m.group(1)
    return None


def end_prompt(told: str, who: str = "") -> str:
    return (f'The child just finished reading you a story. The story was: "{told}"\n'
            f"{who or 'One toy'} says one short, kind thing about a part of the story. Reply with that one line only"
            + (f", starting with {who}:" if who else "."))


def end_line(raw: str) -> str:
    """The model's line about the story, whatever name it put in front (it answered as SAGE when only DYNO and PENNY could
    speak, and the line was lost, live Nov 21)."""
    for ln in reversed((raw or "").splitlines()):
        m = re.match(r"\s*([A-Z]+):\s*(.+)", ln)
        if m and m.group(1) != "HEARD" and len(m.group(2).split()) >= 3:
            return m.group(2).strip()
    return ""


END_LINE = "What a lovely story! Thank you for reading it to me."   # said when the model gives no line at "the end"


def ask_prompt(said: str) -> str:
    return f'The child stopped reading for a moment and said: "{said}"\nAnswer in one short line. Then they will keep reading.'
