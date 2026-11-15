#!/usr/bin/env python3
"""Append-only dialog ledger for the toy-to-toy grade. Synthetic scenarios and toy-generated lines only (no child or parent data).

  python tools/grade_ledger.py add RUN.json --label L [--baseline-label B] [--commit HASH] [--note TEXT]   # appends one record to docs/grades/ledger.jsonl
  python tools/grade_ledger.py render                                                                   # rebuilds docs/grades/ledger/<label>.md and the table in ledger.md

A record = the run's numbers, its safety probes (synthetic child line + the toy's reply when saved), and for EVERY scene the toys' lines in order with per-line
points and the scene composite. The rendered page puts the same scenario from the baseline run next to it (the conversations differ: Gemma is sampled).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tools"))
import grade_toys as G  # noqa: E402
import textgrade as T  # noqa: E402

GR = ROOT / "docs" / "grades"
JSONL, PAGES, SUMMARY = GR / "ledger.jsonl", GR / "ledger", GR / "ledger.md"


def records() -> list[dict]:
    return [json.loads(l) for l in JSONL.read_text().splitlines() if l.strip()] if JSONL.exists() else []


def build(run: dict, label: str, baseline: dict | None, commit: str, note: str) -> dict:
    agg = G.evaluate(run)
    scenes = []
    for s in run["scenes"]:
        if s["failed"]:
            continue
        lines = G.merge_chunks(s["lines"])
        one = T.aggregate([{"topic": s["topic"], "lines": lines}])
        scenes.append({"id": s["id"], "kind": s["kind"], "lead": s["lead"], "topic": s["topic"], "composite20": one["composite20"], "lines": T.line_scores(lines, s["topic"])})
    decision = "reference"
    if baseline:
        keep, why = G.decide(baseline["agg"], agg)
        decision = why
    brief = {k: agg.get(k) for k in ("composite20", "distinct", "probe_pass", "guards", "words_per_scene", "failed_scenes", "round_points", "holds")}
    brief["toys"] = {t: {"total20": a["total20"], "scores": a["scores"], "lines": a["lines"]} for t, a in agg["toys"].items()}
    return {"label": label, "set": run["set"], "toytalk": run.get("toytalk", 0), "commit": commit, "note": note, "baseline": baseline["label"] if baseline else None,
            "decision": decision, "agg": brief, "probes": [{"toy": p["toy"], "ok": p["ok"], **({"reply": p["text"]} if "text" in p else {}), **({"child": p["child"]} if "child" in p else {})} for p in run["probes"]], "scenes": scenes}


def cmd_add(a):
    recs = records()
    if any(r["label"] == a.label for r in recs):
        sys.exit(f"label {a.label} already in the ledger (append-only)")
    base = next((r for r in recs if r["label"] == a.baseline_label), None) if a.baseline_label else None
    if a.baseline_label and not base:
        sys.exit(f"baseline label {a.baseline_label} not found")
    run = json.loads(Path(a.run).read_text())
    rec = build(run, a.label, base and {"label": base["label"], "agg": base["agg"]}, a.commit or subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=ROOT).stdout.strip(), a.note)
    with JSONL.open("a") as f:
        f.write(json.dumps(rec) + "\n")
    print(rec["label"], rec["agg"]["composite20"], rec["decision"])
    progress(rec, recs)


def progress(rec: dict, recs: list[dict]):
    """ONE line per run in /tmp/grade-progress.log: time, label, set, composite /20, ratio vs the baseline of the same set, guards, kept/reverted."""
    import time
    ref = next((r for r in recs if r["label"] == f"baseline-{rec['set']}"), None)
    ratio = f"{rec['agg']['composite20'] / ref['agg']['composite20']:.2f}x" if ref else "-"
    verdict = "reference" if rec["decision"] == "reference" else ("KEPT" if rec["decision"].startswith("keep") else "REVERTED")
    g = rec["agg"]["guards"]
    with open("/tmp/grade-progress.log", "a") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {rec['label']} {rec['set']} {rec['agg']['composite20']:.2f}/20 {ratio} guards[long {g['long_lines']} run-on {g['run_on']} repeat {g['repeats']} scary {g['scary']} pressure {g['pressure']}] probes {rec['agg']['probe_pass']} {verdict} ({rec['decision']})\n")


def md_line(l: dict) -> str:
    txt = l["text"].replace("|", "\\|")
    return f"**{l['toy'][0].upper()}** {txt} `{l['points']:.1f}`"


def render_page(rec: dict, base: dict | None) -> str:
    a = rec["agg"]
    out = [f"# {rec['label']} ({rec['set']} set, toy-talk level {rec['toytalk']}, code {rec['commit']})", "",
           f"Composite **{a['composite20']:.2f}/20**; probes {a['probe_pass']}; words/scene {a['words_per_scene']}; guards {a['guards']}; distinct {a['distinct']}; line points by round {hold_of(rec)[0]} (last/first {hold_of(rec)[1]}).  ",
           f"Decision vs {rec['baseline'] or '-'}: **{rec['decision']}**. {rec['note']}", "",
           "Synthetic scenarios, toy-generated lines. Line points `0-4` = share of the applicable checks passed (on topic, follow-up, not a repeat, 1-2 sentences). "
           "Left = this run, right = the baseline for the SAME scenario id (different sample of Gemma, so different words).", ""]
    out += ["## Scores by category (mean of the three toys, 0-4)", "", "| category | this run | " + (f"{base['label']} | change |" if base else ""), "|---|---|" + ("---|---|" if base else "")]
    for c in T.CATS:
        mine = sum(a["toys"][t]["scores"][c] for t in a["toys"]) / 3
        if base:
            theirs = sum(base["agg"]["toys"][t]["scores"][c] for t in base["agg"]["toys"]) / 3
            out.append(f"| {T.LABELS[c]} | {mine:.2f} | {theirs:.2f} | {mine - theirs:+.2f} |")
        else:
            out.append(f"| {T.LABELS[c]} | {mine:.2f} |")
    out.append("")
    if base:
        bm = {s["id"]: s for s in base["scenes"]}
        moves = sorted(((s["composite20"] - bm[s["id"]]["composite20"], s["id"]) for s in rec["scenes"] if s["id"] in bm))
        if moves:
            out += ["## Biggest scene moves vs the baseline (scene composite /20)", ""] + [f"- {i}: {d:+.1f}" for d, i in moves[:3] + moves[-3:]] + [""]
    if rec["probes"]:
        out += ["## Safety probes (synthetic child lines)", ""] + [f"- {p['toy']} {'pass' if p['ok'] else 'FAIL'}" + (f" (probe: \"{p['child']}\")" if "child" in p else "") + (f": {p['reply']}" if "reply" in p else "") for p in rec["probes"]] + [""]
    bs = {s["id"]: s for s in base["scenes"]} if base else {}
    for s in rec["scenes"]:
        b = bs.get(s["id"])
        out += [f"## {s['id']} — {s['kind']}, topic: {s['topic'] or '(free)'}", ""]
        if b:
            out += [f"| turn | this run (scene {s['composite20']:.1f}/20) | baseline (scene {b['composite20']:.1f}/20) |", "|---|---|---|"]
            n = max(len(s["lines"]), len(b["lines"]))
            for i in range(n):
                x = s["lines"][i] if i < len(s["lines"]) else None
                y = b["lines"][i] if i < len(b["lines"]) else None
                out.append(f"| {x['turn'] if x else y['turn']} | {md_line(x) if x else ''} | {md_line(y) if y else ''} |")
        else:
            out += [f"Scene composite {s['composite20']:.1f}/20", ""] + [f"{l['turn']}. {md_line(l)}  " for l in s["lines"]]
        out.append("")
    return "\n".join(out)


def hold_of(rec: dict):
    """(round points, last/first) for a record; derived from its stored per-line points when the record predates the field."""
    a = rec["agg"]
    if a.get("holds") is not None:
        return a.get("round_points"), a["holds"]
    per = {}
    for sc in rec.get("scenes", []):
        for l in sc["lines"]:
            per.setdefault(int(l.get("turn", 0)), []).append(l["points"])
    rp = {k: round(sum(v) / len(v), 2) for k, v in sorted(per.items())}
    return rp, (round(rp[max(rp)] / rp[min(rp)], 3) if len(rp) >= 2 and rp[min(rp)] else None)


def cmd_render(_):
    recs = records()
    by = {r["label"]: r for r in recs}
    PAGES.mkdir(exist_ok=True)
    rows = ["| run | set | level | composite | probes | words/scene | round 3 / round 1 | guards (long/run-on/repeat) | decision | dialog |", "|---|---|---|---|---|---|---|---|---|---|"]
    for r in recs:
        (PAGES / f"{r['label']}.md").write_text(render_page(r, by.get(r["baseline"])))
        g, a = r["agg"]["guards"], r["agg"]
        rows.append(f"| {r['label']} | {r['set']} | {r['toytalk']} | {a['composite20']:.2f} | {a['probe_pass']} | {a['words_per_scene']} | {hold_of(r)[1] if hold_of(r)[1] is not None else '-'} | {g['long_lines']}/{g['run_on']}/{g['repeats']} | {r['decision']} | [dialog](ledger/{r['label']}.md) |")
    text = SUMMARY.read_text()
    a0, a1 = text.index("<!-- TABLE -->"), text.index("<!-- /TABLE -->")
    SUMMARY.write_text(text[:a0] + "<!-- TABLE -->\n" + "\n".join(rows) + "\n" + text[a1:])
    print(f"rendered {len(recs)} runs")


def main():
    ap = argparse.ArgumentParser(); sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("add"); p.add_argument("run"); p.add_argument("--label", required=True); p.add_argument("--baseline-label"); p.add_argument("--commit", default=""); p.add_argument("--note", default="")
    sub.add_parser("render")
    a = ap.parse_args()
    {"add": cmd_add, "render": cmd_render}[a.cmd](a)


if __name__ == "__main__":
    main()
