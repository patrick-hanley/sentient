"""How the toys talk TO EACH OTHER when nobody is talking (idle banter). A few cumulative levels of plain conversation advice appended to the
idle event. Level 0 = today's behaviour (nothing added). Chosen by tools/grade_toys.py on frozen scenarios; see docs/grades."""
from __future__ import annotations

LIMIT = "Reply with one line per toy listed, each on its own new line starting with that toy's NAME and a colon. Each line is one or two short sentences, at most 16 words in total, and no toy writes another toy's line. Never repeat a line already said."
LEVELS = {
    1: "Stay on that one topic. Each toy picks up a word or idea from the line before it and adds one NEW fact or thought; never repeat something already said.",
    2: "Some lines are only a short question to the next toy, by name, about the topic (under 8 words); every other line is one plain statement, never a statement plus a question.",
    3: "A statement line may point out one thing to notice about the topic or about another toy (for example 'Look at...'), still in one sentence.",
}


def block(level: int) -> str:
    return " ".join([LIMIT] + [LEVELS[i] for i in sorted(LEVELS) if i <= level]) if level else ""
