"""One session as a data-collection log (markdown), generated on demand from a stored numbers-only summary.
Nothing is stored; the layout follows the usual observation-sheet shape (session info, tallies, 0-4 scores, notes)."""
from __future__ import annotations

import time

from .metrics import CATEGORIES, LABELS, TARGETS, qualitative


def _f(v, nd=2, dash="n/a"):
    return dash if v is None else (f"{v:.{nd}f}".rstrip("0").rstrip(".") if isinstance(v, float) else str(v))


def session_markdown(s: dict, child: str | None = None, toys: str = "Dyno, Sage, Penny (plush toys with voices)") -> str:
    c, m, sc = s["counts"], s["metrics"], s["scores"]
    q = qualitative(s)
    when = time.strftime("%Y-%m-%d %H:%M", time.localtime(s.get("start", 0)))
    mins = s["duration_s"] / 60
    knobs = ", ".join(f"{k} {v}" for k, v in (s.get("knobs") or {}).items()) or "defaults"
    rows = [
        "# Speech interaction session log", "",
        "## Session information", "",
        f"- **Date:** {when}", "- **Observer:** automatic (the toys' conversation tracker; transcripts are not kept)",
        f"- **Child:** {child or 'not named'}", f"- **Toys / materials:** {toys}",
        f"- **Session duration:** {mins:.1f} minutes", f"- **Toy coaching settings in force:** {knobs}", "",
        "## Tallies and quantitative data", "",
        "| Measure | Count | Value | Target |", "| --- | --- | --- | --- |",
        f"| Toy cues / prompts (N_T) | {c['N_T']} | | |",
        f"| Child responses (N_R) | {c['N_R']} | | |",
        f"| Child initiations (N_I) | {c['N_I']} | | |",
        f"| Turn-taking ratio T_R = (N_R + N_I) / N_T | | {_f(m['T_R'])} | about {TARGETS['T_R']:g} |",
        f"| Initiation-to-response I:R = N_I / N_R | | {_f(m['IR'])} | about {TARGETS['IR']:g} |",
        f"| Max reciprocity loop C_R (turns of both speakers) | | {m['C_R']} | at least {TARGETS['C_R']} |",
        f"| Response latency, median (n={m['L_n']}) | | {_f(m['L_med'])} s | {TARGETS['L_lo']:g}-{TARGETS['L_hi']:g} s |",
        f"| Response latency, 25th / 75th / 90th percentile | | {_f(m['L_p25'])} / {_f(m['L_p75'])} / {_f(m['L_p90'])} s | |",
        f"| Toy questions with no answer in 10 s | {c['unanswered']} | | |",
        f"| Times the child talked over a toy | {c['barges']} | | |", "",
        "## Scores (0-4)", "", "| Category | Score | Note |", "| --- | --- | --- |"]
    notes = {"latency": f"median {_f(m['L_med'])} s over {m['L_n']} answers", "turn_taking": f"longest loop {m['C_R']} turns",
             "initiation": f"{s['tags']['comments']} comments/questions, {s['tags']['wants']} requests of their own",
             "maintenance": f"{s['tags']['expansions']} answers with extra detail, {s['tags']['echo']} repeats of the toy",
             "joint": f"{s['tags']['refs']} mentions of a toy or feature, {s['tags']['attn']} 'look at this' style"}
    for cat in CATEGORIES:
        rows.append(f"| {LABELS[cat]} | {_f(sc[cat], 0, 'not measurable')} | {notes[cat]} |")
    rows += [f"| **Total** | **{s['total']} / {s['of']}** | sum of the scores that could be measured |", "",
             "## Notes", "",
             "- **Strengths:** " + ("; ".join(q["strengths"]) or "none yet at the proficient level"),
             "- **Targets:** " + ("; ".join(q["targets"]) or "nothing below proficient"),
             "- **Context:** " + ("; ".join(q["factors"]) or "none recorded"), "",
             "_Counts come from timing and simple word features, not from understanding; see docs/metrics.md for what they can miss._", ""]
    return "\n".join(rows)
