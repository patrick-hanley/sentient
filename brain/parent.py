"""Parent Board core: what a parent tells the toys about their child, kept in the house, encrypted, expiring.

Design: docs/parent-board.md. In short:
  * Local only. Profiles live in config.DATA/parent/, encrypted with AES-256-GCM. Nothing leaves the brain.
  * A random data key (DEK) encrypts the profiles; the family PIN only wraps that key (scrypt). Changing the PIN
    re-wraps one small blob, and "delete everything" destroys the wrapped key (crypto-erase) before unlinking files.
  * After a brain restart the key is gone until a parent enters the PIN, so notes are inactive until then. That is the
    price of encryption at rest; with no notes the toys simply play normally.
  * Parent is the only writer. Every item expires or fades. Delete is real, per item.
  * The toys USE notes (a private line in the prompt) and never quote them.
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
import logging
import os
import re
import secrets
import tempfile
import threading
import time

from . import config

log = logging.getLogger("parent")

KDF_N, KDF_R, KDF_P = 2 ** 16, 8, 1     # ~64 MB, ~0.3-0.6 s on a Pi 5 (stored per install, so it can be raised later)
MIN_PIN = 6            # a phrase or anything with a non-digit; all-digit PINs need MIN_DIGITS (10^8 guesses, not 10^6)
MIN_DIGITS = 8
SESSION_IDLE_S = 300
BIND_IDLE_S = 1800
KINDS = ("interest", "hobby", "school", "reading", "boundary", "routine", "goal", "fact", "profile", "care", "person")
# The schema: every item is {id, kind, text, detail, due, weekday, time, scope, source, added, confirmed}; the CATEGORY is derived
# from the kind (so older profiles need no migration) and is what the board shows and the prompt is ordered by.
CATEGORIES = [("about", "About them"), ("interests", "Interests"), ("school", "School & learning"), ("schedule", "Schedule & routines"),
              ("care", "Care & comfort"), ("people", "People & pets"), ("boundaries", "Boundaries"), ("other", "Other")]
KIND_CATEGORY = {"profile": "about", "interest": "interests", "school": "school", "reading": "school", "goal": "school",
                 "hobby": "schedule", "routine": "schedule", "care": "care", "person": "people", "boundary": "boundaries", "fact": "other"}
CATEGORY_KIND = {"about": "profile", "interests": "interest", "school": "goal", "schedule": "routine", "care": "care",
                 "people": "person", "boundaries": "boundary", "other": "fact"}   # the kind a card gets when a parent moves it to a category
PROMPT_ORDER = ["boundaries", "care", "school", "schedule", "about", "people", "interests", "other"]   # what to keep first if the notes are long
NOTES_MAX_ITEMS, NOTES_MAX_CHARS = 16, 1100
CHILD_KINDS = ("interest", "hobby", "school", "reading", "fact")   # what the child can teach the toys: never rules or routines
CHILD_MAX = 25                                                       # remembered things per child; the oldest go first
COLORS = ["#e76f51", "#2a9d8f", "#e9c46a", "#264653", "#8ab17d", "#b5838d", "#6d6875", "#f4a261"]
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
DAY_ABBR = {"mon": 0, "tue": 1, "tues": 1, "wed": 2, "thu": 3, "thur": 3, "thurs": 3, "fri": 4, "sat": 5, "sun": 6}

# how long an item stays active without being re-confirmed (days); None = until the parent removes it
STALE_DAYS = {"interest": 28, "hobby": 84, "reading": 120, "routine": None, "goal": None, "boundary": None, "school": None, "fact": 180, "profile": 365, "care": None, "person": None}
PURGE_AFTER_STALE_DAYS = 14

_LABELS = re.compile(r"\b(DYNO|SAGE|PENNY|HEARD|SCENE|EVENT|TOYS HERE|HEARD BY)\b\s*:", re.I)


class Locked(Exception):
    pass


class WrongPin(Exception):
    pass


class RateLimited(Exception):
    def __init__(self, seconds):
        super().__init__(f"Too many tries. Wait {int(seconds)} seconds.")
        self.seconds = seconds


def safe_text(s, maxlen: int = 80) -> str:
    """Parent text as it may appear in a prompt: one line, no brackets or role labels that could confuse the reply format."""
    s = re.sub(r"[\x00-\x1f\x7f]", " ", str(s or ""))
    s = _LABELS.sub(" ", s)
    s = re.sub(r"[\[\]<>{}\\`|]", " ", s)
    return " ".join(s.split())[:maxlen].strip()


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


def _unb64(s: str) -> bytes:
    return base64.b64decode(s.encode())


def _crypto():
    try:
        from cryptography.exceptions import InvalidTag
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
        return AESGCM, Scrypt, InvalidTag
    except ImportError:
        return None


def available() -> bool:
    return _crypto() is not None


def _kek(pin: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    _, Scrypt, _ = _crypto()
    return Scrypt(salt=salt, length=32, n=n, r=r, p=p).derive(pin.encode())


def _wipe_file(path):
    try:
        size = os.path.getsize(path)
        with open(path, "r+b") as f:
            f.write(b"\0" * size)
            f.flush()
            os.fsync(f.fileno())
    except OSError:
        pass
    try:
        os.unlink(path)
    except OSError:
        pass


def _atomic_write(path, data: bytes):
    d = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp-")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ----------------------------------------------------------------------------------------------------------
# dates and expiry
# ----------------------------------------------------------------------------------------------------------
def _today(now: float) -> dt.date:
    return dt.datetime.fromtimestamp(now).date()


def _iso(now: float) -> str:
    return dt.datetime.fromtimestamp(now).isoformat(timespec="minutes")


def _parse_iso(s) -> float | None:
    try:
        return dt.datetime.fromisoformat(s).timestamp()
    except (TypeError, ValueError):
        return None


def item_state(item: dict, now: float) -> str:
    """'active', 'stale' (not used any more, shown for re-confirmation) or 'expired' (to be purged)."""
    kind = item.get("kind")
    today = _today(now)
    if kind == "school":
        due = item.get("due")
        if due:
            try:
                if today > dt.date.fromisoformat(due):
                    return "expired"
            except ValueError:
                return "expired"
        elif now - (_parse_iso(item.get("added")) or now) > 7 * 86400:
            return "expired"
        return "active"
    if kind == "boundary" and item.get("scope") == "today":
        added = _parse_iso(item.get("added")) or now
        return "active" if dt.datetime.fromtimestamp(added).date() == today else "expired"
    if kind == "hobby" and item.get("due"):   # a one-off event, not recurring
        try:
            return "expired" if today > dt.date.fromisoformat(item["due"]) else "active"
        except ValueError:
            return "expired"
    days = STALE_DAYS.get(kind)
    if kind == "fact" and item.get("source") == "child":
        days = 56          # something a child said fades faster than something a parent wrote
    if days is None:
        return "active"
    age = (now - (_parse_iso(item.get("confirmed")) or _parse_iso(item.get("added")) or now)) / 86400
    if age <= days:
        return "active"
    return "stale" if age <= days + PURGE_AFTER_STALE_DAYS else "expired"


def _fmt_time(t: str | None) -> str:
    if not t:
        return ""
    try:
        h, m = (int(x) for x in t.split(":"))
    except ValueError:
        return ""
    return f"{(h % 12) or 12}{'' if m == 0 else ':%02d' % m}{'am' if h < 12 else 'pm'}"


def _day_name(item: dict, now: float) -> str:
    if item.get("due"):
        try:
            d = dt.date.fromisoformat(item["due"])
            delta = (d - _today(now)).days
            if delta == 0:
                return "today"
            if delta == 1:
                return "tomorrow"
            return d.strftime("%A") if 0 < delta < 7 else d.strftime("%A %b %d").replace(" 0", " ")
        except ValueError:
            return ""
    if item.get("weekday") is not None:
        return WEEKDAYS[item["weekday"]].title() + "s"
    return ""


def describe(item: dict, now: float) -> str:
    """Parent-facing one-liner for a card or list row (items the child told the toys say so)."""
    out = _describe(item, now)
    return out + (" (told to the toys by the child)" if item.get("source") == "child" else "")


def _describe(item: dict, now: float) -> str:
    k, t = item["kind"], item["text"]
    day, tm = _day_name(item, now), _fmt_time(item.get("time"))
    if k == "interest":
        return f"Loves {t}"
    if k == "hobby":
        return f"{t.title()}" + (f" - {day}" if day else "") + (f" {tm}" if tm else "")
    if k == "school":
        return f"{t[:1].upper() + t[1:]}" + (f" - {day}" if day else "") + (f" (words: {item['detail']})" if item.get("detail") else "")
    if k == "reading":
        return f"Reads {t}"
    if k in ("fact", "person"):
        return t[:1].upper() + t[1:]
    if k == "profile":
        return "About: " + t
    if k == "care":
        return "Care: " + t
    if k == "boundary":
        return f"Keep it: {t}" + (" (today)" if item.get("scope") == "today" else "")
    if k == "routine":
        return f"Routine: {t}" + (f" {tm}" if tm else "")
    return f"Goal: {t}"


def prompt_phrase(item: dict, now: float) -> str:
    """The private note for Gemma: meaning, not a quotation."""
    k, t = safe_text(item["text"]), item["text"]
    day, tm = _day_name(item, now), _fmt_time(item.get("time"))
    if k and k != t:
        t = k
    t = safe_text(t)
    if k == t and item["kind"] == "interest":
        return f"loves {t}"
    kind = item["kind"]
    if kind == "interest":
        return f"loves {t}"
    if kind == "hobby":
        return f"{t} {day} {tm}".strip()
    if kind == "school":
        words = safe_text(item.get("detail") or "", 120)
        return f"{t} {day}".strip() + (f" (words: {words})" if words else "")
    if kind == "reading":
        return f"reads {t}"
    if kind in ("fact", "person", "profile"):
        return t
    if kind == "care":
        return f"be mindful: {t}"
    if kind == "boundary":
        return f"keep it {t}" + (" today" if item.get("scope") == "today" else "")
    if kind == "routine":
        return f"{t} {tm}".strip()
    return f"parent would like practice: {t} (suggest it once, gently)"


# ----------------------------------------------------------------------------------------------------------
# parsing a sentence into cards (rules first, deterministic and testable; the parent confirms every card)
# ----------------------------------------------------------------------------------------------------------
_HOUR_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
               "eleven": 11, "twelve": 12, "noon": 12}
_SUBJECTS = r"(spelling|math|maths|reading|times tables?|science|history|vocab(?:ulary)?|writing|geography|phonics|art)"
_ACTIVITIES = ("soccer|football|piano|swimming|swim|dance|ballet|karate|gymnastics|violin|guitar|chess|scouts|basketball|"
               "tennis|baseball|hockey|coding|drama|choir|band|judo|cricket|rugby|skating|climbing|theatre|theater|art club")
_DAYRE = r"(mon(?:day)?s?|tue(?:s(?:day)?)?s?|wed(?:nesday)?s?|thu(?:r(?:s(?:day)?)?)?s?|fri(?:day)?s?|sat(?:urday)?s?|sun(?:day)?s?)"


def _weekday(word: str) -> int | None:
    w = word.lower()
    for i, name in enumerate(WEEKDAYS):
        if w.startswith(name[:3]):
            return i
    return None


_PLURAL_DAY = re.compile(r"\b(mon|tues|wednes|thurs|fri|satur|sun)days\b")
_CLAUSEY = re.compile(r"\b(is|are|was|has|have|goes|go|at|on|test|quiz|exam|homework|tomorrow|today|tonight)\b|\d|" + _DAYRE)


def _next_date(now: float, wd: int | None = None, word: str | None = None) -> str | None:
    today = _today(now)
    if word == "today":
        return today.isoformat()
    if word == "tomorrow":
        return (today + dt.timedelta(days=1)).isoformat()
    if wd is None:
        return None
    return (today + dt.timedelta(days=(wd - today.weekday()) % 7)).isoformat()


def _find_time(s: str) -> str | None:
    m = re.search(r"\bat\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", s) or re.search(r"\bat\s+(" + "|".join(_HOUR_WORDS) + r")(?:\s+(?:o'?clock|(am|pm)))?\b", s)
    if not m:
        return None
    h = _HOUR_WORDS.get(m.group(1)) or int(m.group(1))
    mins = int(m.group(2)) if m.lastindex and m.lastindex >= 2 and m.group(2) and m.group(2).isdigit() else 0
    ap = m.group(m.lastindex) if m.lastindex and m.group(m.lastindex) in ("am", "pm") else None
    if ap == "pm" and h < 12:
        h += 12
    elif ap == "am" and h == 12:
        h = 0
    elif ap is None and 1 <= h <= 7:
        h += 12   # "at four" for an activity means the afternoon
    return f"{h:02d}:{mins:02d}" if 0 <= h < 24 and 0 <= mins < 60 else None


def _items_from_list(raw: str) -> list[str]:
    raw = re.sub(r"\b(and|also|plus|as well as)\b", ",", raw)
    out = []
    for part in raw.split(","):
        p = re.sub(r"^(the|a|an|some|to|playing|doing)\s+", "", part.strip().lower())
        p = " ".join(p.split()[:4])
        if p and p not in ("him", "her", "them", "it"):
            out.append(p)
    return out


def parse_text(text: str, now: float | None = None) -> dict:
    """One freeform sentence -> suggested cards. Nothing is saved: the parent confirms each card."""
    now = now or time.time()
    cards, unparsed = [], []
    for sent in re.split(r"[.;!?\n]+", text):
        s = sent.strip()
        if not s:
            continue
        low = s.lower()
        found = []
        # school: "spelling test Friday", "math quiz tomorrow", "homework due Thursday"
        clauses = [c for c in re.split(r",|\bbut\b", low) if c.strip()]
        m = re.search(_SUBJECTS + r"\s+(test|quiz|exam)\b", low)
        hw = re.search(r"\bhome ?work\b", low)
        if m or hw:
            anchor = (m or hw).group(0)
            clause = next((c for c in clauses if anchor in c), low)   # the day belongs to the clause with the test, not another fact
            day = re.search(r"\b" + _DAYRE + r"\b", clause)
            word = "tomorrow" if "tomorrow" in clause else ("today" if re.search(r"\b(today|tonight)\b", clause) else None)
            words = re.search(r"words?\s*(?:are|:)\s*([a-z' ,\-]+)", low)
            found.append({"kind": "school", "text": f"{m.group(1)} {m.group(2)}" if m else "homework",
                          "due": _next_date(now, _weekday(day.group(1)) if day else None, word),
                          "detail": ", ".join(w.strip() for w in re.split(r"[,\s]+and\s+|,", words.group(1)) if w.strip())[:120] if words else None})
        # hobbies on a weekday ("soccer is Tuesdays at four" is recurring; "soccer Tuesday" is that one day)
        for clause in clauses:
            for am in re.finditer(r"\b(" + _ACTIVITIES + r")\b", clause):
                day = re.search(r"\b" + _DAYRE + r"\b", clause)
                word = "tomorrow" if "tomorrow" in clause else None
                if day or word:
                    recurring = bool(day and (_PLURAL_DAY.search(clause) or re.search(r"\b(every|each)\s+" + _DAYRE, clause)))
                    wd = _weekday(day.group(1)) if day else None
                    found.append({"kind": "hobby", "text": am.group(1), "weekday": wd if recurring else None,
                                  "due": None if recurring else _next_date(now, wd, word), "time": _find_time(clause)})
                elif re.search(r"\b(loves?|likes?|plays?|into|enjoys?)\b", clause):
                    found.append({"kind": "interest", "text": am.group(1)})
        # interests
        im = re.search(r"\b(?:loves?|likes?|is really into|really into|is into|obsessed with|fan of|enjoys?|adores?)\s+([^.;!?]+)", low)
        if im:
            for item in _items_from_list(re.split(r"\b(?:but|so|because|then)\b", im.group(1))[0]):
                if _CLAUSEY.search(item):
                    break   # the list ended: what follows is another fact, handled by its own rule
                if not any(c["text"] == item for c in found):
                    found.append({"kind": "interest", "text": item})
        # boundaries
        bounds = []
        if re.search(r"\bquiet(er)?\b", low):
            bounds.append("quiet voices")
        if re.search(r"\bgentle|calm(er)?\b", low):
            bounds.append("gentle")
        if re.search(r"\b(no|nothing|not|avoid|without)\s+(scary|spooky|frightening)\b", low):
            bounds.append("nothing scary")
        if re.search(r"\btired\b", low):
            bounds.append("gentle, a bit tired")
        for b in dict.fromkeys(bounds):
            found.append({"kind": "boundary", "text": b,
                          "scope": "standing" if re.search(r"\b(always|every day|from now on|all the time)\b", low) else "today"})
        # routine
        rm = re.search(r"\b(bed ?time|quiet time|nap ?time|dinner|bath ?time)\b.*?\bat\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm)?|" + "|".join(_HOUR_WORDS) + r")", low)
        if rm and not any(f["kind"] == "school" for f in found):
            found.append({"kind": "routine", "text": re.sub(r"\s+", " ", rm.group(1)), "time": _find_time("at " + rm.group(2))})
        # reading level
        rl = re.search(r"\breads?\s+((?:short |early |easy )?(?:chapter books|picture books|readers?)|(?:at )?[a-z0-9 ]{0,18}level)", low)
        if rl:
            found.append({"kind": "reading", "text": rl.group(1).strip()})
        # goal
        gm = re.search(r"\b(?:practi[cs]e|working on|needs to practi[cs]e|learn(?:ing)?)\s+([a-z' ]{3,30})", low)
        if gm and not any(f["kind"] == "school" for f in found):
            found.append({"kind": "goal", "text": " ".join(gm.group(1).split()[:4]).strip()})
        if found:
            cards += found
        else:
            unparsed.append(s)
    # tidy: drop duplicates, normalise
    seen, out = set(), []
    for c in cards:
        c.setdefault("detail", None); c.setdefault("due", None); c.setdefault("weekday", None); c.setdefault("time", None)
        c.setdefault("scope", "standing")
        c["text"] = safe_text(c["text"], 60)
        key = (c["kind"], c["text"], c["due"], c["weekday"])
        if c["text"] and key not in seen:
            seen.add(key)
            c["label"] = describe(dict(c, kind=c["kind"]), now)
            out.append(c)
    return {"cards": out, "unparsed": unparsed}


_SENSITIVE = re.compile(r"\b(hurt|hurts|scared|afraid|sad|cry|crying|hate|hit me|hits me|bully|bullied|sick|ill|doctor|hospital|"
                        r"address|phone|password|email|live at|lives at|street|secret|private|die|dead|kill|stupid|dumb|"
                        r"mummy|mommy|mum|mom|daddy|dad)\b|\d{4,}", re.I)
_PET = re.compile(r"\bmy\s+(dog|cat|puppy|kitten|hamster|rabbit|fish|bird|horse|turtle|guinea pig)\s+(?:is\s+)?(?:called|named)\s+([A-Za-z]{2,14})\b", re.I)
_HAVEPET = re.compile(r"\bi\s+have\s+a\s+(dog|cat|puppy|kitten|hamster|rabbit|fish|bird|horse|turtle|guinea pig)\s+(?:called|named)\s+([A-Za-z]{2,14})\b", re.I)
_FAV = re.compile(r"\bmy\s+favou?rite\s+([a-z ]{3,16}?)\s+is\s+(?:the\s+|a\s+|an\s+)?([a-z][a-z' ]{1,24}?)(?:[.!?,]|$|\s+and\b)", re.I)


def parse_child(text: str, now: float | None = None) -> list[dict]:
    """What a child said in the first person -> cards of the kinds a child may teach the toys. Same card shape as the parent's.
    Anything about feelings, health, family members, addresses or other people is deliberately not kept."""
    now = now or time.time()
    s = " ".join((text or "").split())
    if not s or len(s) > 300 or _SENSITIVE.search(s):
        return []
    cards = []
    for rx in (_PET, _HAVEPET):
        for m in rx.finditer(s):
            cards.append({"kind": "fact", "text": f"has a {m.group(1).lower()} named {m.group(2).title()}"})
    for m in _FAV.finditer(s):
        cards.append({"kind": "interest", "text": f"{m.group(2).strip().lower()} (favourite {m.group(1).strip().lower()})"})
    # reuse the parent's rules after turning "I love ..." / "I have a spelling test on Friday" into the parent's third person
    third = re.sub(r"\bi'?m\b|\bi am\b", "child is", s, flags=re.I)
    third = re.sub(r"\bi\s+(really\s+)?(love|like|enjoy|adore)\b", lambda m: "child " + (m.group(1) or "") + m.group(2) + "s", third, flags=re.I)
    third = re.sub(r"\bi\s+(have|got)\b", "child has", third, flags=re.I)
    third = re.sub(r"\bi\s+play\b", "child plays", third, flags=re.I)
    third = re.sub(r"\bi\s+read\b", "child reads", third, flags=re.I)
    if re.search(r"\bchild\b", third):
        for c in parse_text(third, now)["cards"]:
            if c["kind"] in ("interest", "hobby", "school", "reading") and not _SENSITIVE.search(c["text"]):
                if c["kind"] == "school":
                    c["due"] = c.get("due")
                cards.append({k: c.get(k) for k in ("kind", "text", "detail", "due", "weekday", "time")})
            elif c["kind"] == "goal":
                cards.append({"kind": "fact", "text": "is learning " + c["text"]})
    seen, out = set(), []
    for c in cards:
        c["text"] = safe_text(c["text"], 60)
        key = (c["kind"], c["text"].lower())
        if c["kind"] in CHILD_KINDS and c["text"] and key not in seen and c["text"].lower() not in ("it", "that", "this", "them", "you"):
            seen.add(key)
            out.append(c)
    return out[:5]


# ----------------------------------------------------------------------------------------------------------
# context dump -> cards in categories: rules first (deterministic), then the local Gemma for what the rules missed
# ----------------------------------------------------------------------------------------------------------
_PETS = "dog|cat|puppy|kitten|hamster|rabbit|fish|bird|horse|turtle|guinea pig|lizard|snake"
_RELS = "brother|sister|cousin|grandma|grandpa|grandmother|grandfather|nana|nanny|granny|gran|aunt|auntie|uncle|best friend|friend|teacher|babysitter|nanny"
_GRADES = {"kindergarten": "kindergarten", "first": "1st", "second": "2nd", "third": "3rd", "fourth": "4th", "fifth": "5th", "sixth": "6th"}


def _extra_rules(seg: str) -> list[dict]:
    """Cards the base parser does not know: about, care, people. Case is kept so names stay capitalised."""
    low, out = seg.lower(), []
    others = re.search(r"\b(" + _RELS + "|" + _PETS + r")\b", low)    # "her sister Ella is 4" is not the child's age
    m = re.search(r"\b(\d{1,2})[- ]?(?:years?|yrs?)[- ]?old\b|\bage[d]?\s+(\d{1,2})\b" + ("" if others else r"|\bis\s+(\d{1,2})\b(?!\s*(?:am|pm|:))"), low)
    if m and others and not re.search(r"\b(she|he|they)\s+is\b|\bage[d]?\b", low):
        m = None
    if m:
        out.append({"kind": "profile", "text": f"{next(g for g in m.groups() if g)} years old"})
    g = re.search(r"\b(?:in\s+)?(?:(\d{1,2})(?:st|nd|rd|th)\s+(?:grade|year)|(kindergarten|first|second|third|fourth|fifth|sixth)\s+(?:grade|year)|(?:grade|year)\s+(\d{1,2})|(kindergarten))\b", low)
    if g:
        v = g.group(1) or g.group(3) or _GRADES.get(g.group(2) or g.group(4) or "", "")
        if v:
            out.append({"kind": "profile", "text": "in kindergarten" if v == "kindergarten" else (f"in {v} grade" if v[-2:] in ("st", "nd", "rd", "th") else f"in grade {v}")})
    m = re.search(r"\b(?:goes by|likes to be called|prefers to be called|nickname is|nicknamed)\s+([A-Z][a-z]{1,12})\b", seg)
    if m:
        out.append({"kind": "profile", "text": f"goes by {m.group(1)}"})
    for m in re.finditer(r"\ballerg(?:ic|y|ies)\s+(?:to\s+)?([a-z][a-z ,]{2,40}?)(?=[.;!?]|$|\bbut\b)", low):
        out.append({"kind": "care", "text": "allergic to " + " ".join(m.group(1).replace(" and ", ", ").split())})
    m = re.search(r"\b(?:is|are)?\s*(?:afraid|scared|frightened|nervous)\s+(?:of|about)\s+([a-z][a-z ]{2,30}?)(?=[.;!?,]|$|\bbut\b|\band\b)", low)
    if m:
        out.append({"kind": "care", "text": "afraid of " + m.group(1).strip()})
    if re.search(r"\b(shy|anxious|sensitive|easily upset|gets overwhelmed)\b", low):
        out.append({"kind": "care", "text": "can be " + re.search(r"\b(shy|anxious|sensitive|easily upset|gets overwhelmed)\b", low).group(1) + ", go gently"})
    for m in re.finditer(r"\b(?i:(?:has|have|got)\s+an?\s+|(?:his|her|their)\s+)(?i:(" + _PETS + r"))\s+(?:is\s+)?(?:called|named)\s+([A-Z][a-z]{1,14})\b", seg):
        out.append({"kind": "person", "text": f"{m.group(1).lower()} named {m.group(2)}"})
    for m in re.finditer(r"\b(?i:(?:(?:his|her|their)\s+)?(" + _RELS + r"))\s+(?:is\s+)?(?:called\s+|named\s+)?((?:(?:Mrs?|Ms|Miss|Dr)\.?\s+)?[A-Z][a-z]{1,14})\b", seg):
        out.append({"kind": "person", "text": f"{m.group(1).lower()} {m.group(2).replace('.', '')}"})
    return out


def _segments(text: str) -> list[str]:
    segs = []
    for line in re.split(r"[\n\r]+", text):
        line = re.sub(r"^\s*(?:[-*\u2022]|\d+[.)])\s*", "", line).strip()
        for sent in re.split(r"(?<=[.!?;])\s+", line):
            if sent.strip(" .!?;"):
                segs.append(sent.strip())
    return segs[:60]


def _tidy(cards: list[dict], now: float) -> list[dict]:
    seen, out = set(), []
    for c in cards:
        c.setdefault("detail", None); c.setdefault("due", None); c.setdefault("weekday", None); c.setdefault("time", None)
        c.setdefault("scope", "standing")
        c["text"] = safe_text(c["text"], 60)
        c["category"] = KIND_CATEGORY.get(c["kind"], "other")
        key = (c["kind"], c["text"].lower(), c["due"], c["weekday"])
        if c["text"] and c["kind"] in KINDS and key not in seen:
            seen.add(key)
            c["label"] = describe(dict(c), now)
            out.append(c)
    return out


def parse_dump(text: str, now: float | None = None) -> dict:
    """A parent's pile of context -> {cards, unparsed}. Rules only (Gemma is added by sort_dump); nothing is saved."""
    now = now or time.time()
    cards, unparsed = [], []
    for seg in _segments(text[:6000]):
        found = parse_text(seg, now)["cards"] + _extra_rules(seg)
        for c in found:      # in a dump a rule is standing unless it says today; a one-off tone needs the word
            if c["kind"] == "boundary" and not re.search(r"\b(today|tonight|this (morning|afternoon|evening))\b", seg, re.I):
                c["scope"] = "standing"
        if found:
            cards += found
        else:
            unparsed.append(seg)
    return {"cards": _tidy(cards, now), "unparsed": unparsed}


_SORT_SYSTEM = ("You file a parent's notes about their child for a toy that plays with the child. Reply with ONLY a JSON array, no prose. "
                "Each item: {\"category\": one of about|interests|school|schedule|care|people|boundaries|other, \"text\": under 8 words, "
                "plain and factual, \"day\": optional weekday name, \"time\": optional HH:MM 24-hour}. "
                "about=age, grade, nickname, personality. interests=loves/likes. school=tests, homework, subjects, reading level, goals. "
                "schedule=activities, routines, events. care=allergies, fears, comfort, sleep, sensitivities. people=family, pets, friends by first name. "
                "boundaries=topics or tones to avoid, rules. other=anything useful that fits nowhere. Skip addresses, phone numbers, "
                "last names, money and anything that is not useful for playing with a child. Never invent facts.")


def _gemma_sort(llm, segments: list[str], now: float) -> list[dict]:
    """Ask the local model to file the sentences the rules could not. Strictly validated: unknown categories, long or odd text are dropped."""
    prompt = "Notes:\n" + "\n".join("- " + safe_text(x, 200) for x in segments[:20]) + "\n\nJSON array:"
    out = llm.complete(prompt, system=_SORT_SYSTEM, max_tokens=500) or ""
    m = re.search(r"\[.*\]", out, re.S)
    if not m:
        return []
    try:
        raw = json.loads(m.group(0))
    except ValueError:
        return []
    cards = []
    for r in raw[:20] if isinstance(raw, list) else []:
        if not isinstance(r, dict) or r.get("category") not in CATEGORY_KIND or not isinstance(r.get("text"), str):
            continue
        text = safe_text(r["text"], 60)
        if not text or re.search(r"\d{5,}|@", text):
            continue
        c = {"kind": CATEGORY_KIND[r["category"]], "text": text, "ai": True}
        wd = _weekday(str(r.get("day") or "")) if r.get("day") else None
        if wd is not None:
            c["weekday"] = wd
        t = _find_time("at " + str(r["time"])) if r.get("time") else None
        if t:
            c["time"] = t
        cards.append(c)
    return cards


# ----------------------------------------------------------------------------------------------------------
# the store
# ----------------------------------------------------------------------------------------------------------
class Parent:
    def __init__(self, directory=None, now=time.time, activity=None, kdf=(KDF_N, KDF_R, KDF_P)):
        self.dir = os.fspath(directory or (config.DATA / "parent"))
        os.makedirs(self.dir, mode=0o700, exist_ok=True)
        self.now = now
        self.activity = activity or (lambda: 0.0)   # last time the toys were active (director.last_activity)
        self.kdf = kdf
        self._lock = threading.RLock()
        self._dek: bytes | None = None
        self.index = {"children": [], "settings": {"checkin_day": 6, "checkin_hour": 18, "notes_on": True}}
        self.items: dict[str, list] = {}
        self.sessions: dict[str, float] = {}
        self.bound: str | None = None
        self.bound_at = 0.0
        self.jobs: dict[str, dict] = {}
        self.setup_code = None if self.configured() else secrets.token_hex(3).upper()   # one-time, printed in the brain's log
        self._announce()

    def _announce(self):
        if self.setup_code:
            log.warning("Parent Board setup code (needed once, to choose the family PIN): %s", self.setup_code)

    # ---- files ----
    def _meta_path(self):
        return os.path.join(self.dir, "meta.json")

    def _meta(self) -> dict | None:
        try:
            with open(self._meta_path()) as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    def _save_meta(self, meta: dict):
        _atomic_write(self._meta_path(), json.dumps(meta).encode())

    def configured(self) -> bool:
        return self._meta() is not None and (self._meta() or {}).get("wrapped") is not None

    def unlocked(self) -> bool:
        return self._dek is not None

    def status(self) -> dict:
        lock = self._lockstate()
        return {"crypto": available(), "configured": self.configured(), "unlocked": self.unlocked(),
                "locked_for": max(0, int(lock.get("locked_until", 0) - self.now())), "min_pin": MIN_PIN, "min_digits": MIN_DIGITS,
                "needs_code": bool(self.setup_code) and not self.configured()}

    # ---- crypto ----
    def _seal(self, key: bytes, plain: bytes, aad: bytes) -> bytes:
        AESGCM, _, _ = _crypto()
        nonce = secrets.token_bytes(12)
        return b"SPB1" + nonce + AESGCM(key).encrypt(nonce, plain, aad)

    def _open(self, key: bytes, blob: bytes, aad: bytes) -> bytes:
        AESGCM, _, InvalidTag = _crypto()
        if blob[:4] != b"SPB1":
            raise ValueError("unknown format")
        try:
            return AESGCM(key).decrypt(blob[4:16], blob[16:], aad)
        except InvalidTag as e:
            raise WrongPin() from e

    def _file(self, name):
        return os.path.join(self.dir, name)

    def _write_index(self):
        _atomic_write(self._file("index.enc"), self._seal(self._dek, json.dumps(self.index).encode(), b"index"))

    def _write_items(self, cid):
        _atomic_write(self._file(f"child-{cid}.enc"), self._seal(self._dek, json.dumps(self.items.get(cid, [])).encode(), f"child-{cid}".encode()))

    def _load_all(self):
        with open(self._file("index.enc"), "rb") as f:
            self.index = json.loads(self._open(self._dek, f.read(), b"index"))
        self.index.setdefault("settings", {}).setdefault("notes_on", True)
        self.items = {}
        for c in self.index["children"]:
            try:
                with open(self._file(f"child-{c['id']}.enc"), "rb") as f:
                    self.items[c["id"]] = json.loads(self._open(self._dek, f.read(), f"child-{c['id']}".encode()))
            except OSError:
                self.items[c["id"]] = []

    # ---- PIN, lockout, sessions ----
    def _check_pin_policy(self, pin: str):
        need = MIN_DIGITS if isinstance(pin, str) and pin.isdigit() else MIN_PIN
        if not isinstance(pin, str) or len(pin) < need or len(pin) > 64:
            raise ValueError(f"Use at least {MIN_DIGITS} digits, or {MIN_PIN} characters with a letter (a short phrase is stronger).")

    def _lockfile(self):
        return self._file("lock.json")

    def _lockstate(self) -> dict:
        """Failure counter and lockout: kept OUT of meta.json so the file that holds the wrapped key is rewritten only at
        setup and PIN change (every rewrite on flash leaves an old copy of it behind)."""
        try:
            with open(self._lockfile()) as f:
                return json.load(f)
        except (OSError, ValueError):
            return {"fails": 0, "locked_until": 0}

    def _save_lockstate(self, st: dict):
        _atomic_write(self._lockfile(), json.dumps(st).encode())

    def _unwrap(self, pin) -> bytes:
        """The data key for this PIN, or WrongPin. Counts failures and enforces the lockout (checked before any key derivation,
        so guessing cannot burn CPU either). Used by login, PIN change and wipe: no path guesses without the counter."""
        meta = self._meta()
        if not meta or not meta.get("wrapped"):
            raise ValueError("Not set up yet.")
        lock = self._lockstate()
        wait = lock.get("locked_until", 0) - self.now()
        if wait > 0:
            raise RateLimited(wait)
        try:
            dek = self._open(_kek(pin if isinstance(pin, str) else "", _unb64(meta["salt"]), meta["n"], meta["r"], meta["p"]),
                             _unb64(meta["wrapped"]), b"dek")
        except WrongPin:
            fails = lock.get("fails", 0) + 1
            lock = {"fails": fails, "locked_until": self.now() + min(3600, 60 * 2 ** (fails - 5)) if fails >= 5 else 0}   # 60 s, doubling, capped at 1 h
            self._save_lockstate(lock)
            raise
        if lock.get("fails") or lock.get("locked_until"):
            self._save_lockstate({"fails": 0, "locked_until": 0})
        return dek

    def setup(self, pin: str, code: str = "") -> str:
        """First run: choose the family PIN. Needs the one-time code from the brain's log (so a stranger on the Wi-Fi cannot
        claim the board first). Returns a session token."""
        if not available():
            raise RuntimeError("The 'cryptography' package is missing, so profiles cannot be stored safely.")
        with self._lock:
            if self.configured():
                raise ValueError("Already set up.")
            if self.setup_code and not secrets.compare_digest(str(code or "").strip().upper(), self.setup_code):
                raise ValueError("That setup code is not right. It is printed in the brain's log when it starts.")
            self._check_pin_policy(pin)
            salt = secrets.token_bytes(16)
            n, r, p = self.kdf
            dek = secrets.token_bytes(32)
            wrapped = self._seal(_kek(pin, salt, n, r, p), dek, b"dek")
            self._save_meta({"v": 1, "salt": _b64(salt), "n": n, "r": r, "p": p, "wrapped": _b64(wrapped)})
            self._save_lockstate({"fails": 0, "locked_until": 0})
            self.setup_code = None
            self._dek = dek
            self.index = {"children": [], "settings": {"checkin_day": 6, "checkin_hour": 18, "notes_on": True}}
            self.items = {}
            self._write_index()
            return self._new_session()

    def login(self, pin: str) -> str:
        with self._lock:
            dek = self._unwrap(pin)
            if self._dek is None:
                self._dek = dek
                self._load_all()
            self.sweep()
            return self._new_session()

    def _new_session(self) -> str:
        tok = secrets.token_urlsafe(32)
        self.sessions[tok] = self.now()
        return tok

    def check(self, token: str | None) -> bool:
        """Valid, unexpired session (sliding 5 min idle). Also locks nothing: the brain keeps its key for the toys."""
        with self._lock:
            now = self.now()
            for t in [t for t, last in self.sessions.items() if now - last > SESSION_IDLE_S]:
                del self.sessions[t]
            if token and token in self.sessions and self._dek is not None:
                self.sessions[token] = now
                return True
            return False

    def logout(self, token: str | None):
        with self._lock:
            self.sessions.pop(token, None)

    def lock(self):
        """Forget the key now (notes become inactive until a parent enters the PIN again)."""
        with self._lock:
            self._dek = None
            self.items, self.sessions, self.bound = {}, {}, None
            self.index = {"children": [], "settings": self.index.get("settings", {})}

    def change_pin(self, old: str, new: str, keep: str | None = None):
        """Needs the current PIN (counted and locked out like a login). Every other session is ended."""
        with self._lock:
            self._require()
            self._unwrap(old)
            self._check_pin_policy(new)
            meta = self._meta()
            salt = secrets.token_bytes(16)
            n, r, p = self.kdf
            meta.update(salt=_b64(salt), n=n, r=r, p=p, wrapped=_b64(self._seal(_kek(new, salt, n, r, p), self._dek, b"dek")))
            self._save_meta(meta)   # profiles are untouched: only the wrapping of the key changed
            self.sessions = {t: v for t, v in self.sessions.items() if t == keep}

    def wipe_all(self, pin: str | None = None):
        """Delete everything: the wrapped key first (crypto-erase), then every file, overwritten. The web board requires the PIN.
        On flash storage old blocks may survive an overwrite, so this is best effort; an all-digit PIN of 8+ or a phrase is
        what keeps any surviving copy unreadable."""
        with self._lock:
            if pin is not None:
                self._unwrap(pin)
            _wipe_file(self._meta_path())
            for name in os.listdir(self.dir):
                _wipe_file(os.path.join(self.dir, name))
            self._dek = None
            self.items, self.sessions, self.bound = {}, {}, None
            self.index = {"children": [], "settings": {"checkin_day": 6, "checkin_hour": 18, "notes_on": True}}
            self.setup_code = secrets.token_hex(3).upper()
            self._announce()

    def _require(self):
        if self._dek is None:
            raise Locked()

    # ---- children ----
    def children(self) -> list[dict]:
        return [dict(c) for c in self.index["children"]]

    def add_child(self, name: str) -> dict:
        with self._lock:
            self._require()
            name = safe_text(name, 24)
            if not name:
                raise ValueError("A first name is needed.")
            if len(self.index["children"]) >= 8:
                raise ValueError("That is plenty of children for one board.")
            cid = "c" + secrets.token_hex(4)
            child = {"id": cid, "name": name, "color": COLORS[len(self.index["children"]) % len(COLORS)], "updated": _iso(self.now())}
            self.index["children"].append(child)
            self.items[cid] = []
            self._write_index()
            self._write_items(cid)
            return dict(child)

    def delete_child(self, cid: str):
        with self._lock:
            self._require()
            self.index["children"] = [c for c in self.index["children"] if c["id"] != cid]
            self.items.pop(cid, None)
            _wipe_file(self._file(f"child-{cid}.enc"))
            if self.bound == cid:
                self.bound = None
            self._write_index()

    def _child(self, cid):
        for c in self.index["children"]:
            if c["id"] == cid:
                return c
        raise KeyError("No such child.")

    # ---- items ----
    def add_items(self, cid: str, cards: list[dict], source: str = "parent") -> list[dict]:
        with self._lock:
            self._require()
            child = self._child(cid)
            now = self.now()
            added = []
            for c in cards[:20]:
                kind = c.get("kind")
                cat = c.get("category")
                if cat in CATEGORY_KIND and KIND_CATEGORY.get(kind) != cat:
                    kind = CATEGORY_KIND[cat]          # the parent moved the card to another category
                text = safe_text(c.get("text"), 60)
                if kind not in KINDS or not text:
                    continue
                item = {"id": secrets.token_hex(4), "kind": kind, "text": text, "detail": safe_text(c.get("detail"), 120) or None,
                        "due": c.get("due") if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(c.get("due") or "")) else None,
                        "weekday": c.get("weekday") if isinstance(c.get("weekday"), int) and 0 <= c["weekday"] <= 6 else None,
                        "time": c.get("time") if re.fullmatch(r"\d{2}:\d{2}", str(c.get("time") or "")) else None,
                        "scope": "today" if c.get("scope") == "today" else "standing", "added": _iso(now), "confirmed": _iso(now),
                        "source": "child" if source == "child" else "parent"}
                if kind == "school" and not item["due"]:
                    item["due"] = (_today(now) + dt.timedelta(days=(4 - _today(now).weekday()) % 7)).isoformat()   # defaults to this Friday
                self.items[cid].append(item)
                added.append(item)
            child["updated"] = _iso(now)
            self._write_items(cid)
            self._write_index()
            return added

    def delete_item(self, cid: str, iid: str):
        with self._lock:
            self._require()
            self._child(cid)
            self.items[cid] = [i for i in self.items[cid] if i["id"] != iid]
            self._write_items(cid)

    def clear_child(self, cid: str, kinds=None):
        with self._lock:
            self._require()
            self._child(cid)
            self.items[cid] = [i for i in self.items[cid] if kinds and i["kind"] not in kinds]
            self._write_items(cid)

    def confirm_item(self, cid: str, iid: str):
        """'Still true': resets the fade clock."""
        with self._lock:
            self._require()
            for i in self.items.get(cid, []):
                if i["id"] == iid:
                    i["confirmed"] = _iso(self.now())
            self._write_items(cid)

    def sweep(self):
        """Purge expired items. Called at unlock and whenever the list is read."""
        with self._lock:
            if self._dek is None:
                return
            now = self.now()
            for cid, items in list(self.items.items()):
                keep = [i for i in items if item_state(i, now) != "expired"]
                if len(keep) != len(items):
                    self.items[cid] = keep
                    self._write_items(cid)

    def view(self, cid: str) -> list[dict]:
        with self._lock:
            self._require()
            self.sweep()
            now = self.now()
            return [dict(i, state=item_state(i, now), label=describe(i, now), category=KIND_CATEGORY.get(i["kind"], "other"))
                    for i in self.items.get(cid, [])]

    # ---- weekly check-in ----
    def checkin_due(self) -> bool:
        s = self.index["settings"]
        now = dt.datetime.fromtimestamp(self.now())
        slot = now.replace(hour=int(s.get("checkin_hour", 18)), minute=0, second=0, microsecond=0)
        slot -= dt.timedelta(days=(now.weekday() - int(s.get("checkin_day", 6))) % 7)
        if slot > now:
            slot -= dt.timedelta(days=7)
        last = _parse_iso(s.get("last_checkin"))
        return bool(self.index["children"]) and (last is None or last < slot.timestamp())

    def checkin_done(self):
        with self._lock:
            self._require()
            self.index["settings"]["last_checkin"] = _iso(self.now())
            self._write_index()

    def set_settings(self, **kw):
        with self._lock:
            self._require()
            s = self.index["settings"]
            if kw.get("checkin_day") is not None:
                s["checkin_day"] = max(0, min(6, int(kw["checkin_day"])))
            if kw.get("checkin_hour") is not None:
                s["checkin_hour"] = max(0, min(23, int(kw["checkin_hour"])))
            if kw.get("notes_on") is not None:
                s["notes_on"] = bool(kw["notes_on"])
            if kw.get("child_memory") is not None:
                s["child_memory"] = bool(kw["child_memory"])
            self._write_index()

    # ---- now playing ----
    def now_playing(self, cid: str | None):
        with self._lock:
            self._require()
            if cid is not None:
                self._child(cid)
            self.bound, self.bound_at = cid, self.now()

    def bound_child(self) -> dict | None:
        with self._lock:
            if self._dek is None or not self.bound:
                return None
            if self.now() - max(self.bound_at, self.activity() or 0) > BIND_IDLE_S:
                self.bound = None   # a session ends after 30 idle minutes; the next one starts generic until a parent picks
                return None
            try:
                return self._child(self.bound)
            except KeyError:
                self.bound = None
                return None

    # ---- what the toys see ----
    def notes_block(self) -> str:
        """The private prompt section for the bound child, or '' (no key, nobody bound, paused or nothing active)."""
        with self._lock:
            if self._dek is None or not self.index["settings"].get("notes_on", True):
                return ""
            child = self.bound_child()
            if not child:
                return ""
            now = self.now()
            live = [i for i in self.items.get(child["id"], []) if item_state(i, now) == "active" and i.get("source") != "child"
                    and not str(i.get("detail") or "").startswith("curriculum:")]   # curriculum picks feed [GRADE TOPICS] instead (brain/curriculum_picks.py)
            live.sort(key=lambda i: PROMPT_ORDER.index(KIND_CATEGORY.get(i["kind"], "other")))   # long notes keep the important ones
            phrases, size = [], 0
            for i in live:
                ph = prompt_phrase(i, now)
                if ph and len(phrases) < NOTES_MAX_ITEMS and size + len(ph) <= NOTES_MAX_CHARS:
                    phrases.append(ph)
                    size += len(ph) + 2
            if not phrases:
                return ""
            return ("[PRIVATE NOTES: use them to choose topics and games; never quote them, never mention that notes, a parent or "
                    "a cue exist; never use one as a test; a 'keep it' note beats an interest for tone; a 'be mindful' note is about their safety or comfort] " + "; ".join(phrases))

    def told_block(self) -> str:
        """What the child told the toys themselves, for the prompt: the toys may bring it up like a friend who remembers."""
        with self._lock:
            if self._dek is None or not self.index["settings"].get("notes_on", True) or not self.index["settings"].get("child_memory", True):
                return ""
            child = self.bound_child()
            if not child:
                return ""
            now = self.now()
            told = [prompt_phrase(i, now) for i in self.items.get(child["id"], [])
                    if i.get("source") == "child" and item_state(i, now) == "active"]
            told = [t for t in told if t]
            if not told:
                return ""
            return ("[THE CHILD TOLD YOU THESE THEMSELVES: bring one up now and then, naturally and warmly, like a friend who "
                    "remembers ('You told me you like dinosaurs!'); never invent more, never say it was written down] " + "; ".join(told[-10:]))

    def remember(self, said: str) -> int:
        """Keep what the child just told the toys (facts only, never the sentence): an interest, a hobby day, a test, a pet's name.
        Needs the key, a child marked 'Playing now' and the parent's switch on; otherwise nothing is kept. Returns the count kept."""
        with self._lock:
            if self._dek is None or not self.index["settings"].get("notes_on", True) or not self.index["settings"].get("child_memory", True):
                return 0
            child = self.bound_child()
            if not child:
                return 0
            cards = parse_child(said, self.now())
            if not cards:
                return 0
            cid, now = child["id"], self.now()
            fresh = []
            for c in cards:
                same = next((i for i in self.items[cid] if i.get("source") == "child" and i["kind"] == c["kind"]
                             and i["text"].lower() == c["text"].lower()), None)
                if same:
                    same["confirmed"] = _iso(now)      # said again: still true
                else:
                    fresh.append(c)
            if fresh:
                self.add_items(cid, fresh, source="child")
                mine = [i for i in self.items[cid] if i.get("source") == "child"]
                for old in mine[:-CHILD_MAX]:
                    self.items[cid].remove(old)
            self._write_items(cid)
            return len(cards)

    def sort_dump(self, text: str, llm, busy=lambda: False) -> str:
        """Start sorting a parent's context dump. Returns a job id; poll `jobs[job]` (same shape as a worksheet read)."""
        with self._lock:
            self._require()
        job = secrets.token_hex(6)
        self.jobs[job] = {"status": "working", "cards": [], "at": self.now()}
        threading.Thread(target=self._sort_job, args=(job, text, llm, busy), daemon=True, name="sort-dump").start()
        return job

    def _sort_job(self, job, text, llm, busy):
        try:
            now = self.now()
            res = parse_dump(text, now)
            cards, unparsed, ai = res["cards"], res["unparsed"], False
            if unparsed and hasattr(llm, "complete"):
                waited = 0
                while busy() and waited < 30:     # never compete with a child's turn
                    time.sleep(1)
                    waited += 1
                try:
                    extra = _tidy(_gemma_sort(llm, unparsed, now), now)
                    if extra:
                        cards, unparsed, ai = _tidy(cards + extra, now), [], True
                except Exception as e:  # noqa: BLE001 — the rules' cards are still useful
                    log.warning("Gemma sort failed: %s", e)
            self.jobs[job] = {"status": "done", "cards": cards, "unparsed": unparsed, "ai": ai, "at": self.now()}
        except Exception as e:  # noqa: BLE001
            log.warning("sorting failed: %s", e)
            self.jobs[job] = {"status": "error", "error": "Could not sort that.", "cards": [], "at": self.now()}

    # ---- worksheets (a photo is read in RAM, summarised, and deleted at once) ----
    def read_worksheet(self, cid: str, image: bytes, llm, busy=lambda: False) -> str:
        with self._lock:
            self._require()
            self._child(cid)
        job = secrets.token_hex(6)
        self.jobs[job] = {"status": "working", "cards": [], "at": self.now()}
        threading.Thread(target=self._worksheet_job, args=(job, image, llm, busy), daemon=True, name="worksheet").start()
        return job

    def _worksheet_job(self, job, image, llm, busy):
        path = None
        try:
            if not hasattr(llm, "complete"):
                raise RuntimeError("Reading a photo needs the local Gemma model, which is not available.")
            waited = 0
            while busy() and waited < 60:   # never compete with a child's turn
                time.sleep(1)
                waited += 1
            ram = "/dev/shm" if os.path.isdir("/dev/shm") else None
            fd, path = tempfile.mkstemp(suffix=".jpg", dir=ram, prefix=".ws-")
            with os.fdopen(fd, "wb") as f:
                f.write(image)
            out = llm.complete("This is a child's homework sheet or school schedule. In one or two short plain sentences, say "
                               "what is due and when, and list any spelling words after 'words:'. If you cannot read it, say 'unreadable'.",
                               system="You read worksheets for a parent. Answer briefly. Never guess.", image=path, max_tokens=160)
            if not out or "unreadable" in out.lower():
                self.jobs[job] = {"status": "done", "cards": [], "unparsed": ["Could not read that photo. Try a closer, brighter one."], "at": self.now()}
            else:
                res = parse_text(out, self.now())
                self.jobs[job] = {"status": "done", "cards": res["cards"], "unparsed": res["unparsed"], "summary": safe_text(out, 300), "at": self.now()}
        except Exception as e:  # noqa: BLE001
            log.warning("worksheet read failed: %s", e)
            self.jobs[job] = {"status": "error", "error": "Could not read the photo.", "cards": [], "at": self.now()}
        finally:
            if path:
                try:
                    os.unlink(path)   # the photo is never kept
                except OSError:
                    pass
            for k in [k for k, v in self.jobs.items() if self.now() - v["at"] > 600]:
                self.jobs.pop(k, None)
