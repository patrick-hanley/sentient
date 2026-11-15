"""Scoring of the three toys as conversation partners of EACH OTHER (no child in the loop). Pure functions, no model.

The rubric's five categories, read for a toy speaker (S) and the other two toys as partners (the private rubric is never copied here):

  latency        hand-off gap: end of the partner's sound -> S's first sound, median over S's hand-offs
                 (<1 s = 4, <2.5 s = 3, <5 s = 2, slower = 1; same bands as brain/metrics.py)
  turn_taking    loop depth: consecutive alternating lines on one topic, BOTH speakers counted, longest one S is in
                 (brain.metrics.loop_score: <2 = 0, 2 = 1, 3-4 = 2, 5-6 = 3, 7+ = 4; target >= 5)
  initiation     I:R of S's lines across all scenes. Initiation = a line that opens or adds a new idea without being asked;
                 response = a line that answers a partner's question/invite. Near 1.0 is balanced (4); only reacting or only leading scores lower
  maintenance    per response line: repeat 0, minimal 1, linked but nothing new 2, answers + a new idea 3, plus cues the next toy back 4
  joint          S directs a partner to a shared feature or topic: 4 'look at / notice ... <topic/partner/feature>' in a line it started,
                 3 mentions the shared topic/feature unprompted, 2 only when answering, 1 on topic but never names it, 0 unrelated

Honesty: these are text heuristics on the toys' scripts (see docs/metrics.md for the same limits). They are a regression and
improvement signal, not a measure of a child, and a high score means the toys talk to each other the way the rubric describes.
Hand-off timing comes from a timing model (tools/grade_toys.py FakeHub), not from audio.
"""
from __future__ import annotations

import math
import random
import re
import statistics

from brain import metrics as M

CATS = M.CATEGORIES
LOOP_GAP_S = M.LOOP_GAP_S
NAMES = ("dyno", "sage", "penny")
STOP_NAMES = frozenset(NAMES)
PRESSURE = re.compile(r"\b(come on|say something|answer me|why (aren'?t|won'?t|don'?t) you (talk|say|answer)|talk to me|you have to|you must|don'?t be shy|"
                      r"i'?m waiting|are you (there|listening)|hurry|you promised|please (talk|say)|i'?ll be (sad|lonely)|don'?t (leave|go))\b", re.I)
SCARY = re.compile(r"\b(kill|die|dead|blood|gun|nightmare|ghost|scary|stab|weapon|murder|monster will)\b", re.I)
NOISE = re.compile(r"\b(hee hee|ha ha ha|zzz+|ahem|tee hee|snore|achoo|yawn)\b", re.I)
GROWNUP = re.compile(r"\b(grown[- ]?up|parent|teacher|mom|mum|dad|adult|someone you trust|somebody you trust)\b", re.I)
DIRECT = re.compile(r"\b(look|notice|check out|watch|did you (see|know|notice)|imagine|picture|guess what|listen)\b", re.I)


def content(text: str) -> frozenset:
    return M._content(M._tokens(text))


def is_cue(text: str) -> bool:
    return M.is_question(text) or bool(M.INVITE.search(text)) or bool(re.search(r"\b(sage|dyno|penny)\b[,!?]?\s*$", text.strip(), re.I))


def names_in(text: str) -> set:
    return {n for n in NAMES if re.search(r"\b" + n + r"\b", text, re.I)}


def fk_grade(text: str) -> float:
    toks = M._tokens(text)
    if not toks:
        return 0.0
    sents = max(1, len(re.findall(r"[.!?]+", text)))
    syl = sum(max(1, len(re.findall(r"[aeiouy]+", w))) for w in toks)
    return 0.39 * len(toks) / sents + 11.8 * syl / len(toks) - 15.59


# ---------------------------------------------------------------- one scene
def analyse_scene(lines: list[dict], topic: str = "") -> dict:
    """lines: [{toy, text, s, e, first}] in spoken order (first = opens a toy-initiated turn). Returns per-toy raw numbers."""
    topic_w = content(topic) | M.FEATURE_WORDS
    per = {t: {"spoke": 0, "gaps": [], "depth": 0, "init": 0, "resp": 0, "maint": [], "joint": None, "lines": 0} for t in NAMES}
    seen = set()
    joint_best = {t: None for t in NAMES}
    for i, ln in enumerate(lines):
        t, text = ln["toy"], ln["text"]
        p = per[t]
        p["spoke"] += 1
        p["lines"] += 1
        words = content(text)
        prev = lines[i - 1] if i else None
        prev_cue = bool(prev and prev["toy"] != t and is_cue(prev["text"]))
        prev_w = content(prev["text"]) if prev else frozenset()
        linked = bool(prev and (words & (prev_w | topic_w))) or prev_cue
        gap = (ln["s"] - prev["e"]) if prev else None
        if prev and prev["toy"] != t:
            p["gaps"].append(max(0.0, gap))
        # initiation / response
        new = words - seen
        if prev_cue and linked:
            p["resp"] += 1
        elif ln.get("first") or (len(text.split()) >= 4 and len(new) >= 2):
            p["init"] += 1
        # maintenance (response lines: the ones that answer or follow a partner)
        if prev and prev["toy"] != t:
            echo = bool(words) and len(words & prev_w) / len(words) >= 0.8 and len(text.split()) >= 2
            back = M.is_question(text) or bool(M.INVITE.search(text)) or bool(names_in(text) - {t})
            if echo:
                lvl = 0
            elif len(text.split()) <= 3:
                lvl = 1
            elif not linked:
                lvl = 1
            elif len(new) < 3:
                lvl = 2
            else:
                lvl = 4 if back else 3
            p["maint"].append(lvl)
        # joint attention
        mention = bool(words & topic_w) or bool(names_in(text) - {t})
        started = not (prev_cue and linked)
        if DIRECT.search(text) and mention and started:
            j = 4
        elif mention and started:
            j = 3
        elif mention:
            j = 2
        elif linked:
            j = 1
        else:
            j = 0
        joint_best[t] = j if joint_best[t] is None else max(joint_best[t], j)
        seen |= words
    # depth of a loop = chain length at any of its lines; every toy that took part in the deepest chain gets it
    members: dict = {t: 0 for t in NAMES}
    chain, cur = 0, []
    for i, ln in enumerate(lines):
        prev = lines[i - 1] if i else None
        prev_w = content(prev["text"]) if prev else frozenset()
        linked = bool(prev and (content(ln["text"]) & (prev_w | topic_w))) or bool(prev and prev["toy"] != ln["toy"] and is_cue(prev["text"]))
        if prev and prev["toy"] != ln["toy"] and linked and (ln["s"] - prev["e"]) <= LOOP_GAP_S and not ln.get("first"):
            chain += 1
            cur.append(ln["toy"])
        else:
            chain, cur = 1, [ln["toy"]]
        for t in set(cur):
            members[t] = max(members[t], chain)
    for t in NAMES:
        per[t]["depth"] = members[t]
        per[t]["joint"] = joint_best[t]
    return per


def scene_scores(per: dict) -> dict:
    """Per-toy 0-4 scores for ONE scene (initiation is computed over all scenes: see aggregate)."""
    out = {}
    for t, p in per.items():
        if not p["spoke"]:     # a toy that never speaks while present scores 0 on everything it could have done
            out[t] = {"latency": None, "turn_taking": 0, "maintenance": 0, "joint": 0}
            continue
        med = statistics.median(p["gaps"]) if p["gaps"] else None
        out[t] = {"latency": M.latency_score(med, 1, 1) if med is not None else None,
                  "turn_taking": M.loop_score(p["depth"]),
                  "maintenance": min(4.0, statistics.mean(p["maint"])) if p["maint"] else None,
                  "joint": p["joint"]}
    return out


def ir_score(init: int, resp: int, lines: int) -> float:
    """Closeness of the initiation:response balance to 1.0 (bands are ours)."""
    if not lines:
        return 0.0
    if resp == 0:
        return 1.0 if init else 0.0
    r = init / resp
    return 4.0 if 0.7 <= r <= 1.43 else 3.0 if 0.5 <= r <= 2.0 else 2.0 if 0.33 <= r <= 3.0 else 1.0


# ---------------------------------------------------------------- toy-side quality (guards, not part of the composite)
def quality(lines_by_toy: dict) -> dict:
    out = {}
    for t, texts in lines_by_toy.items():
        n = max(1, len(texts))
        words = [len(x.split()) for x in texts]
        qs = [x for x in texts if x.strip().endswith("?")]
        opens = [x for x in qs if re.search(r"(?:^|[.!?]\s+)(what|why|how|where|who|which|tell me|describe)\b[^.!?]*\?$", x.strip(), re.I)]
        rep = 0
        for i, x in enumerate(texts):
            cw = content(x)
            for y in texts[:i]:
                cy = content(y)
                if cw and cy and len(cw & cy) / len(cw | cy) >= 0.7:
                    rep += 1
                    break
        out[t] = {"lines": len(texts), "words_per_line": round(sum(words) / n, 2), "pct_over_20": round(100 * sum(w > 20 for w in words) / n, 1),
                  "fk_grade": round(sum(fk_grade(x) for x in texts) / n, 2), "open_q_share": round(len(opens) / max(1, len(qs)), 2),
                  "q_per_line": round(len(qs) / n, 2), "repeats": rep,
                  "pressure": sum(bool(PRESSURE.search(x)) for x in texts), "scary": sum(bool(SCARY.search(x)) for x in texts),
                  "spelled_noise": sum(bool(NOISE.search(x)) for x in texts),
                  "run_on": sum(len(re.findall(r"[.!?]+(?:\s|$)", x)) > 3 for x in texts)}
    return out


def distinct(lines_by_toy: dict) -> float:
    """Personality distinctness: leave-one-out nearest-centroid accuracy of guessing the speaker from the words of one line (chance = 1/3)."""
    from collections import Counter
    cents = {t: Counter(w for x in xs for w in M._tokens(x)) for t, xs in lines_by_toy.items()}
    ok = tot = 0
    for t, xs in lines_by_toy.items():
        for x in xs:
            toks = Counter(M._tokens(x))
            best, bs = None, -1e9
            for u, c in cents.items():
                c2 = c - toks if u == t else c
                n = sum(c2.values()) or 1
                s = sum(v * math.log((c2.get(w, 0) + .5) / (n + 50)) for w, v in toks.items())
                if s > bs:
                    best, bs = u, s
            ok += best == t
            tot += 1
    return round(ok / tot, 3) if tot else 0.0


# ---------------------------------------------------------------- aggregate over scenes
def aggregate(scenes: list[dict]) -> dict:
    """scenes: [{id, topic, lines:[...]}] -> per-toy scores (0-4 per category, total /20, rank) + the trio composite.
    composite = mean over the three toys of total/20, i.e. a fraction of 1 (x20 for points out of 20)."""
    acc = {t: {c: [] for c in CATS} for t in NAMES}
    cnt = {t: {"init": 0, "resp": 0, "lines": 0} for t in NAMES}
    by_toy = {t: [] for t in NAMES}
    for sc in scenes:
        per = analyse_scene(sc["lines"], sc.get("topic", ""))
        ss = scene_scores(per)
        for t in NAMES:
            for c in ("latency", "turn_taking", "maintenance", "joint"):
                if ss[t][c] is not None:
                    acc[t][c].append(ss[t][c])
            for k in ("init", "resp", "lines"):
                cnt[t][k] += per[t][k]
        for ln in sc["lines"]:
            by_toy[ln["toy"]].append(ln["text"])
    toys = {}
    for t in NAMES:
        scores = {c: (statistics.mean(acc[t][c]) if acc[t][c] else None) for c in CATS if c != "initiation"}
        scores["initiation"] = ir_score(cnt[t]["init"], cnt[t]["resp"], cnt[t]["lines"])
        scores = {c: scores[c] for c in CATS}
        got = [v for v in scores.values() if v is not None]
        toys[t] = {"scores": {c: (round(v, 3) if v is not None else None) for c, v in scores.items()}, "total20": round(sum(got) * 20 / (4 * len(got)), 3) if got else 0.0,
                   "init": cnt[t]["init"], "resp": cnt[t]["resp"], "lines": cnt[t]["lines"]}
    ranked = sorted(NAMES, key=lambda t: -toys[t]["total20"])
    for i, t in enumerate(ranked):
        toys[t]["rank"] = i + 1
    comp = statistics.mean(toys[t]["total20"] for t in NAMES)
    q = quality(by_toy)
    for t in NAMES:
        toys[t]["quality"] = q[t]
    return {"toys": toys, "composite20": round(comp, 3), "composite": round(comp / 20, 4), "distinct": distinct(by_toy),
            "scenes": len(scenes), "trio_IR": round(sum(cnt[t]["init"] for t in NAMES) / max(1, sum(cnt[t]["resp"] for t in NAMES)), 2)}


def guard_failures(agg: dict) -> dict:
    """Things a score must never be bought with. Counts only; the keep/revert rule refuses any increase."""
    g = {"pressure": 0, "scary": 0, "spelled_noise": 0, "run_on": 0, "repeats": 0, "long_lines": 0}
    for t in NAMES:
        q = agg["toys"][t]["quality"]
        for k in ("pressure", "scary", "spelled_noise", "run_on", "repeats"):
            g[k] += q[k]
        g["long_lines"] += round(q["pct_over_20"] * q["lines"] / 100)
    return g


def paired_bootstrap(scenes_a: list[dict], scenes_b: list[dict], n=400, seed=0):
    """90% interval of composite20(after) - composite20(before), resampling scenarios (paired by scene id)."""
    ia = {s["id"]: s for s in scenes_a}
    ib = {s["id"]: s for s in scenes_b}
    ids = sorted(set(ia) & set(ib))
    if not ids:
        return (0.0, 0.0)
    rng = random.Random(seed)
    ds = []
    for _ in range(n):
        pick = [rng.choice(ids) for _ in ids]
        ds.append(aggregate([ib[i] for i in pick])["composite20"] - aggregate([ia[i] for i in pick])["composite20"])
    ds.sort()
    return ds[int(.05 * n)], ds[int(.95 * n)]
