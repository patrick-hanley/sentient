"""Fact guard: every toy line is checked for facts that code can verify BEFORE it is spoken. A 2B model states wrong facts
with confidence ("if we have 100 and take away 10, we have zero", "adventure has seven letters", "six, eleven, twelve" counting
by fives, "parallelograms have four equal sides"). The user's rule: the facts can not be wrong.

What is checked (all deterministic, no model, no network):
  arithmetic      "7 times 8 is 54", "two plus three makes six", "have 10 and take away 3, you have 6", "double 4 is 8", "half of 10 is 5"
                  and question -> answer across sentences or toy lines ("What is 6 times 7?" ... "Forty-two!")
  letters         "cat has three letters", "how many letters are in dog?" ... "Three!", "C-A-T spells cat", "cat starts with C",
                  "A is a vowel"
  counting runs   "five, ten, fifteen" must step evenly (and by the step named: "count by fives")
  numbers         "7 is an odd number", "12 is bigger than 9"
  known counts    legs (spider 8, insect 6 ...), polygon sides/corners, days in a week, months in a year, minutes in an hour,
                  planets 8, states 50, continents 7, letters in the alphabet 26, coins in cents, inches in a foot ...
  shapes          "a rectangle has four equal sides" (only a square or rhombus has)
  space           biggest/smallest/hottest planet, closest/farthest from the sun, the red planet, Nth planet from the sun,
                  "the sun is a planet", "Pluto is a planet"
  capitals        the 50 US state capitals and a few countries, as a statement or question -> answer
  superlatives    largest ocean / continent, smallest continent, tallest / fastest land animal in the world

A wrong number, letter or name is FIXED in place when the right one is known ("54" -> "56", "Venus" -> "Jupiter"); otherwise the
sentence is DROPPED. Facts code cannot check are left to the prompt (true facts from the curriculum card, "let's check together").
Nothing is logged here; the director logs only counts.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# ---------------------------------------------------------------- numbers
_UNITS = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
                                     "fifteen sixteen seventeen eighteen nineteen".split())}
_TENS = {w: 10 * (i + 2) for i, w in enumerate("twenty thirty forty fifty sixty seventy eighty ninety".split())}
_SCALES = {"hundred": 100, "thousand": 1000, "million": 1_000_000}
_NUMWORD = "|".join(sorted(list(_UNITS) + list(_TENS) + list(_SCALES), key=len, reverse=True))
_NUM_RE = re.compile(rf"\b(?:\d{{1,3}}(?:,\d{{3}})+|\d+(?:\.\d+)?)\b|\b(?:a\s+(?=(?:hundred|thousand|million)\b))?(?:(?:{_NUMWORD})\b(?:[\s-]+(?:and\s+)?)?)+",
                     re.I)


@dataclass
class Num:
    value: float
    start: int
    end: int
    word: bool          # written in words ("seven") rather than digits ("7")


def _words_value(tokens: list[str]) -> list[tuple[float, int]]:
    """Split a run of number words into numbers: 'twenty five' -> [25], 'five ten fifteen' -> [5, 10, 15] (as tokens counted)."""
    out, total, cur, last, used = [], 0, 0, None, 0

    def flush():
        nonlocal total, cur, last, used
        if last is not None:
            out.append((total + cur, used))
        total, cur, last, used = 0, 0, None, 0

    for tok in tokens:
        t = tok.lower()
        if t == "a":
            used += 1
            continue
        if t == "and":
            if last in ("hundred", "thousand", "million"):
                used += 1
                continue
            flush()
            continue
        if t in _SCALES:
            if last in (None,) and not cur:
                cur = 1
            if _SCALES[t] == 100:
                cur = (cur or 1) * 100
            else:
                total += (cur or 1) * _SCALES[t]
                cur = 0
            last, used = t, used + 1
            continue
        v = _UNITS.get(t, _TENS.get(t))
        ok = (last is None or last in ("hundred", "thousand", "million")
              or (last in _TENS and t in _UNITS and 0 < _UNITS[t] < 10))
        if not ok:
            flush()
        cur += v
        last, used = t, used + 1
    flush()
    return out


def numbers(text: str) -> list[Num]:
    out = []
    for m in _NUM_RE.finditer(text):
        s = m.group(0)
        if s[0].isdigit():
            out.append(Num(float(s.replace(",", "")), m.start(), m.end(), False))
            continue
        # split the word run into separate numbers with their spans
        toks = list(re.finditer(r"[A-Za-z]+", s))
        vals = _words_value([t.group(0) for t in toks])
        i = 0
        for v, n in vals:
            seg = [t for t in toks[i:i + n] if t.group(0).lower() not in ("and",)] or toks[i:i + n]
            i += n
            # skip any 'and' tokens that separated numbers
            while i < len(toks) and toks[i].group(0).lower() == "and":
                i += 1
            if not seg:
                continue
            out.append(Num(float(v), m.start() + seg[0].start(), m.start() + seg[-1].end(), True))
    return out


def words(n: int) -> str:
    """7 -> 'seven', 42 -> 'forty-two', 305 -> 'three hundred five' (0..999,999)."""
    if n < 0:
        return "minus " + words(-n)
    if n < 20:
        return list(_UNITS)[n]
    if n < 100:
        t, u = divmod(n, 10)
        return list(_TENS)[t - 2] + (f"-{list(_UNITS)[u]}" if u else "")
    if n < 1000:
        h, r = divmod(n, 100)
        return f"{list(_UNITS)[h]} hundred" + (f" {words(r)}" if r else "")
    if n < 1_000_000:
        th, r = divmod(n, 1000)
        return f"{words(th)} thousand" + (f" {words(r)}" if r else "")
    return str(n)


def _fmt(value: float, like: Num, original: str) -> str:
    v = int(value) if float(value).is_integer() else value
    if not like.word or not isinstance(v, int):
        return f"{v:,}" if isinstance(v, int) and v >= 10000 else str(v)
    w = words(v)
    return w[0].upper() + w[1:] if original[:1].isupper() else w


# ---------------------------------------------------------------- normalised text with number placeholders
class _Norm:
    """Lower-cased copy of the text in which each number is '#k'; spans map back to the original."""

    def __init__(self, text: str):
        self.text, self.nums = text, numbers(text)
        parts, pos = [], 0
        for k, n in enumerate(self.nums):
            parts.append(text[pos:n.start].lower())
            parts.append(f"#{k}")
            pos = n.end
        parts.append(text[pos:].lower())
        self.s = "".join(parts).replace("’", "'")

    def num(self, k: str | int) -> Num:
        return self.nums[int(k)]

    def orig_pos(self, i: int) -> int:
        """Character offset in the original text for offset i in the normalised one."""
        pos, npos = 0, 0
        for k, n in enumerate(self.nums):
            ph = f"#{k}"
            seg = n.start - pos
            if i < npos + seg:
                return pos + (i - npos)
            npos += seg
            if i < npos + len(ph):
                return n.start
            npos += len(ph)
            pos = n.end
        return pos + (i - npos)


@dataclass
class Error:
    kind: str                  # arithmetic | letters | counting | numbers | count | shape | space | capital | superlative
    start: int                 # span in the checked text of the wrong part (a number, letter or name)
    end: int
    fix: str | None            # replacement text, or None (the sentence must be dropped)


N = r"#(\d+)"
_VERB = (r"(?:is|are|equals?|makes?|gives?(?: (?:us|you|me))?|gets? (?:us|you)|=|will (?:make|be|give(?: us| you)?)|is equal to|"
         r"comes? to|adds? up to|leaves?(?: us| you)?|that'?s|it'?s|is just)")
_OPS = {"add": r"(?:plus|\+|and|added to)", "sub": r"(?:minus|-|take away|takeaway|less)", "mul": r"(?:times|x|×|\*|multiplied by|groups of)",
        "div": r"(?:divided by|÷|/|split into)"}


def _calc(op: str, a: float, b: float) -> float | None:
    if op == "add":
        return a + b
    if op == "sub":
        return a - b
    if op == "mul":
        return a * b
    if op == "div":
        return a / b if b else None
    return None


_ARITH = [(op, re.compile(rf"{N}\s*{pat}\s*{N}(?:\s+more)?\s*,?\s*{_VERB}\s*(?:just\s+|only\s+)?{N}"))
          for op, pat in _OPS.items()]
_ARITH += [("add", re.compile(rf"\badd\s+{N}\s+(?:and|to|plus)\s+{N}\s*,?\s*(?:and\s+)?(?:(?:you|we|i)\s+(?:will\s+)?(?:get|have|make)|{_VERB})\s+{N}")),
           ("sub", re.compile(rf"\btake\s+(?:away\s+)?{N}\s+from\s+{N}\s*,?\s*(?:and\s+)?(?:(?:you|we|i)\s+(?:will\s+)?(?:get|have)|{_VERB})\s+{N}")),
           ("dbl", re.compile(rf"\bdouble\s+(?:of\s+)?{N}\s*,?\s*{_VERB}\s*{N}")),
           ("half", re.compile(rf"\bhalf\s+(?:of\s+)?{N}\s*,?\s*{_VERB}\s*{N}"))]
_STORY = re.compile(rf"\b(?:have|has|had|got|with|there are|there were)\s+{N}\b[^#.!?]{{0,30}}?\b(?:and|then)\s+(?:we\s+|you\s+|i\s+|they\s+|he\s+|she\s+)?"
                    rf"(?P<verb>take away|takes away|took away|eat|eats|ate|lose|loses|lost|give away|gave away|subtract|remove|use|used|"
                    rf"get|gets|got|add|adds|added|find|found|buy|bought|pick|picked)\s+{N}\b[^#.!?]{{0,25}}?,?\s*"
                    rf"(?:now\s+)?(?:we|you|i|there|they|he|she|it)\s*(?:will\s+|would\s+)?(?:have|has|are left with|'re left with|get|is|are)\s+"
                    rf"(?:only\s+|just\s+)?{N}")
_Q_ARITH = re.compile(rf"(?:what'?s|what is|how much is|what does|what do|can you tell me)\s+{N}\s*(?P<op>{'|'.join(_OPS.values())})\s*{N}")
_ANSWER = re.compile(rf"^\s*(?:(?:yes|yeah|oh|ooh|um|hmm|easy|wow|i know|i think|it'?s|it is|that'?s|that is|the answer is|you get|we get|"
                     rf"they make|it makes|that makes|that equals|it equals|is it|that would be)[\s,!.]*){{0,3}}{N}\b")


def _opname(word: str) -> str:
    for op, pat in _OPS.items():
        if re.fullmatch(pat, word):
            return op
    return "add"


# ---------------------------------------------------------------- tables
_SIDES = {"triangle": 3, "square": 4, "rectangle": 4, "rhombus": 4, "parallelogram": 4, "trapezoid": 4, "quadrilateral": 4, "kite": 4,
          "pentagon": 5, "hexagon": 6, "heptagon": 7, "octagon": 8, "nonagon": 9, "decagon": 10}
_EQUAL_OK = {"square", "rhombus"}
# (noun regex, subject regex, allowed values, singular subject required)
_COUNTS = [
    (r"legs?", r"spiders?|tarantulas?", {8}, False), (r"(?:legs?|arms?)", r"octopus(?:es)?|octopi", {8}, False),
    (r"legs?", r"insects?|ants?|bees?|butterfl(?:y|ies)|ladybugs?|beetles?|grasshoppers?|flies|fly|crickets?|bugs?", {6}, False),
    (r"legs?", r"birds?|chickens?|ducks?|penguins?|ostrich(?:es)?|owls?|humans?|people|kids?|children|child", {2}, False),
    (r"legs?", r"dogs?|cats?|horses?|cows?|elephants?|lions?|tigers?|bears?|pigs?|sheep|goats?|zebras?|giraffes?", {4}, False),
    (r"(?:days?)", r"week", {7}, True), (r"(?:months?)", r"year", {12}, True), (r"(?:days?)", r"year", {365, 366}, True),
    (r"(?:weeks?)", r"year", {52}, True), (r"(?:hours?)", r"day", {24}, True), (r"(?:minutes?)", r"hour", {60}, True),
    (r"(?:seconds?)", r"minute", {60}, True), (r"(?:inch(?:es)?)", r"foot", {12}, True), (r"(?:feet|foot)", r"yard", {3}, True),
    (r"(?:cents?|pennies)", r"dollar", {100}, True), (r"(?:centimeters?|centimetres?)", r"meter|metre", {100}, True),
    (r"(?:millimeters?|millimetres?)", r"centimeter|centimetre", {10}, True), (r"(?:grams?)", r"kilogram", {1000}, True),
    (r"(?:things|eggs|items|donuts|cookies)", r"dozen", {12}, True), (r"(?:cents?)", r"nickel", {5}, True),
    (r"(?:cents?)", r"dime", {10}, True), (r"(?:cents?)", r"quarter", {25}, True), (r"(?:sides|faces)", r"(?:die|dice|cube)", {6}, True),
    (r"(?:letters?)", r"(?:the )?(?:english )?alphabet", {26}, True), (r"(?:colors?|colours?)", r"rainbow", {7}, True),
    (r"(?:cards?)", r"deck", {52}, True),
]
_GLOBAL_COUNTS = [  # the number and noun alone make the claim
    (re.compile(rf"{N}\s+planets\b(?!\s+(?:like|that|with))"), {8}, r"(?:dwarf|rocky|gas|inner|outer|giant|other|big|small|tiny|more)\s+$"),
    (re.compile(rf"{N}\s+(?:united\s+)?states\b(?=[^.!?]*\b(?:america|usa|u\.s\.|united states|our country|country)\b)|{N}\s+states in (?:america|the usa|the united states|our country)"), {50}, None),
    (re.compile(rf"{N}\s+continents\b"), {7}, None), (re.compile(rf"{N}\s+oceans\b"), {4, 5}, None),
]
_PLANETS = ["mercury", "venus", "earth", "mars", "jupiter", "saturn", "uranus", "neptune"]
_ORD = {w: i + 1 for i, w in enumerate("first second third fourth fifth sixth seventh eighth".split())}
_PLANET_RE = r"\b(mercury|venus|earth|mars|jupiter|saturn|uranus|neptune|pluto)\b"
_SUPER = [  # (phrase in the clause, name set regex, right answer(s), replacement)
    (r"\b(?:biggest|largest|hugest)\s+planet|\bplanet\b[^,.!?]{0,12}\b(?:biggest|largest)\b", _PLANET_RE, {"jupiter"}, "Jupiter"),
    (r"\bsmallest\s+planet|\bplanet\b[^,.!?]{0,12}\bsmallest\b", _PLANET_RE, {"mercury"}, "Mercury"),
    (r"\bhottest\s+planet", _PLANET_RE, {"venus"}, "Venus"),
    (r"\b(?:closest|nearest)\s+(?:planet\s+)?to\s+the\s+sun|\bplanet\s+(?:closest|nearest)\s+to\s+the\s+sun", _PLANET_RE, {"mercury"}, "Mercury"),
    (r"\b(?:farthest|furthest)\s+(?:planet\s+)?from\s+the\s+sun|\bplanet\s+(?:farthest|furthest)\s+from\s+the\s+sun", _PLANET_RE, {"neptune"}, "Neptune"),
    (r"\bred\s+planet", _PLANET_RE, {"mars"}, "Mars"),
    (r"\b(?:biggest|largest)\s+ocean", r"\b(pacific|atlantic|indian|arctic|southern)\b", {"pacific"}, "Pacific"),
    (r"\b(?:biggest|largest)\s+continent", r"\b(africa|antarctica|asia|australia|europe|north america|south america)\b", {"asia"}, "Asia"),
    (r"\bsmallest\s+continent", r"\b(africa|antarctica|asia|australia|europe|north america|south america)\b", {"australia"}, "Australia"),
    (r"\btallest\s+animal\s+(?:in\s+the\s+world|on\s+earth)", r"\b(giraffes?|elephants?|horses?|camels?|bears?|ostrich(?:es)?)\b", {"giraffe", "giraffes"}, "giraffe"),
    (r"\bfastest\s+land\s+animal", r"\b(cheetahs?|lions?|horses?|tigers?|leopards?|antelopes?|rabbits?|dogs?)\b", {"cheetah", "cheetahs"}, "cheetah"),
    (r"\b(?:biggest|largest)\s+(?:animal|mammal)\s+(?:in\s+the\s+world|on\s+earth|ever)", r"\b(blue whales?|whales?|elephants?|giraffes?|sharks?)\b", {"blue whale", "blue whales", "whale", "whales"}, "blue whale"),
    (r"\b(?:biggest|largest)\s+state\b", r"\b(alaska|texas|california|montana)\b", {"alaska"}, "Alaska"),
    (r"\bsmallest\s+state\b", r"\b(rhode island|delaware|connecticut)\b", {"rhode island"}, "Rhode Island"),
    (r"\bfirst\s+president\b", r"\b(george washington|washington|lincoln|abraham lincoln|thomas jefferson|jefferson|john adams|adams)\b",
     {"george washington", "washington"}, "George Washington"),
]
CAPITALS = {
    "alabama": "Montgomery", "alaska": "Juneau", "arizona": "Phoenix", "arkansas": "Little Rock", "california": "Sacramento",
    "colorado": "Denver", "connecticut": "Hartford", "delaware": "Dover", "florida": "Tallahassee", "georgia": "Atlanta",
    "hawaii": "Honolulu", "idaho": "Boise", "illinois": "Springfield", "indiana": "Indianapolis", "iowa": "Des Moines",
    "kansas": "Topeka", "kentucky": "Frankfort", "louisiana": "Baton Rouge", "maine": "Augusta", "maryland": "Annapolis",
    "massachusetts": "Boston", "michigan": "Lansing", "minnesota": "Saint Paul", "mississippi": "Jackson", "missouri": "Jefferson City",
    "montana": "Helena", "nebraska": "Lincoln", "nevada": "Carson City", "new hampshire": "Concord", "new jersey": "Trenton",
    "new mexico": "Santa Fe", "new york": "Albany", "north carolina": "Raleigh", "north dakota": "Bismarck", "ohio": "Columbus",
    "oklahoma": "Oklahoma City", "oregon": "Salem", "pennsylvania": "Harrisburg", "rhode island": "Providence",
    "south carolina": "Columbia", "south dakota": "Pierre", "tennessee": "Nashville", "texas": "Austin", "utah": "Salt Lake City",
    "vermont": "Montpelier", "virginia": "Richmond", "washington": "Olympia", "west virginia": "Charleston", "wisconsin": "Madison",
    "wyoming": "Cheyenne",
    "the united states": "Washington, D.C.", "united states": "Washington, D.C.", "america": "Washington, D.C.", "the usa": "Washington, D.C.",
    "canada": "Ottawa", "mexico": "Mexico City", "france": "Paris", "england": "London", "the united kingdom": "London", "japan": "Tokyo",
    "china": "Beijing", "italy": "Rome", "spain": "Madrid", "germany": "Berlin", "australia": "Canberra", "egypt": "Cairo",
    "india": "New Delhi", "brazil": "Brasilia",
}
_CAP_OK = {"saint paul": {"saint paul", "st. paul", "st paul"}, "washington, d.c.": {"washington, d.c.", "washington d.c.", "washington dc",
           "washington, dc", "washington", "d.c.", "dc"}, "brasilia": {"brasilia", "brasília"}}
_PLACES = sorted(CAPITALS, key=len, reverse=True)
_PLACE_RE = "|".join(re.escape(p) for p in _PLACES)
_ALL_CAPS = sorted({c.lower() for c in CAPITALS.values()} | {"los angeles", "san francisco", "san diego", "new york city", "chicago",
                    "seattle", "portland", "miami", "dallas", "houston", "las vegas", "philadelphia", "detroit", "san jose", "fresno",
                    "oakland", "toronto", "vancouver", "sydney", "melbourne", "shanghai"}, key=len, reverse=True)
_CITY_RE = r"\b(" + "|".join(re.escape(c) for c in _ALL_CAPS) + r")\b"


def _cap_ok(place: str, said: str) -> bool:
    norm = lambda x: " ".join(re.sub(r"[.,]", " ", x.lower()).split())   # noqa: E731
    right = CAPITALS[place].lower()
    return norm(said) in {norm(x) for x in _CAP_OK.get(right, {right})}


# ---------------------------------------------------------------- the checks
def _sentences(s: str) -> list[tuple[int, int]]:
    out, start = [], 0
    for m in re.finditer(r"[.!?]+(?=\s|$)", s):
        out.append((start, m.end()))
        start = m.end()
    if start < len(s):
        out.append((start, len(s)))
    return [(a, b) for a, b in out if s[a:b].strip()]


def _clauses(s: str, a: int, b: int) -> list[tuple[int, int]]:
    out, start = [], a
    for m in re.finditer(r",\s+(?:and|but|so)\s+|;\s*|\s+(?:and|but)\s+(?=[a-z#]+\s+(?:is|are|has|have)\b)|,\s+(?=[a-z#]+\s+(?:is|are|has|have)\b)", s[a:b]):
        out.append((start, a + m.start()))
        start = a + m.end()
    out.append((start, b))
    return out


def _num_err(nm: _Norm, k, right: float, kind: str) -> Error:
    n = nm.num(k)
    fix = _fmt(right, n, nm.text[n.start:n.end]) if right is not None and float(right) >= 0 and float(right).is_integer() else None
    return Error(kind, n.start, n.end, fix)


def _arith(nm: _Norm) -> list[Error]:
    errs, s = [], nm.s
    for op, rx in _ARITH:
        for m in rx.finditer(s):
            g = [nm.num(x).value for x in m.groups()]
            if op == "dbl":
                right, c = 2 * g[0], m.group(2)
            elif op == "half":
                right, c = g[0] / 2, m.group(2)
            elif op == "sub" and rx.pattern.startswith(r"\btake"):
                right, c = g[1] - g[0], m.group(3)
            else:
                right, c = _calc(op, g[0], g[1]), m.group(3)
            if op == "add" and " and " in m.group(0) and not re.search(r"\b(?:make|makes|equals?|is|are|that'?s|it'?s|=)\b", m.group(0)):
                continue
            if right is not None and abs(nm.num(c).value - right) > 1e-9:
                errs.append(_num_err(nm, c, right, "arithmetic"))
    for m in _STORY.finditer(s):
        a, b, c = (nm.num(m.group(i)).value for i in (1, 3, 4))
        v = m.group("verb")
        right = a + b if re.match(r"get|got|add|find|found|buy|bought|pick", v) else a - b
        if abs(c - right) > 1e-9:
            errs.append(_num_err(nm, m.group(4), right, "arithmetic"))
    for m in re.finditer(rf"{N}\s+is\s+(?:an?\s+)?(even|odd)\b", s):
        v = nm.num(m.group(1)).value
        if v.is_integer() and (int(v) % 2 == 0) != (m.group(2) == "even"):
            errs.append(Error("numbers", nm.orig_pos(m.start(2)), nm.orig_pos(m.end(2)), "odd" if m.group(2) == "even" else "even"))
    for m in re.finditer(rf"{N}\s+is\s+(?:a\s+lot\s+|much\s+)?(bigger|greater|larger|more|smaller|less|fewer)\s+than\s+{N}", s):
        a, b = nm.num(m.group(1)).value, nm.num(m.group(3)).value
        big = m.group(2) in ("bigger", "greater", "larger", "more")
        if a == b or (a > b) != big:
            errs.append(Error("numbers", nm.orig_pos(m.start(2)), nm.orig_pos(m.end(2)), None))
    return errs


_STEP_WORDS = {"twos": 2, "2s": 2, "threes": 3, "fours": 4, "fives": 5, "5s": 5, "tens": 10, "10s": 10, "hundreds": 100, "ones": 1,
               "twenties": 20, "twenty-fives": 25, "fifties": 50}


def _counting(nm: _Norm, prefix_len: int = 0) -> list[Error]:
    errs, s = [], nm.s
    for m in re.finditer(rf"{N}(?:\s*[,!.]\s*{N}){{2,}}", s):
        ks = re.findall(N, m.group(0))
        vals = [nm.num(k).value for k in ks]
        named = re.search(r"\bby\s+(twos|threes|fours|fives|tens|hundreds|ones|twenties|fifties|2s|5s|10s|twenty-fives)\b", s[:m.start()])
        step = _STEP_WORDS[named.group(1)] if named else vals[1] - vals[0]
        for i in range(1, len(vals)):
            if vals[i] - vals[i - 1] != step:
                errs.append(_num_err(nm, ks[i], vals[i - 1] + step if i > 1 or named else None, "counting"))
                break
    return errs


def _letters(nm: _Norm) -> list[Error]:
    errs, s = [], nm.s
    stop = {"it", "that", "this", "which", "who", "everything", "name", "word", "words", "names", "everyone", "she", "he", "they", "mine",
            "yours", "some", "many", "most", "all", "both", "each", "these", "those"}
    for m in re.finditer(rf"\b(?:the\s+word\s+)?[\"']?([a-z]+)[\"']?\s+(?:has|have|is spelled with|is made of|uses)\s+(?:just\s+|only\s+)?{N}\s+letters\b", s):
        w = m.group(1)
        if w in stop:
            continue
        right = 26 if w == "alphabet" and "word alphabet" not in m.group(0) else len(w)
        if nm.num(m.group(2)).value != right:
            errs.append(_num_err(nm, m.group(2), right, "letters"))
    for m in re.finditer(rf"\bthere\s+are\s+{N}\s+letters\s+in\s+(?:the\s+word\s+)?[\"']?([a-z]+)[\"']?", s):
        w = m.group(2)
        right = 26 if w == "the" else len(w)
        if w in stop or w == "the":
            continue
        if nm.num(m.group(1)).value != right:
            errs.append(_num_err(nm, m.group(1), right, "letters"))
    # spellings: "C-A-T spells cat", "cat is spelled C-A-T", "spell cat: C-A-T", "C-A-T, cat!"
    seq = r"((?:[a-z][-‐‑]){1,}[a-z])\b"
    pats = [rf"\b{seq}\s*,?\s*(?:spells|is|makes)\s+[\"']?([a-z]+)", rf"\b([a-z]{{2,}})[\"']?\s+is\s+spelled\s+{seq}",
            rf"\bspell(?:s|ing)?\s+[\"']?([a-z]{{2,}})[\"']?\s*(?:is|:|,)?\s*{seq}", rf"\b{seq}\s*[,!.]\s+[\"']?([a-z]{{2,}})\b"]
    for i, p in enumerate(pats):
        for m in re.finditer(p, s):
            letters_first = i in (0, 3)
            seq_s, w = (m.group(1), m.group(2)) if letters_first else (m.group(2), m.group(1))
            letters = re.sub(r"[^a-z]", "", seq_s)
            if i == 3 and (w[0] != letters[0] or abs(len(w) - len(letters)) > 2):
                continue
            if letters != w:
                gi = 1 if letters_first else 2
                a, b = nm.orig_pos(m.start(gi)), nm.orig_pos(m.end(gi))
                errs.append(Error("letters", a, b, "-".join(w.upper())))
    last_word = None
    for m in re.finditer(r"\b(?:the\s+word\s+)?[\"']?([a-z]{2,})[\"']?\s+(starts|begins|ends)\s+with\s+(?:the\s+letter\s+|a\s+|an\s+)?[\"']?([a-z])[\"']?(?=\s*(?:[,.!?;]|$)|\s+(?:and|or|but|like|for|as|too)\b)", s):
        w, where, ch = m.group(1), m.group(2), m.group(3)
        if w in ("and", "also", "then", "but", "it", "so") and last_word:
            w = last_word          # "cat starts with C and ends with T"
        last_word = w
        if w in stop or w in ("word", "letter", "name", "song", "story", "game", "day", "everything"):
            continue
        right = w[-1] if where == "ends" else w[0]
        if ch != right:
            a, b = nm.orig_pos(m.start(3)), nm.orig_pos(m.end(3))
            errs.append(Error("letters", a, b, right.upper()))
    for m in re.finditer(r"(?:^|[\s,!.])(?:the\s+letter\s+)[\"']?([a-z])[\"']?\s+is\s+a\s+(vowel|consonant)\b", s):
        ch, kind = m.group(1), m.group(2)
        if ch == "y":
            continue
        if (ch in "aeiou") != (kind == "vowel"):
            errs.append(Error("letters", nm.orig_pos(m.start(2)), nm.orig_pos(m.end(2)), "consonant" if kind == "vowel" else "vowel"))
    return errs


def _counts(nm: _Norm) -> list[Error]:
    errs, s = [], nm.s
    for sa, sb in _sentences(s):
        sent = s[sa:sb]
        best: dict[str, tuple] = {}     # number placeholder -> (distance, allowed values) of the NEAREST matching subject
        for noun_re, subj_re, ok, singular in _COUNTS:
            for m in re.finditer(rf"{N}\s+(?:[a-z]+\s+)?(?:{noun_re})\b", sent):
                for sm in re.finditer(rf"\b(?:(a|an|one|each|every|the|per|in|on)\s+)?({subj_re})\b", sent):
                    if singular and not sm.group(1):
                        continue
                    if re.search(r"#\d+\s+(?:[a-z]+\s+)?$", sent[max(0, sm.start() - 12):sm.start()]):
                        continue   # "two spiders have 16 legs", "in 2 weeks there are 14 days": not the per-one fact
                    d = abs(sm.start() - m.start())
                    k = m.group(1)
                    if k not in best or d < best[k][0]:
                        best[k] = (d, ok)
        for k, (_d, ok) in best.items():
            if nm.num(k).value not in ok:
                errs.append(_num_err(nm, k, min(ok) if len(ok) == 1 else None, "count"))
        for m in re.finditer(rf"\b(?:an?\s+|the\s+|every\s+|each\s+)?({'|'.join(_SIDES)})s?\b[^.!?#]{{0,20}}?\b(?:has|have|with|got)\s+{N}\s+(?:straight\s+)?(sides|corners|vertices|angles|edges)\b", sent):
            k = m.group(2)
            right = _SIDES[m.group(1)]
            if nm.num(k).value != right:
                errs.append(_num_err(nm, k, right, "count"))
        for m in re.finditer(rf"{N}\s+(?:straight\s+)?(?:sides|corners|vertices|angles)\b[^.!?#]{{0,12}}?\b(?:make|makes|is|are|on|in|of|for)\s+(?:an?\s+|the\s+|every\s+|each\s+)({'|'.join(_SIDES)})\b", sent):
            k, right = m.group(1), _SIDES[m.group(2)]
            if nm.num(k).value != right:
                errs.append(_num_err(nm, k, right, "count"))
    for rx, ok, skip_before in _GLOBAL_COUNTS:
        for m in rx.finditer(s):
            k = next(g for g in m.groups() if g is not None)
            if skip_before and re.search(skip_before, s[max(0, m.start() - 12):m.start()]):
                continue
            if re.search(r"\b(?:dwarf|rocky|gas|inner|outer|giant)\s+planets", s[m.start():m.end() + 1]):
                continue
            if nm.num(k).value not in ok:
                errs.append(_num_err(nm, k, min(ok) if len(ok) == 1 else None, "count"))
    return errs


def _shapes(nm: _Norm) -> list[Error]:
    errs, s = [], nm.s
    for m in re.finditer(rf"\b({'|'.join(_SIDES)})s?\b[^.!?]{{0,25}}?\b(?:has|have|with)\s+(?:{N}\s+|all\s+)(equal)\s+sides", s):
        shape = m.group(1)
        if shape in _EQUAL_OK or re.search(r"\b(?:equilateral|regular)\s+$", s[max(0, m.start() - 14):m.start()]):
            continue
        if m.group(2) is not None and nm.num(m.group(2)).value != _SIDES[shape]:
            continue   # "a rectangle has two equal sides": a count, not "all sides equal"
        a = nm.orig_pos(m.start(3))
        errs.append(Error("shape", a, nm.orig_pos(m.end(3)) + 1, ""))   # drop the word "equal " -> "has four sides"
    return errs


def _space(nm: _Norm) -> list[Error]:
    errs, s = [], nm.s
    for sa, sb in _sentences(s):
        for ca, cb in _clauses(s, sa, sb):
            cl = s[ca:cb]
            for phrase, names, right, rep in _SUPER:
                if not re.search(phrase, cl):
                    continue
                hits = [m for m in re.finditer(names, cl) if not re.search(r"\b(?:than|like|not)\s+$", cl[max(0, m.start() - 6):m.start()])]
                said = {m.group(1) for m in hits}
                if len(said) == 1 and not (said & right):
                    m = hits[0]
                    a, b = nm.orig_pos(ca + m.start(1)), nm.orig_pos(ca + m.end(1))
                    errs.append(Error("space" if names == _PLANET_RE else "superlative", a, b, rep))
            m = re.search(rf"{_PLANET_RE}\s+is\s+the\s+(first|second|third|fourth|fifth|sixth|seventh|eighth|#\d+(?:st|nd|rd|th)?)\s+planet\s+(?:from|away from)\s+the\s+sun", cl)
            if m and m.group(1) != "pluto":
                o = m.group(2)
                n = _ORD.get(o) or (int(nm.num(re.search(r"\d+", o).group(0)).value) if o.startswith("#") else None)
                if n and _PLANETS.index(m.group(1)) + 1 != n:
                    a, b = nm.orig_pos(ca + m.start(1)), nm.orig_pos(ca + m.end(1))
                    right = _PLANETS[n - 1] if 0 < n <= 8 else None
                    errs.append(Error("space", a, b, right.capitalize() if right else None))
    for m in re.finditer(r"\bthe\s+sun\s+is\s+(?:a|our|the)\s+(?:\w+\s+)?(planet)\b", s):
        errs.append(Error("space", nm.orig_pos(m.start(1)), nm.orig_pos(m.end(1)), "star"))
    for m in re.finditer(r"\bthe\s+moon\s+is\s+(?:a|our|the)\s+(?:\w+\s+)?(planet|star)\b", s):
        errs.append(Error("space", nm.orig_pos(m.start(1)), nm.orig_pos(m.end(1)), None))
    for m in re.finditer(r"\bpluto\s+is\s+(?:a|the\s+ninth)\s+(planet)\b", s):
        errs.append(Error("space", nm.orig_pos(m.start(1)), nm.orig_pos(m.end(1)), "dwarf planet"))
    return errs


def _name_span(text: str, i: int) -> tuple[int, int] | None:
    m = re.match(r"\s*((?:[A-Z][a-zA-Z.']*)(?:,?\s+(?:[A-Z][a-zA-Z.']*))*)", text[i:])
    if not m or not m.group(1):
        return None
    name = m.group(1)
    if name.endswith(".") and not name.endswith(("D.C.", "St.")):
        name = name.rstrip(".")
    return i + m.start(1), i + m.start(1) + len(name)


def _capitals(nm: _Norm) -> list[Error]:
    errs, s, t = [], nm.s, nm.text
    for m in re.finditer(rf"\bcapital\s+(?:city\s+)?of\s+(?:the\s+state\s+of\s+)?({_PLACE_RE})\s+is\s+(?:the\s+city\s+of\s+)?", s):
        place = m.group(1)
        sp = _name_span(t, nm.orig_pos(m.end()))
        if sp and not _cap_ok(place, t[sp[0]:sp[1]]):
            errs.append(Error("capital", sp[0], sp[1], CAPITALS[place]))
    for m in re.finditer(rf"{_CITY_RE}\s+is\s+(?:the\s+)?capital\s+(?:city\s+)?of\s+(?:the\s+state\s+of\s+)?({_PLACE_RE})\b", s):
        city, place = m.group(1), m.group(2)
        if not _cap_ok(place, city):
            errs.append(Error("capital", nm.orig_pos(m.start(1)), nm.orig_pos(m.end(1)), CAPITALS[place]))
    return errs


_CHECKS = (_arith, _counting, _letters, _counts, _shapes, _space, _capitals)


def find(text: str) -> list[Error]:
    """All checkable wrong facts in one piece of text (spans are in `text`)."""
    nm = _Norm(text)
    out = []
    for f in _CHECKS:
        try:
            out += f(nm)
        except Exception:   # noqa: BLE001 - a checker bug must never stop a toy from talking
            continue
    seen, uniq = set(), []
    for e in sorted(out, key=lambda e: (e.start, e.end)):
        if (e.start, e.end) not in seen:
            seen.add((e.start, e.end))
            uniq.append(e)
    return uniq


# ---------------------------------------------------------------- questions answered in the next sentence / line
@dataclass
class _Pending:
    kind: str
    right: object               # number, or capital name
    place: str = ""


def _questions(text: str) -> list[_Pending]:
    out = []
    for sa, sb in _sentences(text):
        sent = text[sa:sb]
        if "?" not in sent:
            continue
        nm = _Norm(sent)
        s = nm.s
        m = _Q_ARITH.search(s)
        if m:
            a, b = nm.num(m.group(1)).value, nm.num(m.group(3)).value
            r = _calc(_opname(m.group("op")), a, b)
            if r is not None:
                out.append(_Pending("arithmetic", r))
            continue
        m = re.search(r"\bhow\s+many\s+letters\s+(?:are\s+|is\s+)?(?:there\s+)?in\s+(?:the\s+word\s+)?[\"']?([a-z]+)", s) or \
            re.search(r"\bhow\s+many\s+letters\s+(?:does|do)\s+(?:the\s+word\s+)?[\"']?([a-z]+)[\"']?\s+have", s)
        if m:
            w = m.group(1)
            out.append(_Pending("letters", 26 if w in ("the", "alphabet") else len(w)))
            continue
        m = re.search(r"\bhow\s+many\s+(sides|corners|vertices|angles)\s+(?:does|do|are\s+on|on|in|has)\s+(?:an?\s+|the\s+)?(" + "|".join(_SIDES) + r")s?\b", s)
        if m:
            out.append(_Pending("count", _SIDES[m.group(2)]))
            continue
        hit = None
        for noun_re, subj_re, ok, _sing in _COUNTS:
            if re.search(rf"\bhow\s+many\s+(?:{noun_re})\b", s) and re.search(rf"\b(?:{subj_re})\b", s) and len(ok) == 1:
                hit = next(iter(ok))
                break
        if hit is None and re.search(r"\bhow\s+many\s+planets\b", s) and not re.search(r"\bdwarf\b", s):
            hit = 8
        if hit is not None:
            out.append(_Pending("count", hit))
            continue
        m = re.search(rf"\b(?:what'?s|what\s+is|do\s+you\s+know)\s+the\s+capital\s+(?:city\s+)?of\s+(?:the\s+state\s+of\s+)?({_PLACE_RE})\b", s)
        if m:
            out.append(_Pending("capital", CAPITALS[m.group(1)], m.group(1)))
    return out[-1:]   # only the last question can be the one answered next


def _answer_errors(p: _Pending, text: str) -> list[Error]:
    """Check the first sentence after a question against its known answer."""
    sents = _sentences(text)
    if not sents:
        return []
    a, b = sents[0]
    sent = text[a:b]
    nm = _Norm(sent)
    if p.kind == "capital":
        cities = [m for m in re.finditer(_CITY_RE, nm.s)]
        if cities and not any(_cap_ok(p.place, m.group(1)) for m in cities):
            m = cities[0]
            return [Error("capital", a + nm.orig_pos(m.start(1)), a + nm.orig_pos(m.end(1)), str(p.right))]
        return []
    m = _ANSWER.match(nm.s)
    if not m or re.match(rf"\s*(?:{'|'.join(_OPS.values())}|groups of)", nm.s[m.end():]):
        return []   # "Six times seven is 42" restates a sum of its own (checked by find), it is not a bare answer
    n = nm.num(m.group(1))
    if abs(n.value - float(p.right)) < 1e-9:
        return []
    fix = _fmt(p.right, n, sent[n.start:n.end]) if float(p.right).is_integer() and float(p.right) >= 0 else None
    return [Error(p.kind, a + n.start, a + n.end, fix)]


# ---------------------------------------------------------------- the guard used while a reply streams
@dataclass
class FactGuard:
    """One per reply. check(piece, line_so_far) returns the piece to speak (fixed where needed) or '' to drop it.
    `context` = text said just before this reply (the last toy line of the previous turn, the child's words) so an answer to a
    question asked there is checked too. fixed / dropped count what happened (numbers only; never the words)."""
    context: list[str] = field(default_factory=list)
    fixed: int = 0
    dropped: int = 0
    _pending: list = field(default_factory=list)

    def __post_init__(self):
        for c in self.context:
            if c:
                self._pending = _questions(c) or self._pending

    def check(self, piece: str, line_so_far: str = "") -> str:
        if not piece.strip():
            return piece
        prefix = line_so_far.rstrip()
        joined = (prefix + " " + piece) if prefix else piece
        off = len(joined) - len(piece)
        errs = [e for e in find(joined) if e.end > off]          # claims finished in this piece (earlier ones were checked before)
        if self._pending and not prefix:
            errs += [e for e in _answer_errors(self._pending[-1], joined) if e.end > off]
        out = piece
        if errs:
            if any(e.fix is None for e in errs) or any(e.start < off for e in errs):
                out = _drop_bad_sentences(piece, [e for e in errs], off)
                self.dropped += 1
            else:
                for e in sorted(errs, key=lambda e: -e.start):
                    a, b = e.start - off, e.end - off
                    out = out[:a] + e.fix + out[b:]
                out = re.sub(r"\s{2,}", " ", out)
                self.fixed += 1
        q = _questions(joined)
        if q:
            self._pending = q
        elif not prefix and self._pending:
            self._pending = []                                    # the sentence after a question was its answer (or moved on)
        return out


def _drop_bad_sentences(piece: str, errs: list[Error], off: int) -> str:
    keep = []
    for a, b in _sentences(piece):
        bad = any(e.end > off + a and e.start < off + b or (e.start < off and e.end > off + a and a == 0) for e in errs)
        if not bad:
            keep.append(piece[a:b].strip())
    return " ".join(keep)


def errors(lines: list[str]) -> int:
    """Wrong checkable facts in a sequence of spoken lines (for the grader): each line is checked alone and as the answer to a
    question in the line before."""
    n, pend = 0, []
    for ln in lines:
        n += len(find(ln))
        if pend:
            n += len(_answer_errors(pend[-1], ln))
        pend = _questions(ln)
    return n
