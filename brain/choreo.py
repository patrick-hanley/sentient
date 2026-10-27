"""Brain-planned speaking order: who talks when, decided before the model writes a word."""
from __future__ import annotations

import random

from . import config


def plan_order(online, rng=random, first=None, lines=None):
    """A speaker sequence like [dyno, sage, dyno, penny]: every toy speaks, none twice in a row.

    `first` pins the opening speaker. Everyone gets a turn before anyone repeats.
    """
    online = list(online)
    if not online:
        return []
    if len(online) == 1:
        return online[:1]
    n = lines or rng.randint(len(online), max(len(online), config.MAX_LINES))
    order = [first if first in online else rng.choice(online)]
    unused = [t for t in online if t not in order]
    while len(order) < n:
        pool = unused or online
        pick = rng.choice([t for t in pool if t != order[-1]] or [t for t in online if t != order[-1]])
        order.append(pick)
        if pick in unused:
            unused.remove(pick)
    return order
