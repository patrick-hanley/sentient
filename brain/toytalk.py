"""How the toys talk TO EACH OTHER when nobody is talking (idle banter). A few cumulative levels of plain conversation advice appended to the
idle event. Level 0 = today's behaviour (nothing added). Chosen by tools/grade_toys.py on frozen scenarios; see docs/grades."""
from __future__ import annotations

LEVELS = {
    1: "Stay on that one topic. Each toy picks up a word or idea from the line before it and adds one new fact or thought.",
    2: "Each line except the last ends by asking the next toy a question about the topic or inviting it by name, so the chat passes around like a game.",
    3: "A toy may point out one thing to notice about the topic or about another toy (for example 'Look at...' or 'Did you notice...').",
}


def block(level: int) -> str:
    return " ".join(LEVELS[i] for i in sorted(LEVELS) if i <= level)
