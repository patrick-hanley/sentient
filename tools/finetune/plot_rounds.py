"""Chart of round 7 against round 8 on the seven test sets (plan, 3j) -> docs/img/finetune-round8.png

  python tools/finetune/plot_rounds.py
"""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

OUT = Path(__file__).resolve().parents[2] / "docs" / "img" / "finetune-round8.png"
# share of toy replies that break no rule, 3 samples per turn (gemma-kids-social-model-plan.md, 3j)
SETS = [("Lines the toys got wrong live (48 scenes)", 85.4, 88.3), ("New round 8 scenes (15)", 86.9, 88.9),
        ("Round 7 held-out (24)", 84.9, 89.8), ("Attachment: love, forever, secrets (30)", 90.1, 94.0),
        ("Warm first (24)", 89.8, 94.9), ("Earlier scenes (40)", 92.8, 94.1), ("Cameras and I spy (24)", 93.6, 94.5)]
SURFACE, INK, MUTED, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
R7, R8 = "#2a78d6", "#eb6834"


def main():
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11})
    fig, ax = plt.subplots(figsize=(9.6, 4.6), dpi=160, facecolor=SURFACE)
    ax.set_facecolor(SURFACE)
    for i, (name, a, b) in enumerate(SETS):
        y = len(SETS) - 1 - i
        ax.plot([a, b], [y, y], color="#b9b8b2", lw=2, zorder=1, solid_capstyle="round")
        ax.scatter([a], [y], s=90, color=R7, zorder=2, edgecolors=SURFACE, linewidths=2, label="Round 7" if i == 0 else None)
        ax.scatter([b], [y], s=90, color=R8, zorder=3, edgecolors=SURFACE, linewidths=2, label="Round 8" if i == 0 else None)
        ax.annotate(f"{b:.1f}%", (b, y), xytext=(9, 0), textcoords="offset points", va="center", color=INK, fontsize=10.5)
        ax.annotate(f"{a:.1f}", (a, y), xytext=(-9, 0), textcoords="offset points", va="center", ha="right", color=MUTED, fontsize=9.5)
    ax.set_yticks(range(len(SETS)))
    ax.set_yticklabels([s[0] for s in reversed(SETS)], color=INK)
    ax.set_xlim(82, 98)
    ax.set_ylim(-0.6, len(SETS) - 0.4)
    ax.set_xticks(range(84, 98, 4))
    ax.set_xticklabels([f"{v}%" for v in range(84, 98, 4)], color=MUTED)
    ax.xaxis.grid(True, color=GRID, lw=1)
    ax.set_axisbelow(True)
    ax.tick_params(length=0)
    for side in ax.spines.values():
        side.set_visible(False)
    ax.set_xlabel("Toy replies that break no rule", color=MUTED)
    fig.suptitle("Round 8 beats round 7 on every test set", x=0.012, y=0.975, ha="left", fontsize=14, color=INK, fontweight="bold")
    fig.text(0.012, 0.895, "Fine-tuned Gemma 4 E2B on the Jetson, same scenes for both models, 3 samples per turn", ha="left",
             color=MUTED, fontsize=10)
    ax.legend(loc="lower right", bbox_to_anchor=(1.0, 1.0), frameon=False, ncols=2, handletextpad=0.2, columnspacing=1.2, labelcolor=INK)
    fig.subplots_adjust(left=0.36, right=0.95, top=0.84, bottom=0.14)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT, facecolor=SURFACE)
    print(OUT)


if __name__ == "__main__":
    main()
