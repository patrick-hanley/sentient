"""How the toys talk TO EACH OTHER when nobody is talking (idle banter). A few cumulative levels of plain conversation advice appended to the
idle event. Level 0 = today's behaviour (nothing added). Chosen by tools/grade_toys.py on frozen scenarios; see docs/grades."""
from __future__ import annotations

LIMIT = "Reply with one line per toy listed, each on its own new line starting with that toy's NAME and a colon. Each line is one or two short sentences, at most 16 words in total, and no toy writes another toy's line. Never repeat a line already said."
LEVELS = {
    1: "Stay on that one topic. Each toy picks up a word or idea from the line before it and adds one NEW fact or thought; never repeat something already said.",
    2: "Let the second sentence of most lines (not the last toy's) ask the next toy, by name, a question about the topic.",
    3: "A toy may point out one thing to notice about the topic or about another toy (for example 'Look at...' or 'Did you notice...').",
}


def block(level: int) -> str:
    return " ".join([LIMIT] + [LEVELS[i] for i in sorted(LEVELS) if i <= level]) if level else ""
