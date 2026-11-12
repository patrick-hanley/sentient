#!/usr/bin/env python3
"""Objective, model-free scoring of a virtual_atoms.py run (or several, for A/B).

  python tools/score_run.py runs/a.jsonl [runs/b.jsonl ...] [--filler-max 1.5] [--json]

Per human utterance: time from the end of speech to the first agent audio (filler or reply) and to the first real
reply (a /play longer than --filler-max seconds). Also: overlap (two toys playing at once), talk-over (an agent
starts while a human is still speaking), dead air between consecutive agent clips, and talk-time share per toy.
Compares against the brain's own milestones when <run>.turns.json is next to the event log.

--rubric also feeds the same timings to brain.metrics (the conversation-rubric tracker): turn-taking ratio, response latency,
reciprocity loop, initiation ratio and the timing-only scores. A virtual run has no words, so every real reply (longer than
--filler-max) is ASSUMED to end with a question/invitation (a cue), and the text-based categories read n/a.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

DEAD_AIR_S = 3.0


def load(path):
    return [json.loads(l) for l in open(path) if l.strip()]


def pct(v, p):
    v = sorted(v)
    return round(v[min(len(v) - 1, int(len(v) * p))], 3) if v else None


def score(path, filler_max=1.5):
    ev = load(path)
    plays, speech = [], []
    open_play, open_sp = {}, {}
    for e in ev:
        if e["ev"] == "play_start":
            open_play[e["toy"]] = e
        elif e["ev"] == "play_end" and e["toy"] in open_play:
            s = open_play.pop(e["toy"])
            plays.append({"toy": e["toy"], "start": s["t"], "end": e["t"], "dur": s["dur"]})
        elif e["ev"] == "speech_start" and e["label"] != "silence":
            open_sp[(e["toy"], e["label"])] = e
        elif e["ev"] == "speech_end" and e["label"] != "silence" and (e["toy"], e["label"]) in open_sp:
            s = open_sp.pop((e["toy"], e["label"]))
            speech.append({"toy": e["toy"], "start": s["t"], "end": e["t"], "chain": e["label"].startswith("chain")})
    plays.sort(key=lambda p: p["start"])
    humans = sorted([s for s in speech if not s["chain"]], key=lambda s: s["end"])
    # the same child voice reaches every mic: group human utterances that start within 1 s of each other
    groups = []
    for h in humans:
        if groups and h["start"] - groups[-1]["start"] < 1.0:
            groups[-1]["end"] = max(groups[-1]["end"], h["end"])
        else:
            groups.append(dict(h))
    first_any, first_real, unanswered = [], [], 0
    for i, g in enumerate(groups):
        horizon = groups[i + 1]["start"] if i + 1 < len(groups) else float("inf")
        mine = [p for p in plays if g["end"] <= p["start"] < horizon]
        if not mine:
            unanswered += 1
            continue
        first_any.append(mine[0]["start"] - g["end"])
        real = [p for p in mine if p["dur"] > filler_max]
        if real:
            first_real.append(real[0]["start"] - g["end"])
    overlap = sum(1 for i, a in enumerate(plays) for b in plays[i + 1:]
                  if a["toy"] != b["toy"] and b["start"] < a["end"] - .05)
    talk_over = sum(1 for p in plays for s in speech if not s["chain"] and s["start"] < p["start"] < s["end"] - .05)
    gaps = [b["start"] - a["end"] for a, b in zip(plays, plays[1:]) if b["start"] - a["end"] < 10]
    dead = [g for g in gaps if g > DEAD_AIR_S]
    total = sum(p["dur"] for p in plays) or 1
    share = {}
    for p in plays:
        share[p["toy"]] = share.get(p["toy"], 0) + p["dur"] / total
    out = {
        "run": str(path), "human_utterances": len(groups), "unanswered": unanswered,
        "first_audio_s": {"n": len(first_any), "p50": pct(first_any, .5), "p95": pct(first_any, .95)},
        "first_real_reply_s": {"n": len(first_real), "p50": pct(first_real, .5), "p95": pct(first_real, .95)},
        "overlaps": overlap, "talk_over": talk_over, "half_duplex_violations": overlap + talk_over,
        "dead_air_gaps": len(dead), "dead_air_rate": round(len(dead) / max(1, len(gaps)), 3),
        "talk_share": {k: round(v, 2) for k, v in sorted(share.items())},
        "chain_hops": sum(1 for e in ev if e["ev"] == "chain"),
    }
    brain = Path(str(path) + ".turns.json")
    if brain.exists():
        summ = json.loads(brain.read_text()).get("summary", {})
        out["brain_ms"] = {k: summ[k] for k in ("utterance_ready_ms", "first_model_text_ms", "first_pcm_ready_ms",
                                                "first_audio_post_ms", "llm_ms", "tts_ms") if k in summ}
    return out


def rubric(path, filler_max=1.5):
    """Timing-only rubric metrics for a virtual-Atoms run (see the module docstring for the assumption made)."""
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from brain import metrics
    ev = load(path)
    plays, speech, open_play, open_sp = [], [], {}, {}
    for e in ev:
        if e["ev"] == "play_start":
            open_play[e["toy"]] = e
        elif e["ev"] == "play_end" and e["toy"] in open_play:
            st = open_play.pop(e["toy"])
            plays.append({"s": st["t"], "e": e["t"], "dur": st["dur"]})
        elif e["ev"] == "speech_start" and e["label"] != "silence":
            open_sp[(e["toy"], e["label"])] = e
        elif e["ev"] == "speech_end" and e["label"] != "silence" and (e["toy"], e["label"]) in open_sp:
            st = open_sp.pop((e["toy"], e["label"]))
            if not e["label"].startswith("chain"):
                speech.append({"s": st["t"], "e": e["t"]})
    events = [{"k": "child", "s": h["s"], "e": h["e"], "f": None} for h in speech]   # the metrics merge the same voice heard by several mics
    events += [{"k": "audio", "s": p["s"], "e": p["e"]} for p in plays]
    turn = None
    for p in sorted(plays, key=lambda p: p["s"]):
        if p["dur"] <= filler_max:
            continue
        if turn and p["s"] - turn["e"] < metrics.TURN_JOIN_S and not any(turn["e"] <= h["s"] <= p["s"] for h in speech):
            turn["e"] = p["e"]
        else:
            turn = {"k": "toy", "s": p["s"], "e": p["e"], "init": False, "q": True, "invite": False, "open": False}
            events.append(turn)
    return metrics.analyze(events)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rubric", action="store_true", help="also print the conversation-rubric metrics (timing only)")
    ap.add_argument("runs", nargs="+")
    ap.add_argument("--filler-max", type=float, default=1.5)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    res = [score(r, a.filler_max) for r in a.runs]
    if a.rubric:
        for r, path in zip(res, a.runs):
            r["rubric"] = rubric(path, a.filler_max)
    if a.json:
        print(json.dumps(res, indent=1))
        return
    for r in res:
        print(f"\n{r['run']}\n  human utterances {r['human_utterances']} (unanswered {r['unanswered']}), chain hops {r['chain_hops']}")
        for k in ("first_audio_s", "first_real_reply_s"):
            print(f"  {k:20s} n={r[k]['n']} p50={r[k]['p50']} p95={r[k]['p95']}")
        print(f"  overlaps {r['overlaps']}  talk-over {r['talk_over']}  half-duplex violations {r['half_duplex_violations']}"
              f"  dead-air {r['dead_air_gaps']} ({r['dead_air_rate']:.0%})  talk share {r['talk_share']}")
        if "rubric" in r:
            m, sc = r["rubric"]["metrics"], r["rubric"]["scores"]
            print(f"  rubric (timing only): T_R={m['T_R']} I:R={m['IR']} C_R={m['C_R']} latency median={m['L_med']}s  scores={sc}")
        for k, v in r.get("brain_ms", {}).items():
            print(f"  brain {k:22s} p50={v['p50']} p95={v['p95']}")
    if len(res) == 2 and all(r["first_real_reply_s"]["p50"] is not None for r in res):
        d = res[1]["first_real_reply_s"]["p50"] - res[0]["first_real_reply_s"]["p50"]
        print(f"\nB - A first-real-reply p50: {d:+.2f}s")


if __name__ == "__main__":
    main()
