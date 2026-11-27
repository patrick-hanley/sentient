"""Two pictures of the cross-toy echo canceller (docs/aec.md) -> docs/img/aec-simulation.png, docs/img/aec-real-toys.png

  python tools/plot_aec.py

1. One run of the simulation rig (tools/aec_sim.py, the real brain/aec.py inside): a toy talks, a child cuts in.
2. The measurements on the real toys (Nov 14, 12 recorded sequences replayed offline; table in docs/aec.md).
"""
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import aec_sim  # noqa: E402

IMG = HERE.parent / "docs" / "img"
SURFACE, INK, MUTED, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
BLUE, ORANGE, SHADE = "#2a78d6", "#eb6834", "#efeee9"


def style(ax):
    ax.set_facecolor(SURFACE)
    for side in ax.spines.values():
        side.set_visible(False)
    ax.tick_params(length=0, colors=MUTED)


def simulation():
    sc = aec_sim.Scenario(seed=3, dur=6.0, line_s=5.0, child_at=2.8, child_s=2.2, child_over_echo=0.0)
    r = aec_sim.run(sc)                          # as live: the talking toy is cut when the child is detected
    t = (r.t_true[:, None] + np.arange(aec_sim.B)[None, :] / 16000.0).ravel()
    mic, res = r.mic.ravel().astype(float), r.res.ravel().astype(float)
    barge = r.barge_t - sc.mic_epoch - sc.clock0 if r.barge_t is not None else None
    top = 1.05 * np.abs(mic).max()
    fig, axes = plt.subplots(2, 1, figsize=(9.6, 5.0), dpi=160, facecolor=SURFACE, sharex=True)
    rows = (("What the listening toy's microphone hears: the talking toy, then the child over it", mic, BLUE),
            ("After the brain subtracts the sound it sent to the talking toy: the child is what is left", res, ORANGE))
    for ax, (title, y, color) in zip(axes, rows):
        style(ax)
        ax.axvspan(sc.child_at, sc.child_at + sc.child_s, color=SHADE, zorder=0)
        ax.plot(t, y, color=color, lw=0.6, zorder=2)
        ax.set_ylim(-top, top)
        ax.set_yticks([])
        ax.set_title(title, loc="left", fontsize=10.5, color=INK, pad=6)
        if barge is not None:
            ax.axvline(barge, color=INK, lw=1.2, zorder=3)
    axes[0].annotate("child speaks", (sc.child_at + sc.child_s / 2, top * 0.86), ha="center", color=MUTED, fontsize=9.5)
    if barge is not None:
        axes[1].annotate(f"the brain tells the toys to stop\n{(barge - sc.child_at) * 1000:.0f} ms after the child's first sound",
                         (barge, -top * 0.8), xytext=(8, 0), textcoords="offset points", color=INK, fontsize=9.5, va="center",
                         bbox=dict(fc=SHADE, ec="none", pad=2))
    axes[1].annotate("first second:\nlearning the room", (0.3, -top * 0.8), ha="center", color=MUTED, fontsize=9)
    axes[1].annotate(f"toy alone: echo down {r.erle_db(1.6, sc.child_at):.0f} dB", (1.25, top * 0.72), color=MUTED, fontsize=9.5)
    axes[1].set_xlabel("seconds", color=MUTED)
    axes[1].set_xlim(0, sc.dur)
    fig.suptitle("A child can interrupt a talking toy, because the other toys' microphones keep listening",
                 x=0.012, y=0.985, ha="left", fontsize=13, color=INK, fontweight="bold")
    fig.text(0.012, 0.915, "Simulation of the real canceller (brain/aec.py): room echo, clock drift, WiFi jitter and 1% packet loss",
             ha="left", color=MUTED, fontsize=9.5)
    fig.subplots_adjust(left=0.02, right=0.985, top=0.83, bottom=0.11, hspace=0.32)
    fig.savefig(IMG / "aec-simulation.png", facecolor=SURFACE)
    print("simulation: barge", barge, "ERLE", round(r.erle_db(1.6, sc.child_at), 1))


def real_toys():
    stages = ["Raw\nmicrophone", "Filter", "Filter +\nsuppressor", "+ stored\necho path"]
    panels = (("Words of the talking toy still heard", [0.71, 0.12, 0.08, 0.10]),
              ("Words of the child heard wrong", [0.65, 0.18, 0.13, 0.13]))
    fig, axes = plt.subplots(1, 2, figsize=(9.6, 3.9), dpi=160, facecolor=SURFACE, sharey=True)
    for ax, (title, vals) in zip(axes, panels):
        style(ax)
        bars = ax.bar(range(4), [v * 100 for v in vals], width=0.56, color=BLUE, zorder=2)
        for b, v in zip(bars, vals):
            ax.annotate(f"{v * 100:.0f}%", (b.get_x() + b.get_width() / 2, v * 100), xytext=(0, 4), textcoords="offset points",
                        ha="center", color=INK, fontsize=10.5)
        ax.set_xticks(range(4))
        ax.set_xticklabels(stages, color=INK, fontsize=9.5)
        ax.set_ylim(0, 82)
        ax.set_yticks([0, 25, 50, 75])
        ax.set_yticklabels(["0", "25%", "50%", "75%"])
        ax.yaxis.grid(True, color=GRID, lw=1, zorder=0)
        ax.set_axisbelow(True)
        ax.set_title(title, loc="left", fontsize=11, color=INK, pad=8)
    fig.suptitle("On the real toys: the talking toy mostly disappears, and the child is understood",
                 x=0.012, y=0.985, ha="left", fontsize=13, color=INK, fontweight="bold")
    fig.text(0.012, 0.9, "Dyno, Sage and Penny, 12 recorded sequences replayed offline, words scored by a speech recogniser (Nov 14)",
             ha="left", color=MUTED, fontsize=9.5)
    fig.subplots_adjust(left=0.06, right=0.985, top=0.76, bottom=0.16, wspace=0.08)
    fig.savefig(IMG / "aec-real-toys.png", facecolor=SURFACE)


if __name__ == "__main__":
    simulation()
    real_toys()
