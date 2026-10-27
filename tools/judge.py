#!/usr/bin/env python3
"""Subjective judge for a virtual_atoms.py run: scores a transcript + timing summary against a rubric.

  python tools/judge.py runs/x.jsonl                 # needs runs/x.jsonl.transcript.json (run with --transcribe)
  python tools/judge.py runs/x.jsonl --prompt-only   # print the judge prompt (paste into any model)
  python tools/judge.py --calibrate labels.json      # agreement of judge scores with human ratings

Uses the Anthropic API when ANTHROPIC_API_KEY is set (model: JUDGE_MODEL, default claude-sonnet-5-5); otherwise it
only prints the prompt. The judge sees text and timings, never audio.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from score_run import score  # noqa: E402

RUBRIC = ["coherence", "on_topic", "distinct_personas", "no_repetition", "turn_taking", "interruption_recovery"]
PERSONAS = ("Dyno: curious, bouncy, asks short questions. Sage: calm, explains simply. "
            "Penny: whimsical, silly, accurate with school facts.")


def build_prompt(transcript, metrics):
    lines = "\n".join(f"[{r['t']:6.1f}s] {r['who']}: {r['text'] or '(unintelligible)'}" for r in transcript)
    m = {k: metrics[k] for k in ("first_audio_s", "first_real_reply_s", "overlaps", "talk_over", "dead_air_gaps", "talk_share")}
    return (f"You are judging a conversation between a child (human) and talking toys. Personas: {PERSONAS}\n\n"
            f"Transcript (speaker, text):\n{lines}\n\nTiming summary: {json.dumps(m)}\n\n"
            f"Score each criterion 1-5 (5 best): {', '.join(RUBRIC)}. Turn-taking uses the timing summary "
            f"(long gaps, overlaps and talking over the child are bad). Reply with JSON only: "
            f'{{"scores": {{...}}, "notes": "<one sentence>"}}')


def ask(prompt):
    import anthropic
    r = anthropic.Anthropic().messages.create(model=os.environ.get("JUDGE_MODEL", "claude-sonnet-5-5"),
                                              max_tokens=400, messages=[{"role": "user", "content": prompt}])
    text = r.content[0].text
    return json.loads(text[text.index("{"): text.rindex("}") + 1])


def agreement(judged, human, tol=1):
    """Share of (run, criterion) pairs where judge and human differ by <= tol points."""
    pairs = [(judged[r][c], human[r][c]) for r in human if r in judged for c in RUBRIC if c in human[r] and c in judged[r]]
    if not pairs:
        return {"pairs": 0}
    return {"pairs": len(pairs), "within_tol": round(sum(abs(a - b) <= tol for a, b in pairs) / len(pairs), 3),
            "mean_abs_err": round(sum(abs(a - b) for a, b in pairs) / len(pairs), 2)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run", nargs="?")
    ap.add_argument("--prompt-only", action="store_true")
    ap.add_argument("--calibrate", metavar="LABELS_JSON",
                    help='{"runs/a.jsonl": {"coherence": 4, ...}, ...} human ratings (aim for ~20 runs)')
    a = ap.parse_args()
    if a.calibrate:
        human = json.loads(Path(a.calibrate).read_text())
        judged = {}
        for run in human:
            tr = json.loads(Path(run + ".transcript.json").read_text())
            judged[run] = ask(build_prompt(tr, score(run)))["scores"]
        print(json.dumps(agreement(judged, human), indent=1))
        return
    tr = json.loads(Path(a.run + ".transcript.json").read_text())
    prompt = build_prompt(tr, score(a.run))
    if a.prompt_only or not os.environ.get("ANTHROPIC_API_KEY"):
        print(prompt)
        return
    print(json.dumps(ask(prompt), indent=1))


if __name__ == "__main__":
    main()
