"""California academics repository: what a child in a given grade learns, indexed for fast lookup.

Data lives in brain/curriculum/*.json (schema, sources and how to extend it: docs/curriculum.md). This module loads it once,
builds indexes (by id, grade, subject, tag), and offers:

  * query(...)            lookup by grade / subject / kind / tag / difficulty / free text
  * grade_from_text(...)  "in 2nd grade" / "kindergarten" / "grade 7" -> 0..8
  * topics_block(...)     the short rotating [GRADE TOPICS] prompt block the director adds each turn
  * banter_seed(...)      one topic phrase for idle banter

Nothing here knows about a child: it takes a grade number (and optional parent picks) and returns public curriculum text.
"""
from __future__ import annotations

import collections
import json
import random
import re
import threading
from pathlib import Path

DATA_DIR = Path(__file__).with_name("curriculum")
SUBJECTS = ("ela", "math", "hss", "science", "california")
SUBJECT_LABELS = {"ela": "Reading, writing & spelling", "math": "Math", "hss": "History & social science",
                  "science": "Science", "california": "California"}
KINDS = ("topic", "vocab", "spelling", "fact")
GRADES = tuple(range(0, 9))           # 0 = kindergarten ... 8
DEFAULT_GRADE = 2                     # the toys are made for roughly 2nd-5th graders; used when the profile gives no grade
GRADE_NAMES = {0: "kindergarten", 1: "1st grade", 2: "2nd grade", 3: "3rd grade", 4: "4th grade", 5: "5th grade",
               6: "6th grade", 7: "7th grade", 8: "8th grade"}

_lock = threading.Lock()
_cache: dict | None = None


def grade_label(grade: int) -> str:
    return GRADE_NAMES.get(grade, "grade %s" % grade)


# ---------------------------------------------------------------- loading and indexes
def load_files(directory: Path | None = None) -> list[dict]:
    """Every data file as parsed JSON, each with its '_file' name added. Bad JSON raises (the tests catch it)."""
    out = []
    for p in sorted((directory or DATA_DIR).glob("*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        d["_file"] = p.name
        out.append(d)
    return out


def _build(files: list[dict]) -> dict:
    items, by_id = [], {}
    by_grade = collections.defaultdict(list)
    by_gs = collections.defaultdict(list)
    by_tag = collections.defaultdict(list)
    for f in files:
        for it in f.get("items", []):
            it = dict(it)
            it.setdefault("words", [])
            it.setdefault("tags", [])
            it["_file"] = f["_file"]
            it["_text"] = " ".join([it.get("title", ""), it.get("summary", ""), it.get("strand", ""), " ".join(it["tags"]),
                                    " ".join(it["words"])]).lower()
            items.append(it)
            by_id[it["id"]] = it
            by_grade[it["grade"]].append(it)
            by_gs[(it["grade"], it["subject"])].append(it)
            for t in it["tags"]:
                by_tag[t.lower()].append(it)
    return {"items": items, "by_id": by_id, "by_grade": by_grade, "by_gs": by_gs, "by_tag": by_tag, "files": files}


def index() -> dict:
    global _cache
    with _lock:
        if _cache is None:
            _cache = _build(load_files())
        return _cache


def reload() -> None:
    global _cache
    with _lock:
        _cache = None


def get(topic_id: str) -> dict | None:
    return index()["by_id"].get(topic_id)


def public(it: dict) -> dict:
    """An item without the internal search fields (what the web API returns)."""
    return {k: v for k, v in it.items() if not k.startswith("_")}


def sources() -> dict[str, list[str]]:
    return {f["_file"]: f.get("sources", []) for f in index()["files"]}


# ---------------------------------------------------------------- lookup
_WORD = re.compile(r"[a-z0-9']+")


def query(grade: int | None = None, subject: str | None = None, kind: str | None = None, tag: str | None = None,
          difficulty: int | None = None, text: str | None = None, limit: int | None = None) -> list[dict]:
    """Items matching every given filter, in file order. `text` matches whole lowercase words anywhere in an item
    (title, summary, tags, words); all words must match. `difficulty` is the most difficult level to include."""
    ix = index()
    if grade is not None and subject is not None:
        pool = ix["by_gs"].get((grade, subject), [])
    elif grade is not None:
        pool = ix["by_grade"].get(grade, [])
    elif tag:
        pool = ix["by_tag"].get(tag.lower(), [])
    else:
        pool = ix["items"]
    words = _WORD.findall((text or "").lower())
    out = []
    for it in pool:
        if subject is not None and it["subject"] != subject:
            continue
        if kind is not None and it["kind"] != kind:
            continue
        if tag and tag.lower() not in (t.lower() for t in it["tags"]):
            continue
        if difficulty is not None and it.get("difficulty", 1) > difficulty:
            continue
        if words:
            hay = set(_WORD.findall(it["_text"]))
            if not all(w in hay for w in words):
                continue
        out.append(it)
        if limit and len(out) >= limit:
            break
    return out


def coverage() -> dict[int, dict[str, int]]:
    """{grade: {subject: item count}} for the board and the tests."""
    ix = index()
    return {g: {s: len(ix["by_gs"].get((g, s), [])) for s in SUBJECTS} for g in GRADES}


# ---------------------------------------------------------------- grade from a profile
_ORD = {"kindergarten": 0, "kinder": 0, "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6,
        "seventh": 7, "eighth": 8}
_GRADE_RES = [
    re.compile(r"\b(?:in\s+)?(?:grade|gr\.?)\s*(\d{1,2})\b", re.I),
    re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)\s*[- ]?grade(?:r)?\b", re.I),
    re.compile(r"\b(first|second|third|fourth|fifth|sixth|seventh|eighth)\s*[- ]?grade(?:r)?\b", re.I),
    re.compile(r"\b(kindergarten|kinder)(?:er|ner)?\b", re.I),
]


def grade_from_text(text: str) -> int | None:
    """'in 2nd grade', 'second grader', 'in kindergarten', 'grade 7' -> 2, 2, 0, 7. None when there is no grade."""
    s = str(text or "")
    for rx in _GRADE_RES:
        m = rx.search(s)
        if not m:
            continue
        v = m.group(1).lower()
        g = _ORD[v] if v in _ORD else int(v)
        if 0 <= g <= 8:
            return g
    if re.search(r"\b(?:in\s+)?(?:K|TK)\b", s) and re.search(r"\bin\s+K\b", s):
        return 0
    return None


# ---------------------------------------------------------------- the rotating prompt block
BLOCK_ITEMS = 3                # a few items per turn, never more
BLOCK_MAX_CHARS = 520
RECENT = 40                    # topics not repeated until this many others have been offered
BOOST_WEIGHT = 5


class Rotation:
    """Picks a few topics per turn for one conversation: rotates through the grade so the toys do not repeat themselves,
    mixes subjects, and leans toward topics a parent boosted. Thread-safe enough for the director's single turn lock."""

    def __init__(self, rng: random.Random | None = None):
        self.rng = rng or random.Random()
        self.recent: collections.deque = collections.deque(maxlen=RECENT)

    def pick(self, grade: int, boost=frozenset(), skip=frozenset(), n: int = BLOCK_ITEMS) -> list[dict]:
        pool = [it for it in index()["by_grade"].get(grade, []) if it["id"] not in skip]
        if not pool:
            return []
        fresh = [it for it in pool if it["id"] not in self.recent] or pool
        chosen, subjects = [], set()
        for _ in range(min(n, len(fresh))):
            cands = [it for it in fresh if it not in chosen and (it["subject"] not in subjects or len(subjects) >= len(SUBJECTS))]
            cands = cands or [it for it in fresh if it not in chosen]
            if not cands:
                break
            weights = [BOOST_WEIGHT if it["id"] in boost else 1 for it in cands]
            it = self.rng.choices(cands, weights=weights)[0]
            chosen.append(it)
            subjects.add(it["subject"])
        for it in chosen:
            self.recent.append(it["id"])
        return chosen


def _phrase(it: dict) -> str:
    s = it["title"]
    if it["kind"] in ("vocab", "spelling") and it.get("words"):
        return "%s (words like: %s)" % (s, ", ".join(it["words"][:3]))
    return "%s: %s" % (s, it["summary"]) if it.get("summary") else s


def topics_block(grade: int | None, rotation: Rotation, boost=frozenset(), skip=frozenset()) -> str:
    """'[GRADE TOPICS: ...] a; b; c' or '' when there is nothing to offer. Grade None means unknown -> DEFAULT_GRADE."""
    g = DEFAULT_GRADE if grade is None else grade
    items = rotation.pick(g, boost, skip)
    if not items:
        return ""
    parts, size = [], 0
    for it in items:
        ph = _phrase(it)
        if size + len(ph) > BLOCK_MAX_CHARS and parts:
            break
        parts.append(ph)
        size += len(ph) + 2
    return ("[GRADE TOPICS: things a California %s student is learning; only if it fits, bring one up as casual chat or a fun fact; "
            "never quiz or test the child on them unless they ask; ignore them if the child is talking about something else] "
            % grade_label(g)) + "; ".join(parts)


def banter_seed(grade: int | None, rotation: Rotation, boost=frozenset(), skip=frozenset()) -> str | None:
    """A short phrase for idle banter ('the Gold Rush'), drawn from the grade's topics; None when the data is empty."""
    items = rotation.pick(DEFAULT_GRADE if grade is None else grade, boost, skip, n=1)
    return items[0]["title"].lower() if items else None
