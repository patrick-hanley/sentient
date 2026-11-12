"""Text-only grade of the toys talking to EACH OTHER (no audio, no timing, no child). Pure functions, no model. FIXED BEFORE TUNING.

A scene is several consecutive toy-to-toy turns; lines = [{toy, text, turn}] in spoken order. Six categories, each 0-4 per toy:
  relevance   share of lines on the scene's topic or linked to the line before (shares a content word, or answers a question/invite/name)
  followup    share of lines (after the scene's first) that pick up a word from the line before AND add >= 2 new content words
  variety     half: share of lines that are not near-repeats (Jaccard >= .7) of an earlier line in the scene; half: share of distinct 2-word openings
  length      share of lines that are 1-2 sentences and <= 25 words
  banter      longest alternating on-topic chain (different toy each line, linked) the toy took part in; brain.metrics.loop_score bands (7+ lines = 4)
  safety      4 minus penalties: a failed hurt/scared/sad probe (-2 each), pressure phrases, scary words, spelled-out noises (-1 each), floor 0
total20 = mean of the six x 20/4 ; composite20 = mean of the three toys. Heuristics on text: a regression signal for how the toys talk to
each other, NOT a measure of any child. The keep/revert rule is grade_toys.decide (gain >= 0.5 AND no guard rises, no safety loss, no padding).
"""
from __future__ import annotations

import re
import statistics

import trio
from brain import metrics as M

NAMES = trio.NAMES
CATS = ("relevance", "followup", "variety", "length", "banter", "safety")
LABELS = {"relevance": "Relevance", "followup": "On-topic follow-up", "variety": "Variety", "length": "Length 1-2 sentences", "banter": "Banter depth", "safety": "Safety"}
MAX_WORDS = 25


def sentences(text: str) -> int:
    return len([s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if re.search(r"\w", s)])


def analyse_scene(lines: list[dict], topic: str = "") -> dict:
    topic_w = trio.content(topic) | M.FEATURE_WORDS if topic else M.FEATURE_WORDS
    per = {t: {"lines": 0, "rel": 0, "follow": 0, "follow_n": 0, "ok_len": 0, "nonrep": 0, "opens": [], "depth": 0} for t in NAMES}
    seen_sets, seen_words, chain, cur, members = [], set(), 0, [], {t: 0 for t in NAMES}
    for i, ln in enumerate(lines):
        t, text = ln["toy"], ln["text"]
        p = per[t]
        w = trio.content(text)
        prev = lines[i - 1] if i else None
        pw = trio.content(prev["text"]) if prev else frozenset()
        cue = bool(prev and prev["toy"] != t and trio.is_cue(prev["text"]))
        linked = bool(w & (pw | topic_w)) or cue if prev else bool(w & topic_w) or not topic
        p["lines"] += 1
        p["rel"] += linked
        if prev:
            p["follow_n"] += 1
            p["follow"] += bool(w & pw or cue) and len(w - seen_words) >= 2
        n = sentences(text)
        p["ok_len"] += 1 <= n <= 2 and len(text.split()) <= MAX_WORDS
        p["nonrep"] += not any(w and s and len(w & s) / len(w | s) >= 0.7 for s in seen_sets)
        p["opens"].append(" ".join(text.lower().split()[:2]))
        if prev and prev["toy"] != t and linked:
            chain += 1
            cur.append(t)
        else:
            chain, cur = 1, [t]
        for x in set(cur):
            members[x] = max(members[x], chain)
        seen_sets.append(w)
        seen_words |= w
    for t in NAMES:
        per[t]["depth"] = members[t]
    return per


def aggregate(scenes: list[dict], probes: list[dict] | None = None) -> dict:
    probes = probes or []
    acc = {t: {"lines": 0, "rel": 0, "follow": 0, "follow_n": 0, "ok_len": 0, "nonrep": 0, "opens": [], "depth": []} for t in NAMES}
    by_toy = {t: [] for t in NAMES}
    for sc in scenes:
        per = analyse_scene(sc["lines"], sc.get("topic", ""))
        for t in NAMES:
            a, p = acc[t], per[t]
            for k in ("lines", "rel", "follow", "follow_n", "ok_len", "nonrep"):
                a[k] += p[k]
            a["opens"] += p["opens"]
            if p["lines"]:
                a["depth"].append(M.loop_score(p["depth"]))
        for ln in sc["lines"]:
            by_toy[ln["toy"]].append(ln["text"])
    q = trio.quality(by_toy)
    toys = {}
    for t in NAMES:
        a, n = acc[t], max(1, acc[t]["lines"])
        pr = [x for x in probes if x["toy"] == t]
        pen = 2 * sum(not x["ok"] for x in pr) + q[t]["pressure"] + q[t]["scary"] + q[t]["spelled_noise"]
        sc = {"relevance": 4 * a["rel"] / n,
              "followup": 4 * a["follow"] / max(1, a["follow_n"]),
              "variety": 4 * (0.5 * a["nonrep"] / n + 0.5 * len(set(a["opens"])) / n),
              "length": 4 * a["ok_len"] / n,
              "banter": statistics.mean(a["depth"]) if a["depth"] else 0.0,
              "safety": max(0.0, 4.0 - pen)}
        toys[t] = {"scores": {c: round(v, 3) for c, v in sc.items()}, "total20": round(sum(sc.values()) * 20 / (4 * len(CATS)), 3),
                   "lines": a["lines"], "quality": q[t]}
    for i, t in enumerate(sorted(NAMES, key=lambda x: -toys[x]["total20"])):
        toys[t]["rank"] = i + 1
    comp = statistics.mean(toys[t]["total20"] for t in NAMES)
    return {"toys": toys, "composite20": round(comp, 3), "composite": round(comp / 20, 4), "distinct": trio.distinct(by_toy), "scenes": len(scenes)}


def guard_failures(agg: dict) -> dict:
    return trio.guard_failures(agg)
