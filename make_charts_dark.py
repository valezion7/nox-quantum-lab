"""Rigenera i grafici del Report 001 in tema dark NOX (da experiments_results.json)."""
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
from matplotlib import pyplot as plt

HERE = Path(__file__).parent
d = json.loads((HERE / "experiments_results.json").read_text())

BG, PANEL, INK, DIM, VIOLET, TEAL, RED = (
    "#0a0d14", "#10141f", "#e9ebf2", "#9aa3b5", "#7c6cff", "#37e2d5", "#e05c5c")


def style(ax):
    ax.set_facecolor(PANEL)
    for s in ax.spines.values():
        s.set_color("#232a3a")
    ax.tick_params(colors=DIM)
    ax.yaxis.label.set_color(DIM)
    ax.title.set_color(INK)


# CHSH
c = d["chsh"]
fig, ax = plt.subplots(figsize=(6.4, 3.2), facecolor=BG)
ax.bar(c["labels"], c["E"], yerr=c["err"], color=[TEAL] * 3 + [VIOLET],
       width=0.55, ecolor=INK, capsize=3)
ax.axhline(0, color=DIM, lw=0.6)
ax.set_ylabel("Correlazione E")
ax.set_title(f"Le quattro correlazioni CHSH: S = {c['S']:.3f} ± {c['S_err']:.3f}")
style(ax)
fig.tight_layout()
fig.savefig(HERE / "chsh_dark.png", dpi=170, facecolor=BG)

# Grover
g = d["grover"]
total = sum(g["counts"].values())
keys = [format(i, "03b") for i in range(8)]
vals = [g["counts"].get(k, 0) / total * 100 for k in keys]
fig, ax = plt.subplots(figsize=(6.4, 3.2), facecolor=BG)
ax.bar(keys, vals, color=[VIOLET if k == g["target"] else "#3a4258" for k in keys])
ax.axhline(12.5, color=RED, lw=1.2, ls="--")
ax.text(6.6, 14, "caso: 12.5%", color=RED, fontsize=8)
ax.set_ylabel("% degli shot")
ax.set_title(f"Grover: la chiave {g['target']} emerge nel {g['hit_rate']*100:.1f}% delle misure")
style(ax)
fig.tight_layout()
fig.savefig(HERE / "grover_dark.png", dpi=170, facecolor=BG)
print("OK: chsh_dark.png, grover_dark.png")
