"""Story mode in one picture (docs/story-mode.md) -> docs/img/story-mode.png

  python tools/plot_story.py

The sentences and their sounds are the Billy Goats Gruff lines of tools/story_lines.py (what the live check expects).
"""
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from story_lines import STORIES  # noqa: E402

OUT = HERE.parent / "docs" / "img" / "story-mode.png"
SURFACE, INK, MUTED, RULE = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
CHIP, CHIP_EDGE, DOT = "#fdeee6", "#f3c9b5", "#eb6834"
NAMES = {"goat": "goat bleats", "dino_roar": "troll roars", "hooves": "hooves", "door_creak": "creak", "splash": "splash"}
PICK = (0, 2, 4, 5, 7, 8)          # six of the ten sentences


def short(text, n=66):
    return text if len(text) <= n else text[:n].rsplit(" ", 1)[0] + " ..."


def main():
    rows = [STORIES["billy_goats"][i] for i in PICK]
    fig = plt.figure(figsize=(9.6, 4.9), dpi=160, facecolor=SURFACE)
    ax = fig.add_axes((0, 0, 1, 1))
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.axis("off")
    ax.text(1.5, 95, "Story mode: the child reads, the toys add the sounds", fontsize=13, fontweight="bold", color=INK, va="center")
    ax.text(1.5, 89, "One recorded sound after each sentence, about 0.7 s behind the reader. No toy talks over the story.",
            fontsize=9.5, color=MUTED, va="center")
    ax.text(1.5, 80.5, "THE CHILD READS", fontsize=8.5, color=MUTED, va="center")
    ax.text(58, 80.5, "THE TOYS PLAY", fontsize=8.5, color=MUTED, va="center")
    y, step = 72.5, 11.2
    for text, _pause, sounds in rows:
        ax.plot([1.5, 98.5], [y + step / 2, y + step / 2], color=RULE, lw=1)
        ax.text(1.5, y, "“" + short(text) + "”", fontsize=10, color=INK, va="center")
        x = 58
        for s in sounds:
            label = NAMES.get(s, s)
            w = 4.4 + 0.78 * len(label)
            ax.add_patch(FancyBboxPatch((x, y - 3.1), w, 6.2, boxstyle="round,pad=0,rounding_size=3.1", fc=CHIP, ec=CHIP_EDGE, lw=1))
            ax.plot([x + 1.9], [y], marker="o", ms=5, color=DOT)
            ax.text(x + 3.4, y, label, fontsize=9.5, color=INK, va="center")
            x += w + 1.2
        y -= step
    ax.plot([1.5, 98.5], [y + step / 2, y + step / 2], color=RULE, lw=1)
    ax.text(1.5, 4.5, "Billy Goats Gruff, one of six stories with a word table. Read aloud to the real toys: 46 of 49 expected sounds played.",
            fontsize=9.5, color=MUTED, va="center")
    fig.savefig(OUT, facecolor=SURFACE)
    print(OUT)


if __name__ == "__main__":
    main()
