"""Self-improvement loop: after each session, nudge the TOYS (never the child, never the spoken scripts) toward the rubric.

Design (docs/metrics.md has the reasoning):
  * A handful of bounded knobs, each an integer level with a hard min/max. Level 0/neutral is today's behaviour, so with
    no history the [COACHING] block is empty and the prompt is exactly what it was before.
  * One change at a time, at most `MAX_PER_DAY` per rolling day, and a new change only after the previous one has been
    judged. Each change is judged on the next `EVAL_N` scored sessions against the average just before it; if the
    normalised total fell by more than `ROLLBACK_MARGIN` it is reverted automatically and that knob is frozen for a while.
  * Everything is logged as numbers (what, from, to, which category, scores) - never what anyone said.
  * Anything that would rewrite a spoken line or the base system prompt only ever becomes a REVIEW proposal for a human.
State is a plain dict (JSON, stored encrypted per child by brain/progress.py), so every function here is pure and testable.
"""
from __future__ import annotations

import copy
import statistics
import time
import uuid

from .metrics import CATEGORIES, LABELS

EVAL_N = 2                 # sessions that judge a change
ROLLBACK_MARGIN = 0.08     # normalised total must fall by more than this (~1.6 of 20) to undo a change
FREEZE_SESSIONS = 5        # sessions a rolled-back knob stays put
UNDO_FREEZE_SESSIONS = 3
MAX_PER_DAY = 2
MAX_LOG = 60
TARGET_SCORE = 3           # "proficient": below this a category is something to work on
WEAK_STREAK = 3            # sessions a category stays <2 with its knobs exhausted before a human review is proposed
PATIENCE_STEP = 0.35       # each patience level lengthens the toys' idle wait by this fraction of the base

KNOBS = {   # name: (min, max, default, label)
    "patience": (0, 3, 0, "How long the toys wait before filling a silence"),
    "style":    (0, 2, 1, "Kind of questions (0 easy either/or, 1 mixed, 2 open)"),
    "length":   (0, 3, 0, "How short each toy line is"),
    "pace":     (0, 2, 0, "Simpler, slower-feeling sentences"),
    "followup": (0, 3, 0, "How much the toys stay on the child's topic"),
    "invite":   (0, 3, 0, "How often a toy pauses and invites the child to tell or ask"),
    "feature":  (0, 2, 0, "How often a toy points out something to notice"),
}
# weak category -> ordered (knob, direction) options; the first usable one is tried
PLAN = {
    "latency":     [("patience", +1), ("length", +1), ("pace", +1)],
    "turn_taking": [("followup", +1), ("style", +1)],
    "initiation":  [("invite", +1)],
    "maintenance": [("style", "toward")],       # easier questions while answers are minimal, open ones once they are not
    "joint":       [("feature", +1)],
}
PRIORITY = ("latency", "maintenance", "turn_taking", "initiation", "joint")   # tie-break among equally weak categories

WORDS = {0: "", 1: 14, 2: 10, 3: 7}
SENTENCES = {
    ("style", 0): "Ask easy either/or or yes/no questions the child can answer in a word or two.",
    ("style", 2): "Prefer open questions that invite a whole sentence (what, why, how).",
    ("pace", 1): "Use short, simple sentences with natural pauses.",
    ("pace", 2): "Use very short sentences, one idea per line.",
    ("followup", 1): "When the child answers, build on what they just said before changing the topic.",
    ("followup", 2): "Stay on the child's topic for several turns: react to their words and ask one follow-up about it.",
    ("followup", 3): "Stay on the child's topic as long as they are interested; always ask a follow-up about the detail they gave.",
    ("invite", 1): "Now and then end a line by inviting the child to tell or ask you something, then wait.",
    ("invite", 2): "Often end a line by inviting the child to tell or ask you something, then wait.",
    ("invite", 3): "End most turns with a pause and an invitation for the child to tell or ask you something.",
    ("feature", 1): "Once in a while point out one thing about a toy (a feature or what it is doing) and ask what they notice.",
    ("feature", 2): "Often point out one thing about a toy (a feature or what it is doing) and ask what they notice.",
}
REVIEW_TEXT = {   # canned, generic proposals: they never contain anything a child said
    "latency": ("scripted_lines", "Several slow answers even with the toys waiting longer: a human could review the openers and greetings for ones that are hard to answer quickly."),
    "turn_taking": ("system_prompt", "Chats stay short even when the toys follow the child's topic: a human could review the base prompt's rule about changing topics."),
    "initiation": ("scripted_lines", "The child rarely starts talk even with frequent invitations: a human could review the toys' idle-banter seeds and greeting lines."),
    "maintenance": ("system_prompt", "Answers stay minimal: a human could review the base prompt's rules about question style and line length."),
    "joint": ("scripted_lines", "Few mentions of the toys' features even when pointed out: a human could review the toys' descriptions and sound/feature lines."),
}


def new_state() -> dict:
    return {"v": 1, "enabled": True, "knobs": {k: v[2] for k, v in KNOBS.items()}, "log": [], "pending": None, "frozen": {},
            "review": [], "seen": 0, "history": [], "weak": {}, "changes": []}


def knob_levels(state) -> dict:
    return dict(state["knobs"]) if state.get("enabled", True) else {k: v[2] for k, v in KNOBS.items()}


def block(state_or_knobs, enabled=True) -> str:
    """The short [COACHING] prompt block ('' when everything is at its neutral level or coaching is off)."""
    if isinstance(state_or_knobs, dict) and "knobs" in state_or_knobs:
        enabled, k = state_or_knobs.get("enabled", True), state_or_knobs["knobs"]
    else:
        k = state_or_knobs
    if not enabled:
        return ""
    parts = []
    if WORDS.get(k.get("length", 0)):
        parts.append(f"Keep each line under {WORDS[k['length']]} words.")
    for name in ("style", "pace", "followup", "invite", "feature"):
        s = SENTENCES.get((name, k.get(name, KNOBS[name][2])))
        if s:
            parts.append(s)
    if not parts:
        return ""
    return "[COACHING: gentle style adjustments for this child; never mention them] " + " ".join(parts)


def patience_multiplier(state_or_knobs, transient: int = 0, enabled=True) -> float:
    """How much longer than the base the toys wait before filling a silence (1.0 = unchanged). `transient` is the
    in-RAM, not persisted, extra level from a run of unanswered cues in the current session."""
    if isinstance(state_or_knobs, dict) and "knobs" in state_or_knobs:
        enabled, k = state_or_knobs.get("enabled", True), state_or_knobs["knobs"]
    else:
        k = state_or_knobs
    if not enabled:
        return 1.0
    return 1.0 + PATIENCE_STEP * min(KNOBS["patience"][1], k.get("patience", 0) + max(0, transient))


def transient_level(consec_unanswered: int) -> int:
    """'Lightly after each interaction': after 3 unanswered cues in a row the toys wait one level longer, after 5 two."""
    return 0 if consec_unanswered < 3 else 1 if consec_unanswered < 5 else 2


def norm(summary) -> float:
    return summary["total"] / summary["of"] if summary.get("of") else 0.0


def _log(state, **entry):
    entry.update(id=uuid.uuid4().hex[:8], t=int(time.time()))
    state["log"].append(entry)
    del state["log"][:-MAX_LOG]
    return entry


def _propose(state, category, evidence):
    kind, text = REVIEW_TEXT[category]
    if any(r["kind"] == kind and r["category"] == category and r["state"] == "pending" for r in state["review"]):
        return None
    item = {"id": uuid.uuid4().hex[:8], "kind": kind, "category": category, "text": text, "evidence": evidence, "state": "pending", "t": int(time.time())}
    state["review"].append(item)
    del state["review"][:-20]
    return item


def _pick(state, cat, score):
    """The first usable (knob, new level) for a weak category, or None when every option is at its bound or frozen."""
    for knob, how in PLAN[cat]:
        if state["frozen"].get(knob, 0) > 0:
            continue
        lo, hi, _default, _ = KNOBS[knob]
        cur = state["knobs"][knob]
        if how == "toward":
            want = 0 if score <= 1 else 1
            new = cur + (1 if want > cur else -1 if want < cur else 0)
        else:
            new = cur + how
        new = max(lo, min(hi, new))
        if new != cur:
            return knob, new
    return None


def after_session(state: dict, summary: dict, now: float | None = None) -> list[dict]:
    """Update `state` in place after one scored session; return the log entries made. The one entry point of the loop."""
    now = time.time() if now is None else now
    out = []
    if not summary.get("scored", True):
        return out
    state["seen"] += 1
    n = norm(summary)
    state["history"] = (state.get("history", []) + [round(n, 3)])[-12:]
    for k in list(state["frozen"]):                        # frozen knobs thaw one session at a time
        state["frozen"][k] -= 1
        if state["frozen"][k] <= 0:
            del state["frozen"][k]
    for c in CATEGORIES:
        weak_now = summary["scores"].get(c) is not None and summary["scores"][c] < 2
        state["weak"][c] = state["weak"].get(c, 0) + 1 if weak_now else 0
    if not state.get("enabled", True):
        return out          # off means frozen: no new changes and no automatic rollbacks either
    pending = state.get("pending")
    if pending:
        pending["after"].append(round(n, 3))
        if len(pending["after"]) >= EVAL_N:
            mean_after = statistics.mean(pending["after"])
            if mean_after < pending["baseline"] - ROLLBACK_MARGIN:
                if state["knobs"][pending["knob"]] == pending["to"]:
                    state["knobs"][pending["knob"]] = pending["from"]
                state["frozen"][pending["knob"]] = FREEZE_SESSIONS
                out.append(_log(state, kind="rollback", knob=pending["knob"], frm=pending["to"], to=pending["from"],
                                baseline=pending["baseline"], after=round(mean_after, 3), why=pending["why"]))
                if sum(1 for e in state["log"] if e["kind"] == "rollback" and e["why"].get("weak") == pending["why"].get("weak")) >= 2:
                    _propose(state, pending["why"]["weak"], {"rollbacks": 2})
            else:
                out.append(_log(state, kind="kept", knob=pending["knob"], to=pending["to"], baseline=pending["baseline"], after=round(mean_after, 3)))
            state["pending"] = None
        return out      # a change under evaluation: no second change (clean attribution)
    sc = summary["scores"]
    recent = [e for e in state["log"] if e["kind"] == "change" and now - e["t"] < 86400]
    if len(recent) >= MAX_PER_DAY:
        return out
    weak = sorted((c for c in CATEGORIES if sc.get(c) is not None and sc[c] < TARGET_SCORE), key=lambda c: (sc[c], PRIORITY.index(c)))
    base = statistics.mean((state["history"][-3:]))
    for cat in weak:
        pick = _pick(state, cat, sc[cat])
        if pick:
            knob, new = pick
            old = state["knobs"][knob]
            state["knobs"][knob] = new
            why = {"weak": cat, "score": sc[cat], "total": summary["total"], "of": summary["of"],
                   "L_med": summary["metrics"].get("L_med"), "C_R": summary["metrics"].get("C_R")}
            state["pending"] = {"knob": knob, "from": old, "to": new, "baseline": round(base, 3), "after": [], "why": why}
            out.append(_log(state, kind="change", knob=knob, frm=old, to=new, why=why))
            return out
        if state["weak"].get(cat, 0) >= WEAK_STREAK:       # nothing left to adjust: a human decides about lines/prompt
            _propose(state, cat, {"score": sc[cat], "sessions": state["weak"][cat]})
    if not weak and sc.get("maintenance", 0) >= TARGET_SCORE and state["knobs"]["style"] < 2 and not state["frozen"].get("style"):
        old = state["knobs"]["style"]                      # stretch: answers are good, so ask more open questions
        state["knobs"]["style"] = old + 1
        why = {"weak": None, "stretch": "maintenance", "total": summary["total"], "of": summary["of"]}
        state["pending"] = {"knob": "style", "from": old, "to": old + 1, "baseline": round(base, 3), "after": [], "why": why}
        out.append(_log(state, kind="change", knob="style", frm=old, to=old + 1, why=why))
    return out


# ---------------------------------------------------------------- parent controls
def set_enabled(state: dict, on: bool) -> None:
    state["enabled"] = bool(on)
    _log(state, kind="switch", to=int(bool(on)))


def undo(state: dict, change_id: str) -> bool:
    """Reverse one logged change (if that knob is still where the change left it)."""
    for e in state["log"]:
        if e["id"] == change_id and e["kind"] == "change" and state["knobs"].get(e["knob"]) == e["to"]:
            state["knobs"][e["knob"]] = e["frm"]
            state["frozen"][e["knob"]] = UNDO_FREEZE_SESSIONS
            if state.get("pending") and state["pending"]["knob"] == e["knob"]:
                state["pending"] = None
            _log(state, kind="undo", knob=e["knob"], frm=e["to"], to=e["frm"], of=change_id)
            return True
    return False


def reset(state: dict) -> None:
    state["knobs"] = {k: v[2] for k, v in KNOBS.items()}
    state["pending"], state["frozen"] = None, {}
    _log(state, kind="reset")


def resolve_review(state: dict, rid: str, decision: str) -> bool:
    """A human's answer to a proposal. 'approved' only records the decision: nothing is rewritten automatically."""
    for r in state["review"]:
        if r["id"] == rid and r["state"] == "pending" and decision in ("approved", "dismissed"):
            r["state"] = decision
            return True
    return False


def describe(state: dict) -> dict:
    """The parent-visible view (numbers, labels and short canned reasons)."""
    return {"enabled": state.get("enabled", True), "pending": copy.deepcopy(state.get("pending")), "review": copy.deepcopy(state["review"]),
            "knobs": [{"name": k, "label": KNOBS[k][3], "level": state["knobs"][k], "min": KNOBS[k][0], "max": KNOBS[k][1],
                       "default": KNOBS[k][2]} for k in KNOBS],
            "log": [dict(e, category=LABELS.get((e.get("why") or {}).get("weak") or "", "")) for e in reversed(state["log"])][:30]}
