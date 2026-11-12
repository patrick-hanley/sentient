"""Conversation metrics for the child's speech during toy play (see docs/metrics.md for every proxy and its limits).

Privacy: text is only ever seen by `featurize_*` at the moment an utterance is understood; it is turned into numbers and
tags (word count, question form, mentions...) and dropped. The tracker keeps, in RAM only, the content words of the toys'
LAST line and the child's LAST utterance (to measure echo and topic continuity); each is replaced by the next one and
nothing is ever written. Everything that leaves this module (summaries, snapshots) is numbers and tags.

Shape: the tracker records small timestamped events; `analyze(events)` is a pure function that turns a session's events
into counts, the four quantitative metrics, and the five 0-4 scores. All timestamps are brain-monotonic seconds.
"""
from __future__ import annotations

import re
import statistics
import threading
import time
from collections import deque

# ---------------------------------------------------------------- knobs of the measurement (documented in docs/metrics.md)
RESPONSE_WINDOW_S = 10.0   # a child utterance this soon after a toy cue ends is a response; otherwise an initiation
LOOP_GAP_S = 10.0          # a pause longer than this between neighbouring turns ends a back-and-forth loop
MERGE_GAP_S = 1.2          # two child bursts closer than this (no toy turn between) are one utterance (the VAD split it)
ACTIVATION_S = 8.0         # a toy mention this soon after a tap/motion counts as "only when the toy was activated"
TURN_JOIN_S = 6.0          # toy lines this close together (no child between) are one toy turn
LATENCY_BANDS = ((1.0, 4), (2.5, 3), (5.0, 2))   # median latency below x s -> score; above the last band -> 1
TARGETS = {"T_R": 1.0, "IR": 1.0, "C_R": 5, "L_lo": 1.0, "L_hi": 2.0}
CATEGORIES = ("latency", "turn_taking", "initiation", "maintenance", "joint")
LABELS = {"latency": "Response latency", "turn_taking": "Reciprocal turn-taking", "initiation": "Verbal initiation",
          "maintenance": "Conversational maintenance", "joint": "Joint attention (verbal)"}

STOP = frozenset("""a an the and or but so if then than that this these those it its is are was were am be been being do does did
done have has had having i me my mine we us our you your yours he him his she her they them their to of in on at for with from by as
about into up down out off over not no yes yeah yep nope ok okay oh um uh hmm just really very too can could will would should may
might must what why how where who when which there here also like get got go going went one some any all more again""".split())
MINIMAL = frozenset("yeah yes yep yup no nope nah ok okay uh huh um mm hmm hm maybe sure idk hi hello hey bye".split())
EXPAND = re.compile(r"\b(because|cause|'cause|cuz|and then|so that|but|also|when|since|then|i think|i know|it has|it's like|like a)\b", re.I)
WANT = re.compile(r"\b(more|again|open|help me|stop|i want|i wanna|give me|can i|can you (?:say|sing|play|do|tell)|i need|please|my turn|let me)\b", re.I)
ATTN = re.compile(r"\b(look|see|watch|check|listen|guess what)\b", re.I)
DEMO = re.compile(r"\b(this|that|these|those|here|there)\b", re.I)
YOU = re.compile(r"\b(you|your|you're|yours)\b", re.I)
WH = re.compile(r"^\s*(what|why|how|where|who|when|which)\b", re.I)
YESNO = re.compile(r"^\s*(is|are|do|does|did|can|could|will|would|should|have|has)\b", re.I)
INVITE = re.compile(r"\b(tell me|show me|what do you think|your turn|let's|lets|want to|do you want|can you|would you like|what about you|"
                    r"how about you|any ideas|guess)\b", re.I)
FEATURE_WORDS = frozenset("""ear ears tail horn hat wing wings eye eyes nose foot feet arm arms hand hands color colour colors green white
hair costume face tummy belly spike spikes tooth teeth beak flipper flippers leg legs head body fur soft fluffy button""".split())
WORD = re.compile(r"[a-z']+")


def _tokens(text: str) -> list[str]:
    return WORD.findall((text or "").lower())


def _content(tokens) -> frozenset:
    out = set()
    for t in tokens:
        t = t.strip("'")
        if len(t) > 2 and t not in STOP and t not in MINIMAL:
            out.add(t[:-1] if t.endswith("s") and len(t) > 3 else t)
    return frozenset(out)


def is_question(text: str) -> bool:
    t = (text or "").strip()
    return t.endswith("?") or bool(WH.match(t)) or bool(YESNO.match(t) and len(t.split()) >= 3)


def toy_features(text: str) -> dict:
    """Numbers/tags about ONE toy line. Whether it asks or invites decides if it is a cue the child may answer."""
    t = (text or "").strip()
    q = is_question(t)
    return {"q": q, "open": bool(q and WH.match(t)), "invite": bool(INVITE.search(t)), "words": len(t.split())}


def child_features(text: str, toy_words: frozenset = frozenset(), prev_words: frozenset = frozenset(), names=frozenset()) -> dict:
    """Numbers/tags about ONE child utterance. `toy_words` = content words of the toys' last line; `prev_words` = the
    previous turn's (for topic continuity). The text itself is not kept."""
    toks = _tokens(text)
    n = len(toks)
    content = _content(toks)
    flat = " ".join(toks)
    name_hit = bool(names & set(toks))
    feature_hit = bool(FEATURE_WORDS & set(toks))
    # echolalia: (nearly) all of the child's content words came straight from the toy's last line
    echo_overlap = (len(content & toy_words) / len(content)) if content and n >= 2 else 0.0
    echo = n >= 2 and len(content) >= 1 and echo_overlap >= 0.8 and n <= max(3, int(len(toy_words) * 1.6) + 3)
    ref = name_hit or feature_hit
    question = is_question(text)
    link = n <= 3 or bool(content & (toy_words | prev_words)) or ref or bool(ATTN.search(flat))
    return {"words": n, "q": question, "want": bool(WANT.search(flat)) and n <= 6,
            "minimal": n <= 2 or all(t in MINIMAL for t in toks), "echo": bool(echo), "expand": bool(EXPAND.search(flat)) or n >= 8,
            "attn": bool(ATTN.search(flat)), "demo": bool(DEMO.search(flat)), "name": name_hit, "feature": feature_hit,
            "you": bool(YOU.search(flat)), "ref": ref, "link": bool(link)}


def merge_child(a: dict | None, b: dict | None) -> dict | None:
    """Two bursts of one utterance: words add up, flags OR together, topic link is the first burst's."""
    if a is None or b is None:
        return a or b
    out = {k: (a[k] or b[k]) if isinstance(a[k], bool) else a[k] for k in a}
    out["words"] = a["words"] + b["words"]
    out["minimal"] = a["minimal"] and b["minimal"] and out["words"] <= 2
    out["echo"] = a["echo"] and b["echo"]
    out["link"] = a["link"]
    return out


# ---------------------------------------------------------------- the pure analysis
def _pct(sorted_vals, p):
    return sorted_vals[min(len(sorted_vals) - 1, int(len(sorted_vals) * p))] if sorted_vals else None


def latency_score(median_s, n_cues, n_resp):
    """Rubric 0-4 from the MEDIAN response latency. None when no toy cue was given (nothing to respond to)."""
    if n_cues == 0:
        return None
    if n_resp == 0 or median_s is None:
        return 0            # nothing within the 10 s window
    for limit, score in LATENCY_BANDS:
        if median_s < limit:
            return score
    return 1


def loop_score(c_r: int) -> int:
    """Both speakers' turns count, so a toy cue + one child phrase is 2."""
    return 0 if c_r < 2 else 1 if c_r == 2 else 2 if c_r <= 4 else 3 if c_r <= 6 else 4


def initiation_score(comments: int, wants: int, duration_s: float) -> int:
    if comments + wants == 0:
        return 0
    if comments == 0:
        return 1            # only functional wants ("more", "open")
    per5 = comments * 300.0 / max(duration_s, 60.0)
    return 1 if per5 < 1 else 2 if per5 < 3 else 3 if per5 < 5 else 4


def maintenance_level(f: dict) -> int:
    if f["echo"]:
        return 0
    if f["minimal"] or f["words"] <= 2:
        return 1
    cue_back = f["q"] or f["name"] or (f["you"] and f["words"] >= 4)
    if cue_back and f["words"] >= 4 and (f["expand"] or f["words"] >= 6):
        return 4            # answers, adds an idea, and hands the turn back to the toy
    if f["expand"] or f["words"] >= 6:
        return 3
    return 2


def _round_half_up(x):
    return int(x + 0.5)


def analyze(events: list[dict], duration_s: float | None = None) -> dict:
    """Counts, metrics and scores from a session's events (see the module docstring for the event shapes):
      toy    {k, s, e, init, q, invite, open}  one toy turn (all lines of one go), s/e = first audio .. last audio
      child  {k, s, e, f}                        one child utterance; f = child_features() or None when no text was available
      audio  {k, s, e}                           any toy sound (for overlap), act {k, t} a tap/motion, barge {k, t}"""
    ev = sorted((dict(e) for e in events if e["k"] in ("toy", "child")), key=lambda e: e["s"])
    toys = [e for e in ev if e["k"] == "toy"]
    audio = [e for e in events if e["k"] == "audio"]
    acts = [e["t"] for e in events if e["k"] == "act"]
    barges = sum(1 for e in events if e["k"] == "barge")
    # merge the VAD's split bursts into utterances
    kids: list[dict] = []
    seq = []   # toy turns and child utterances in order
    for e in ev:
        if e["k"] == "child":
            last = seq[-1] if seq else None
            if last is not None and last["k"] == "child" and e["s"] - last["e"] <= MERGE_GAP_S:
                last["e"] = max(last["e"], e["e"])
                last["f"] = merge_child(last.get("f"), e.get("f"))
                continue
            e = dict(e)
            kids.append(e)
        seq.append(e)
    # classify: response (first utterance within the window after a cue) or initiation
    cue = None
    n_cues = n_resp = n_init = overlaps = 0
    lat: list[float] = []
    for e in seq:
        if e["k"] == "toy":
            if e["init"] or e["q"] or e["invite"]:
                n_cues += 1
                cue = {"e": e["e"], "answered": False}
            else:
                cue = None   # a plain statement closes the question that came before it
            continue
        e["role"] = "init"
        if cue and not cue["answered"] and e["s"] - cue["e"] <= RESPONSE_WINDOW_S:
            e["role"] = "resp"
            cue["answered"] = True
            n_resp += 1
            lat.append(max(0.0, e["s"] - cue["e"]))
        else:
            n_init += 1
        if any(a["s"] <= e["s"] < a["e"] for a in audio):
            overlaps += 1
    # reciprocity loop: alternating toy/child turns on one thread
    best = chain = 0
    last_end, last_spk = None, None
    for e in seq:
        spk = e["k"]
        fresh = last_end is None or e["s"] - last_end > LOOP_GAP_S
        if spk == "toy" and e["init"]:
            fresh = True    # a toy-started activity is a new loop
        if spk == "child" and e["role"] == "init" and e.get("f") and not e["f"]["link"]:
            fresh = True    # a spontaneous utterance unrelated to the last turn: the child changed the subject
        if fresh:
            chain, last_spk = 1, spk
        elif spk != last_spk:
            chain, last_spk = chain + 1, spk
        last_end = max(last_end or 0.0, e["e"])
        best = max(best, chain)
    child_turns = [e for e in seq if e["k"] == "child"]
    known = [e for e in child_turns if e.get("f")]
    # ---- duration
    stamps = [e["s"] for e in seq] + [e["e"] for e in seq] + [a["s"] for a in audio] + [a["e"] for a in audio]
    dur = duration_s if duration_s is not None else (max(stamps) - min(stamps) if stamps else 0.0)
    # ---- tags
    inits = [e for e in child_turns if e["role"] == "init"]
    wants = [e for e in inits if e.get("f") and e["f"]["want"] or (e.get("f") and e["f"]["minimal"] and not e["f"]["q"])]
    comments = [e for e in inits if e not in wants]
    tags = {"echo": sum(1 for e in known if e["f"]["echo"]), "wants": len(wants), "comments": len(comments),
            "questions": sum(1 for e in known if e["f"]["q"]), "refs": sum(1 for e in known if e["f"]["ref"]),
            "attn": sum(1 for e in known if e["f"]["attn"]), "expansions": sum(1 for e in known if e["f"]["expand"]),
            "minimal": sum(1 for e in known if e["f"]["minimal"]), "unknown_text": len(child_turns) - len(known)}
    # ---- scores
    med = statistics.median(lat) if lat else None
    scores = {"latency": latency_score(med, n_cues, n_resp), "turn_taking": loop_score(best) if (child_turns or toys) else None,
              "initiation": initiation_score(len(comments), len(wants), dur) if child_turns else (0 if toys else None)}
    pool = [e for e in known if e["role"] == "resp"] or known
    if not known:
        scores["maintenance"] = 0 if (not child_turns and toys) else None
    elif tags["echo"] * 2 >= len(known):
        scores["maintenance"] = 0       # mostly repeating the toy
    else:
        scores["maintenance"] = _round_half_up(statistics.mean(maintenance_level(e["f"]) for e in pool))
    scores["joint"] = _joint_score(child_turns, known, acts, toys)
    got = [v for v in scores.values() if v is not None]
    return {
        "counts": {"N_T": n_cues, "N_R": n_resp, "N_I": n_init, "unanswered": n_cues - n_resp, "child_utts": len(child_turns),
                   "toy_turns": len(toys), "barges": barges, "overlaps": overlaps},
        "metrics": {"T_R": round((n_resp + n_init) / n_cues, 2) if n_cues else None,
                    "IR": round(n_init / n_resp, 2) if n_resp else None, "C_R": best,
                    "L_med": round(med, 2) if med is not None else None,
                    "L_p25": round(_pct(sorted(lat), .25), 2) if lat else None, "L_p75": round(_pct(sorted(lat), .75), 2) if lat else None,
                    "L_p90": round(_pct(sorted(lat), .9), 2) if lat else None, "L_n": len(lat)},
        "scores": scores, "total": sum(got), "of": 4 * len(got), "duration_s": round(dur, 1), "tags": tags}


def _joint_score(child_turns, known, acts, toys):
    if not child_turns:
        return 0 if toys else None
    if not known:
        return None
    refs = [e for e in known if e["f"]["ref"] or e["f"]["attn"]]
    directing = [e for e in refs if e["role"] == "init" and (e["f"]["attn"] or (e["f"]["demo"] and e["f"]["ref"]))]
    if directing:
        return 4
    if any(e["role"] == "init" for e in refs):
        return 3
    if refs:
        # mentions only straight after a tap/motion = "only when the toy was activated"
        if all(any(0 <= e["s"] - a <= ACTIVATION_S for a in acts) for e in refs):
            return 1
        return 2
    return 1 if any(e["f"]["link"] for e in known) else 0


# ---------------------------------------------------------------- notes in plain language
def hour_bucket(wall: float) -> str:
    h = time.localtime(wall).tm_hour
    return "morning" if 5 <= h < 12 else "afternoon" if 12 <= h < 17 else "evening" if 17 <= h < 21 else "night"


STRENGTH = {"latency": "answers the toys quickly", "turn_taking": "keeps a back-and-forth going for several turns",
            "initiation": "starts conversations and comments on their own", "maintenance": "gives answers with extra detail and hands the turn back",
            "joint": "points out and talks about the toys' features"}
TARGET = {"latency": "taking a little time to answer; the toys will wait longer and ask shorter questions",
          "turn_taking": "longer back-and-forth chats; the toys will follow the child's topic more",
          "initiation": "starting talk on their own; the toys will leave pauses and invite them to tell or ask",
          "maintenance": "adding detail to answers; the toys will adjust the kind of questions they ask",
          "joint": "noticing and naming what the toys look like or are doing; the toys will point out things to notice"}


def qualitative(summary: dict) -> dict:
    sc = summary["scores"]
    strengths = [STRENGTH[c] for c in CATEGORIES if (sc.get(c) or 0) >= 3]
    targets = [TARGET[c] for c in sorted((c for c in CATEGORIES if sc.get(c) is not None and sc[c] < 3), key=lambda c: sc[c])]
    ctx = summary.get("context", {})
    factors = []
    if ctx.get("hour"):
        factors.append(f"time of day: {ctx['hour']}")
    if ctx.get("noise") is not None:
        factors.append("room noise: " + ("quiet" if ctx["noise"] < 250 else "moderate" if ctx["noise"] < 600 else "noisy"))
    if summary["counts"].get("barges"):
        factors.append(f"the child talked over the toys {summary['counts']['barges']} time(s)")
    if summary["counts"].get("unanswered"):
        factors.append(f"{summary['counts']['unanswered']} toy question(s) got no answer within 10 s")
    if ctx.get("toys"):
        factors.append(f"{ctx['toys']} toy(s) online")
    return {"strengths": strengths, "targets": targets, "factors": factors}


# ---------------------------------------------------------------- the tracker
class SessionTracker:
    """Collects events for the current session and hands a finished, numbers-only summary to `on_session(summary, subject)`.
    A session ends after `idle_gap_s` without activity, at `max_s` of length, or when the subject (the child marked
    'Playing now', or None for anonymous) changes."""

    def __init__(self, idle_gap_s=180.0, max_s=600.0, min_s=60.0, min_child_utts=3, toy_names=(), clock=time.monotonic,
                 wall=time.time, on_session=None, keep_anon=12, noise=None, toys_online=None):
        self.idle_gap_s, self.max_s, self.min_s, self.min_child_utts = idle_gap_s, max_s, min_s, min_child_utts
        self.names = frozenset(n.lower() for n in toy_names)
        self.clock, self.wall, self.on_session = clock, wall, on_session
        self.noise, self.toys_online = noise or (lambda: None), toys_online or (lambda: None)
        self.anon = deque(maxlen=keep_anon)    # finished sessions with no child attached: RAM only
        self.lock = threading.RLock()
        self.subject = None
        self.knobs = {}                        # the coaching knobs in force (numbers), stamped into each summary
        self._reset(None)
        self._toy_words, self._prev_words = frozenset(), frozenset()   # last toy line / last child utterance: content words, RAM only
        self._turn = None
        self.dropped = 0                       # sessions too short to score (counted, not kept)
        self.consec_unanswered = 0

    # ---- session lifecycle
    def _reset(self, t):
        self.events: list[dict] = []
        self.start_t = t
        self.last_t = t
        self.start_wall = self.wall()
        self.noise_samples: list[float] = []
        self.consec_unanswered = 0

    def _touch(self, t):
        if self.events and (t - self.last_t > self.idle_gap_s or t - self.start_t > self.max_s):
            self._finish()
        if not self.events:
            self.start_t, self.start_wall, self.last_t = t, self.wall(), t
        self.last_t = max(self.last_t, t)

    def set_subject(self, subject):
        with self.lock:
            if subject != self.subject:
                if self.events:
                    self._finish()
                self.subject = subject

    def _add(self, ev):
        t = ev.get("s", ev.get("t"))
        self._touch(t)
        self.events.append(ev)
        self.last_t = max(self.last_t, ev.get("e", t))
        n = self.noise()
        if n is not None and len(self.noise_samples) < 400:
            self.noise_samples.append(float(n))

    def tick(self, now=None):
        """Called regularly: closes a session that has been idle too long."""
        with self.lock:
            now = self.clock() if now is None else now
            if self.events and (now - self.last_t > self.idle_gap_s):
                self._finish()

    def close(self):
        with self.lock:
            if self.events:
                self._finish()

    def _finish(self):
        evs, subject = self.events, self.subject
        res = analyze(evs, duration_s=max(0.0, (self.last_t or 0) - (self.start_t or 0)))
        ctx = {"hour": hour_bucket(self.start_wall), "dow": time.localtime(self.start_wall).tm_wday, "toys": self.toys_online(),
               "noise": round(statistics.median(self.noise_samples), 1) if self.noise_samples else None}
        summary = {"v": 1, "start": int(self.start_wall), **res, "context": ctx, "knobs": dict(self.knobs)}
        summary["scored"] = (res["counts"]["child_utts"] >= self.min_child_utts and res["duration_s"] >= self.min_s
                             and res["counts"]["N_T"] >= 1)
        self._reset(None)
        self._toy_words = self._prev_words = frozenset()   # nothing about the last conversation is kept in RAM either
        if not summary["scored"]:
            self.dropped += 1
            return None
        if subject is None:
            self.anon.append(summary)
        if self.on_session:
            try:
                self.on_session(summary, subject)
            except Exception:  # noqa: BLE001 — measuring must never break the toys
                pass
        return summary

    # ---- text in, numbers out
    def toy_line(self, text: str) -> dict:
        """A toy line was spoken (or is about to be). Returns its features; remembers its content words for the next child turn."""
        f = toy_features(text)
        toks = _tokens(text)
        with self.lock:
            self._toy_words = _content(toks)
            if self._turn is not None:
                t = self._turn
                t["q"], t["open_q"], t["invite"] = t["q"] or f["q"], t["open_q"] or f["open"], t["invite"] or f["invite"]
        return f

    def child_text(self, start: float, end: float, text: str | None):
        """The child's utterance was understood. `text` is reduced to features here and dropped."""
        with self.lock:
            f = None
            if text is not None:
                f = child_features(text, self._toy_words, self._prev_words, self.names)
                self._prev_words = _content(_tokens(text))
            self._add({"k": "child", "s": start, "e": max(start, end), "f": f})
            self.consec_unanswered = 0   # any child speech ends a run of unanswered cues

    # ---- timing in
    def turn_open(self, t: float, initiated: bool):
        with self.lock:
            self._touch(t)
            self._turn = {"t0": t, "init": initiated, "q": False, "open_q": False, "invite": False}

    def turn_close(self, t: float, status="ok"):
        with self.lock:
            tr, self._turn = self._turn, None
            if tr is None or status != "ok":
                return
            ev = {"k": "toy", "s": tr["t0"], "e": max(t, tr["t0"]), "t0": tr["t0"], "tc": t, "audio": False,
                  "init": tr["init"], "q": tr["q"], "open": tr["open_q"], "invite": tr["invite"]}
            self._add(ev)
            for a in [a for a in self.events if a["k"] == "audio"]:
                self._attach(ev, a)
            if ev["init"] or ev["q"] or ev["invite"]:
                self.consec_unanswered += 1

    def _attach(self, toy_ev, a):
        """A toy sound inside a toy turn (the Atom's PLAYED can arrive just after the turn closed) sets that turn's span.
        If two turns' windows both cover the sound it belongs to the later-started one."""
        later = [e for e in self.events[-12:] if e["k"] == "toy" and e["t0"] > toy_ev["t0"] and e["t0"] - 0.5 <= a["s"]]
        open_turn = self._turn is not None and self._turn["t0"] > toy_ev["t0"] and self._turn["t0"] - 0.5 <= a["s"]   # the sound is a still-open turn's
        if later or open_turn or not (toy_ev["t0"] - 0.5 <= a["s"] <= toy_ev["tc"] + 3.0):
            return
        if not toy_ev["audio"]:
            toy_ev["s"], toy_ev["e"], toy_ev["audio"] = a["s"], a["e"], True
        else:
            toy_ev["s"], toy_ev["e"] = min(toy_ev["s"], a["s"]), max(toy_ev["e"], a["e"])

    def audio(self, start: float, end: float):
        with self.lock:
            a = {"k": "audio", "s": start, "e": max(start, end)}
            self._add(a)
            for ev in [e for e in self.events[-12:] if e["k"] == "toy"]:
                self._attach(ev, a)

    def barge(self, t: float | None = None):
        with self.lock:
            t = self.clock() if t is None else t
            self._add({"k": "barge", "t": t})

    def activation(self, t: float | None = None):
        with self.lock:
            t = self.clock() if t is None else t
            self._add({"k": "act", "t": t})

    # ---- views
    def live(self) -> dict:
        """Anonymous counters for the open dashboard: no identity, no text."""
        with self.lock:
            res = analyze(self.events, duration_s=max(0.0, (self.last_t or 0) - (self.start_t or 0))) if self.events else None
            return {"active": bool(self.events), "result": res, "consec_unanswered": self.consec_unanswered,
                    "recent": [{k: s[k] for k in ("start", "duration_s", "total", "of", "metrics", "scores")} for s in self.anon]}
