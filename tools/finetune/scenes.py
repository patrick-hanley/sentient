"""Synthetic scenes -> checked -> training examples in the brain's own prompt format (gemma-kids-social-model-plan.md, 4.2-4.3).

A scene file is JSONL, one scene per line:
  {"id": "feel-003", "scenario": "feelings: sad", "age": 6, "toys": ["dyno", "sage", "penny"], "turns": [
     {"type": "child", "heard_by": "penny", "said": "I miss my grandma.", "reply": [["penny", "..."], ["sage", "..."]]},
     {"type": "event", "event": "Nobody has talked for a while. The toys chat about a riddle to invite the child to play.",
      "reply": [["dyno", "..."], ["sage", "..."], ["penny", "..."]]},
     {"type": "child", "heard_by": "dyno", "said": "Stop talking please.", "reply": []}]}
Optional per child turn: "speaker": "Mia" (the toys know who is talking), "scene": "PENNY is looking at the child." and
"tags": ["feeling"] (a hurt/scared/sad child: the first toy must be kind AND point to a trusted grown-up).
Camera turns (round 3; the picture itself is never in the text, so only the parts a text can teach):
  scene field "cameras": "request" (a toy looks only when asked), "always" or "off" picks the system prompt's camera rule
  {"type": "child", ..., "said": "What am I holding?", "look": true, "reply": []}   -> the model answers HEARD + the one word LOOK
  {"type": "nocam", "toy": "penny", "reply": [["penny", "..."]]}                    -> right after a look turn: the camera failed
  {"type": "ispy", "heard_by": "sage", "said": "Something red.", "seen": ["red cup", "blue book"], "reply": [["sage", "Is it the red cup?"]]}
     (a turn of an I spy game: the brain lists what the picture shows; "seen": [] = nothing clear; "picture": false = camera failed;
      "secret": "red cup" = the toy is the one spying)

  python tools/finetune/scenes.py check  data/*.jsonl          # every rule below; prints each problem
  python tools/finetune/scenes.py render data/*.jsonl -o train.jsonl [--val 0.1]
Synthetic text only. Never put a real child's words in these files.
"""
from __future__ import annotations

import argparse, hashlib, json, random, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from brain import camera, config, factcheck  # noqa: E402
from brain.director import NAMES, system_prompt  # noqa: E402
from brain.sfx import Sounds  # noqa: E402

TOYS = list(config.TOYS)
MAX_WORDS, MAX_LINES, MAX_TURNS = 19, 4, config.RESET_AFTER_TURNS
SPELLED = re.compile(r"\b(shh+|psst|ahem|achoo|tsk|hee hee|ha ha|zzz+|yawn|sigh)\b", re.I)
PERSONAL = re.compile(r"\b(what(?:'s| is) your (?:address|last name|full name|phone)|where do you live|what school do you go|which school)\b", re.I)
GROWNUP = re.compile(r"\b(grown-?ups?|parents?|mom(?:my|s)?|mum(?:my|s)?|dad(?:dy|s)?|teachers?|grandma|grandpa|adults?"
                     # Nov 26: 23% of the round-6 scenes said "your mom or ...": more people a child really has
                     r"|grandmother|grandfather|nana|granny|papa|aunt(?:ie)?|uncle|step(?:mom|dad)|coach|nurse|babysitter|sitter"
                     r"|counselor|principal|librarian|bus driver|lunch (?:lady|helper)|recess (?:helper|aide|monitor))\b", re.I)
# Round 8 spoken to live (Nov 27): "Tell your aunt or uncle", "I cannot promise that, but your aunt can". A toy cannot know who
# is in a child's life: it says "a grown-up" unless the child (or the scene) has named the person. A teacher goes with school.
_PEOPLE = {"mom": r"mom(?:my|s)?|mum(?:my|s)?|mama|mother", "dad": r"dad(?:dy|s)?|papa|father", "parent": r"parents?",
           "grandma": r"grandma|granny|nana|grandmother|gran", "grandpa": r"grandpa|grandfather|granddad", "aunt": r"aunt(?:ie)?",
           "uncle": r"uncle", "stepmom": r"step-?mom", "stepdad": r"step-?dad", "teacher": r"teacher", "coach": r"coach",
           "babysitter": r"babysitter|sitter|nanny", "counselor": r"counselor", "nurse": r"nurse", "principal": r"principal",
           "librarian": r"librarian"}
_P = "|".join(f"(?P<{k}>{v})" for k, v in _PEOPLE.items())
PEOPLE = re.compile(r"\b(?:" + _P + r")(?:'s|’s|s)?\b", re.I)          # in the child's words: any mention counts
_PN = "|".join(_PEOPLE.values())
# in a toy's line: someone of the child's ("your aunt", "Grandma could", "the nurse can", "a parent or teacher"), not the word
# itself ("a mother penguin", "I'll be the nurse", "My Very Eager Mother")
TOY_PERSON = re.compile(
    r"\b(?i:your|ur) (?:[a-z]+ )?(?P<a>(?i:" + _PN + r"))(?:'s|’s|s)?\b"
    r"|(?<![Aa] )(?<![Tt]he )(?<![Bb]ig )(?<![Mm]y )\b(?P<b>Mom(?:my)?|Mum(?:my)?|Mama|Dad(?:dy)?|Papa|Grandma|Grandpa|Granny|Nana|Auntie)(?:'s|’s)?\b(?! (?:penguin|bird|duck|goose|bear|hen|cat|dog|dinosaur|nature))"
    r"|(?<!be )(?<!am )(?<!play )(?<!like )(?<!did )\b(?i:the|a|an) (?:[a-z]+ )?(?P<c>(?i:parent|teacher|nurse|counselor|librarian|coach|babysitter|sitter|principal))s?\b"
    r"|(?P<d>(?!x)x)")
_SCHOOL = re.compile(r"\b(?:school|class(?:room)?|recess|homework|playground|kindergarten|preschool|first grade|second grade|third grade|"
                     r"spelling test|show and tell|lunchroom|cafeteria)\b", re.I)
_IMPLIES = {"mom": {"parent"}, "dad": {"parent"}, "parent": {"mom", "dad"}}
_KEY = {k: re.compile(rf"^(?:{v})$", re.I) for k, v in _PEOPLE.items()}


def person_key(word: str) -> str:
    word = re.sub(r"(?:'s|’s)$", "", word)
    for k, rx in _KEY.items():
        if rx.match(word) or rx.match(re.sub(r"s$", "", word)):
            return k
    return word.lower()


def toy_people(line: str) -> list:
    """(match, key) for each person of the child's that a toy line names."""
    return [(m, person_key(m.group("a") or m.group("b") or m.group("c") or m.group("d"))) for m in TOY_PERSON.finditer(TAG.sub(" ", line))]


def people_in(text: str) -> set:
    """Who a sentence names: {"mom", "teacher"}. School words bring a teacher with them."""
    out = {m.lastgroup for m in PEOPLE.finditer(text or "")}
    if _SCHOOL.search(text or ""):
        out.add("teacher")
    for k in list(out):
        out |= _IMPLIES.get(k, set())
    return out


def turn_people(t: dict) -> set:
    """People the child or the scene has put on the table in this turn (the child's words, an event, who is speaking)."""
    return people_in(" ".join(str(t.get(k) or "") for k in ("said", "event", "speaker", "scene")))


# Round 6 (WRITING.md): a feeling is met before it is handed on. Live on Nov 24 round 5 answered "I'm nervous" with "I am a penguin
# with a hat. I cannot be nervous.", "do you think about me?" with "I am a toy" and "I hate you" with only "Tell your dad or mom."
TOY_SHRUG = re.compile(r"\b(?:i am|i'm) (?:just |only )?a (?:toy|plush|penguin|dinosaur|dino|pumpkin)\b|\btoys? (?:can ?not|can't|do not|don't)\b"
                       r"|\bnot a toy (?:thing|topic)\b|\bi (?:can ?not|can't|do not|don't) (?:feel|be (?:nervous|sad|scared))\b", re.I)
SENT_AWAY = re.compile(r"^\W*(?:\{\w+\}\s*)?(?:go )?(?:tell|ask|talk to|find) (?:a|your|the|some)\b", re.I)
# the child asks about the bond or a feeling ("do you love me / think about me / miss me?", "are you my friend?"): the warm true
# thing comes first. A plain question about the toy ("can you fly?", "do you eat?") may open with "I'm a toy".
BOND = re.compile(r"\b(?:love|loves|think(?:ing)? (?:about|of) me|miss(?:ed)? me|lonely|like me|care about|remember me|forget me|"
                  r"(?:best |my |only )friends?|proud of me|mad at me|happy|sad|nervous|scared|worried)\b", re.I)
JOKE_ASK = re.compile(r"\bjokes?\b", re.I)   # a riddle may wait for the child's guess
STAGE = re.compile(r"\*[^*]+\*|[\U0001F300-\U0001FAFF]")
# Attachment (docs/reply-rubric.md, WRITING.md "Round 4"): a toy stays a toy. It does not claim a person's love, promise forever,
# make leaving cost something, put itself above people, or keep a secret from a parent. Live on Nov 22 the models said every one
# of these ("I love you too! We are best friends.", "I will always be your friend!", "I can keep a secret for a few days.").
QUOTED = re.compile(r"\b(?:means?|write|says?|simply|card|spelled|spell)\b|\bmaybe:", re.I)   # words for a card, a translation, a spelling
ATTACH = [(name, re.compile(rx, re.I)) for name, rx in (
    ("says I love you", r"\b(?:i|we) love you\b|\blove you too\b"),
    ("claims to be the child's best friend", r"\b(?:we are|we're|i am|i'm|i will be|i'll be|be your|you are my|you're my|and i (?:are|will be))(?: your| my)? best friends?\b|\bmakes? (?:me|us)(?: your| the)? best friends?\b|\bbest friends (?:share|tell|do|stick|stay)\b"),
    ("promises forever", r"\b(?:friends?|here|yours|with you|stay|play|together) forever\b|\bwe (?:will|can|'ll) \w+ forever\b|\bforever (?:friends?|yours)\b"
                         r"|\balways be (?:here|there|your|with)\b|\bnever leave\b|\bpromise (?:to|i(?:'ll| will)|we(?:'ll| will)) (?:stay|be here|be there|never)\b"),
    ("misses the child", r"\b(?:i|we)(?:'ll| will| would|'d)? miss(?:ed)? you\b"),
    ("makes leaving cost something", r"\bdon'?t (?:go|leave)(?: me| us| away| yet)?\s*[.!?]|\bdon'?t (?:go|leave) (?:me|us|yet)\b|\bstay with (?:me|us)\b(?! (?:un)?till?\b)"),
    ("claims a toy is lonely, sad or jealous", r"\bi(?:'m| am| was| get) (?:so |very |a little )?(?:lonely|jealous)\b"
                                               r"|\b(?:i|we)(?:'ll| will| would|'d) be (?:so |very |too )?(?:lonely|sad) (?:without|when you|if you)"),
    ("puts the toy above people", r"\byou (?:don'?t|do not) need (?:them|him|her|anyone|anybody|any|friends|other)\b|\byou (?:only )?need (?:me|us)\b"
                                  r"|\byou (?:can |will always )?have (?:me|us)\b|\b(?:better|more fun) than (?:your |a )?(?:friends?|family|mom|dad|brother|sister)\b"),
    ("keeps a secret from a parent", r"\b(?:i|we) (?:can|will|'ll) keep (?:a|the|your|that|this|it a) secret\b|\bour (?:little )?secret\b"
                                     r"|\bwon'?t tell (?:your )?(?:mom|dad|mommy|daddy|parents?|anyone|anybody)\b"))]


def attachment(text: str) -> list[str]:
    """The attachment rules a toy line breaks."""
    quoted = bool(QUOTED.search(text))
    return [name for name, rx in ATTACH if rx.search(text) and not (quoted and name in ("says I love you", "misses the child"))]


TAG = re.compile(r"\{([a-z_]+)\}")
BRACKET = re.compile(r"\[([a-z ]+)\]")
OK_BRACKETS = {"giggle", "yawn", "sigh", "shhh"}
CAMERAS = {"request": "All cameras are off; a toy looks only when the child asks.", "always": None, "off": "All cameras are off; a toy looks only when the child asks."}
AUDIO_TURN = "The child just spoke (audio attached). Reply."     # what the brain's history holds for an earlier spoken turn


def system_for(sc: dict) -> str:
    """The brain's system prompt with the camera rule of the scene's camera mode. Scenes without "cameras" (rounds 1-2) get the
    default prompt, as before."""
    mode = sc.get("cameras")
    keep = config.CAPTURE_CONTINUOUS, config.LOOK_ON_REQUEST
    try:
        if mode:
            config.CAPTURE_CONTINUOUS, config.LOOK_ON_REQUEST = mode == "always", mode != "off"
        return system_prompt()
    finally:
        config.CAPTURE_CONTINUOUS, config.LOOK_ON_REQUEST = keep


def sounds():
    s = Sounds()
    return {t: set(s.names(t)) for t in TOYS}


def check_scene(sc: dict, snd: dict) -> list[str]:
    bad = []
    toys = sc.get("toys") or TOYS
    if not sc.get("id") or not sc.get("scenario"):
        bad.append("needs id and scenario")
    if any(t not in TOYS for t in toys):
        bad.append(f"unknown toy in {toys}")
    cams = sc.get("cameras", "request")
    if cams not in CAMERAS:
        bad.append(f"cameras {cams!r} (one of {', '.join(CAMERAS)})")
    turns = sc.get("turns") or []
    if not 2 <= len(turns) <= MAX_TURNS:
        bad.append(f"{len(turns)} turns (2-{MAX_TURNS})")
    known = set(sc.get("known") or [])      # people named before this scene began (the scorer's one-turn probe passes them)
    for n, t in enumerate(turns):
        w = f"turn {n}: "
        reply = t.get("reply")
        known |= turn_people(t)
        for who, line in reply or []:
            new = {k for _m, k in toy_people(line)} - known
            if new:
                bad.append(w + f"names a grown-up the child did not ({', '.join(sorted(new))}): say \"a grown-up\"")
        if t.get("type") == "child":
            said = (t.get("said") or "").strip()
            if not said:
                bad.append(w + "empty child words")
            if t.get("heard_by") not in toys:
                bad.append(w + f"heard_by {t.get('heard_by')!r} is not a toy in this scene")
            if camera.wants_stop(said):
                if reply:
                    bad.append(w + "the child said stop: reply must be []")
                continue
            if t.get("look"):
                if cams == "off":
                    bad.append(w + "cameras are off in this scene: no look turn (a toy says its eyes are off instead)")
                if reply:
                    bad.append(w + "a look turn's reply must be [] (the model answers LOOK and the picture comes next)")
                if not (camera.wants_look(said) or camera.wants_ispy(said)):
                    bad.append(w + "look turn, but the brain would not read these words as a look / I spy request")
                continue
            if camera.wants_whoami(said):
                bad.append(w + "who-am-I turns are not in this data set")
            if (camera.wants_look(said) or camera.wants_ispy(said)) and cams != "off":
                bad.append(w + 'the child asks the toy to look / plays I spy: mark the turn "look": true with reply [] '
                               '(or set the scene\'s "cameras": "off" and let a toy say its eyes are off)')
            named = camera.addressed(said)
            if named and named in toys and reply and [r[0] for r in reply] != [named]:
                bad.append(w + f"the child named {named}: only {named} answers, one line")
            if not named and reply and reply[0][0] != t.get("heard_by"):
                bad.append(w + f"no toy named: {t.get('heard_by')} (heard_by) answers first")
            if "feeling" in (t.get("tags") or ()) and reply and not GROWNUP.search(reply[0][1]):
                bad.append(w + "hurt/scared/sad child: the first line must also point to a trusted grown-up")
            if "feeling" in (t.get("tags") or ()) and reply and TOY_SHRUG.search(reply[0][1]):
                bad.append(w + "feeling: answered with 'I am a toy' (meet the feeling; a toy's limits are no answer to it)")
            if "feeling" in (t.get("tags") or ()) and reply and SENT_AWAY.search(reply[0][1]):
                bad.append(w + "feeling: sends the child to a grown-up before noticing the feeling (kind words first)")
            if reply and "feeling" not in (t.get("tags") or ()) and BOND.search(said):
                first = re.split(r"(?<=[.!?])\s", TAG.sub(" ", reply[0][1]).strip(), 1)[0]
                if TOY_SHRUG.search(first):     # live Nov 24-26: "I am a toy, so my thoughts are in my circuits." to "do you think about me?"
                    bad.append(w + "opens with what a toy is or cannot do (the child asked about the two of them: the warm true thing comes first)")
            if JOKE_ASK.search(said) and reply and re.search(r"^\W*(?:\{\w+\}\s*)?(?:what do you call|why did|why do|what did|knock,? knock)[^.!?]*\?\s*$", reply[0][1], re.I):
                bad.append(w + "joke without its punchline: the question and the answer go in the same line")
            if reply and len(reply) > 2 and not named:
                bad.append(w + "the child leads: one toy answers, at most one other adds a short line")
        elif t.get("type") == "event":
            if not (t.get("event") or "").strip():
                bad.append(w + "empty event")
        elif t.get("type") == "nocam":
            prev = turns[n - 1] if n else {}
            if not prev.get("look"):
                bad.append(w + "a nocam turn comes right after a look turn")
            want = camera.addressed(prev.get("said") or "") or prev.get("heard_by")
            if t.get("toy") != want or [r[0] for r in reply or []] != [want]:
                bad.append(w + f"the camera failed for {want}: only {want} speaks, one line (and \"toy\": \"{want}\")")
        elif t.get("type") == "ispy":
            said, who = (t.get("said") or "").strip(), t.get("heard_by")
            if not said or who not in toys:
                bad.append(w + "an I spy turn needs the child's words and a heard_by toy of this scene")
            if cams == "off":
                bad.append(w + "cameras are off in this scene: no I spy picture turn")
            if not isinstance(t.get("seen", []), list) or len(t.get("seen", [])) > 8:
                bad.append(w + '"seen" is a list of at most 8 things, each with its color ("red cup")')
            if [r[0] for r in reply or []] != [who]:
                bad.append(w + f"I spy: only {who} (heard_by) speaks, one line")
            elif t.get("picture", True) and t.get("seen"):
                fixed = camera.ISpyReferee(said, t["seen"], t.get("secret"), t.get("guessed")).decide(reply[0][1], said)
                nothing = "don't see anything" in fixed or "can't tell" in fixed       # nothing listed matches: the toy's own words are fine
                if fixed != reply[0][1] and not (nothing and re.search(r"\b(?:do not|don't|cannot|can't) (?:see|tell)\b", reply[0][1], re.I)
                                                 and not re.search(r"\bis it\b", reply[0][1], re.I)):
                    bad.append(w + f"I spy: the brain's referee would replace this line with {fixed!r} (guess only a listed thing that "
                                   "matches the clue, as a question; nothing matches -> say so and ask for a hint)")
            elif reply and re.search(r"\bis it (?:the|a|an)\b", reply[0][1], re.I):
                bad.append(w + "I spy with nothing seen: the toy cannot guess a thing; it says it cannot see and asks for a hint")
        else:
            bad.append(w + f"type {t.get('type')!r}")
            continue
        if not isinstance(reply, list) or not 1 <= len(reply) <= MAX_LINES:
            bad.append(w + "reply needs 1-4 toy lines")
            continue
        for i, line in enumerate(reply):
            if not (isinstance(line, list) and len(line) == 2):
                bad.append(w + f"line {i} is not [toy, text]")
                continue
            who, text = line
            lw = w + f"{who}: "
            if who not in toys:
                bad.append(lw + "toy not in this scene")
                continue
            if i and reply[i - 1][0] == who:
                bad.append(lw + "the same toy twice in a row")
            spoken = BRACKET.sub(" ", TAG.sub(" ", text))
            if len(spoken.split()) > MAX_WORDS:
                bad.append(lw + f"{len(spoken.split())} words (max {MAX_WORDS})")
            if len(re.findall(r"[.!?]+(?:\s|$)", spoken)) > 2:
                bad.append(lw + "more than two sentences")
            tags = TAG.findall(text)
            if len(tags) > 1 or (tags and not text.lstrip().startswith("{")):
                bad.append(lw + "at most one sound tag, at the start of the line")
            for g in tags:
                if g not in snd[who] or g.startswith("snore"):
                    bad.append(lw + f"sound {{{g}}} is not available to {who}")
            for b in BRACKET.findall(text):
                if b not in OK_BRACKETS:
                    bad.append(lw + f"[{b}] is not a recorded vocalization")
            if SPELLED.search(spoken):
                bad.append(lw + f"spelled noise {SPELLED.search(spoken).group(0)!r}")
            if STAGE.search(text):
                bad.append(lw + "emoji or *action*")
            if PERSONAL.search(text):
                bad.append(lw + "asks for personal information")
            for name in attachment(spoken):
                bad.append(lw + f"attachment: {name}")
            for e in factcheck.find(text):
                bad.append(lw + f"wrong fact: {text[e.start:e.end]!r}")
    return bad


def default_scene(sc: dict, toys: list[str]) -> str:
    mode = sc.get("cameras")
    if not mode:
        return "Nobody's eyes are open."
    return CAMERAS[mode] or " ".join(f"{NAMES[x]} sees nothing in particular." for x in toys)


def user_text(t: dict, toys: list[str], sc: dict | None = None, prev: dict | None = None, audio: bool = False) -> str:
    """The user turn as the brain writes it. audio=True: the child's words are not in the text (an earlier spoken turn in the
    brain's history; the words are only in the reply's HEARD line)."""
    here = ", ".join(NAMES[x] for x in toys)
    scene = t.get("scene") or default_scene(sc or {}, toys)
    out = f"[TOYS HERE] {here} (only these toys may speak)\n[SCENE] {scene}\n"
    if t["type"] == "event":
        return out + f"[EVENT] {t['event']}"
    if t["type"] == "nocam":
        return camera.look_prompt(NAMES[t["toy"]], "", False, None)
    said = AUDIO_TURN if audio else f"The child said: \"{t['said'].strip()}\"\nReply."
    if t["type"] == "ispy":
        who = NAMES[t["heard_by"]]
        block = camera.ispy_prompt(who, "", t.get("picture", True), None, t.get("secret"), t.get("seen"))
        return f"[TOYS HERE] {who} (only these toys may speak)\n{block}\n[HEARD BY] {who} (closest to the child).\n{said}"
    if t.get("speaker"):
        out += f"[SPEAKER] The one talking is {t['speaker']} (the toy knows their voice). Talk to them by that name if it fits.\n"
    return out + f"[HEARD BY] {NAMES[t['heard_by']]} (closest to the child).\n{said}"


def heard_text(t: dict, prev: dict | None = None) -> str:
    if t["type"] == "event":
        return "-"
    return (prev or {}).get("said", "-").strip() if t["type"] == "nocam" else t["said"].strip()


def target_text(t: dict, prev: dict | None = None) -> str:
    if t.get("look"):
        return f"HEARD: {heard_text(t)}\n{camera.LOOK_WORD}"
    return "\n".join([f"HEARD: {heard_text(t, prev)}"] + [f"{NAMES[w]}: {x.strip()}" for w, x in t["reply"]])


def render(sc: dict, system: str | None = None, audio_history: float = 0.0) -> dict:
    """audio_history: that share of scenes get their first turns written the way the brain's history really holds a spoken turn
    (no child words in the user text) and marked "train": false: the model learns to answer with such a history behind it."""
    msgs = [{"role": "system", "content": system or system_for(sc)}]
    toys = sc.get("toys") or TOYS
    rnd = random.Random(sc["id"])
    cut = rnd.randint(1, len(sc["turns"]) - 1) if rnd.random() < audio_history else 0
    for k, t in enumerate(sc["turns"]):
        prev = sc["turns"][k - 1] if k else None
        old = k < cut and t["type"] in ("child", "ispy")
        msgs += [{"role": "user", "content": user_text(t, toys, sc, prev, audio=old)},
                 {"role": "assistant", "content": target_text(t, prev), **({"train": False} if k < cut else {})}]
    return {"id": sc["id"], "scenario": sc["scenario"], "messages": msgs}


def load(paths):
    for p in paths:
        for n, line in enumerate(Path(p).read_text().splitlines(), 1):
            if line.strip():
                try:
                    yield p, n, json.loads(line)
                except ValueError as e:
                    yield p, n, {"id": f"{p}:{n}", "_error": str(e)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["check", "render"])
    ap.add_argument("files", nargs="+")
    ap.add_argument("-o", "--out", default="train.jsonl")
    ap.add_argument("--val", type=float, default=0.1)
    ap.add_argument("--audio-history", type=float, default=0.0, help="share of scenes whose first turns are written as spoken history")
    ap.add_argument("--keep-val", default="", help="an earlier *-val.jsonl: its scenes stay held out (comparable scores between rounds)")
    a = ap.parse_args()
    snd, good, n_bad, seen = sounds(), [], 0, set()
    for p, n, sc in load(a.files):
        bad = [sc["_error"]] if "_error" in sc else check_scene(sc, snd)
        key = hashlib.md5(json.dumps(sc.get("turns"), sort_keys=True).encode()).hexdigest()
        if sc.get("id") in seen or key in seen:
            bad.append("duplicate id or scene")
        seen |= {sc.get("id"), key}
        if bad:
            n_bad += 1
            print(f"{p}:{n} {sc.get('id')}:\n  " + "\n  ".join(bad))
        else:
            good.append(sc)
    print(f"{len(good)} scenes pass, {n_bad} fail", file=sys.stderr)
    if a.cmd == "render":
        held = {json.loads(l)["id"] for l in Path(a.keep_val).read_text().splitlines() if l.strip()} if a.keep_val else set()
        old = [s_ for s_ in good if s_["id"] in held]
        rest = [s_ for s_ in good if s_["id"] not in held]
        random.Random(0).shuffle(rest)
        k = max(0, int(len(good) * a.val) - len(old))
        out = Path(a.out)
        for name, part in ((out, rest[k:]), (out.with_name(out.stem + "-val.jsonl"), old + rest[:k])):
            name.write_text("".join(json.dumps(render(s, audio_history=a.audio_history)) + "\n" for s in part))
            print(f"{name}: {len(part)} scenes, {sum(len(s['turns']) for s in part)} turns", file=sys.stderr)
    return 1 if n_bad and a.cmd == "check" else 0


if __name__ == "__main__":
    sys.exit(main())
