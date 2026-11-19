"""Build an insight-first line chart: the title states the finding, one series
is highlighted, the rest are context, and the point that matters is annotated.

The same data drawn with library defaults usually has a generic title, a
legend the reader must decode and equal emphasis on every line. This module
makes the deliberate choices explicit so they can be reviewed and tested.
"""
from __future__ import annotations

from dataclasses import dataclass

import matplotlib

matplotlib.use("Agg")                          # render without a display
import matplotlib.pyplot as plt                # noqa: E402

FOCUS = "#0072B2"      # Okabe-Ito blue: distinguishable with common colour-vision deficiencies
CONTEXT = "#B0B0B0"
TEXT = "#333333"


@dataclass(frozen=True)
class Finding:
    series: str
    start: float
    end: float

    @property
    def change(self) -> float:
        return self.end - self.start

    @property
    def pct_change(self) -> float:
        if self.start == 0:
            raise ValueError("percentage change from zero is undefined")
        return self.change / abs(self.start) * 100


def headline(f: Finding, metric: str, period: str) -> str:
    """A title that states the finding, e.g. 'North region orders fell 18% in Q1'."""
    if abs(f.pct_change) < 1:
        return f"{f.series} {metric} held steady {period}"
    direction = "rose" if f.change > 0 else "fell"
    return f"{f.series} {metric} {direction} {abs(f.pct_change):.0f}% {period}"


def insight_chart(x: list, series: dict[str, list[float]], focus: str, metric: str,
                  period: str, unit: str = "", source: str = "", path: str | None = None):
    if focus not in series:
        raise KeyError(f"focus series {focus!r} not in data")
    for name, ys in series.items():
        if len(ys) != len(x):
            raise ValueError(f"{name}: {len(ys)} values for {len(x)} x positions")

    f = Finding(focus, series[focus][0], series[focus][-1])
    fig, ax = plt.subplots(figsize=(8, 4.5), dpi=100)

    for name, ys in series.items():                  # context first, so focus draws on top
        if name != focus:
            ax.plot(x, ys, color=CONTEXT, linewidth=1.5)
            ax.annotate(name, (x[-1], ys[-1]), xytext=(6, 0), textcoords="offset points",
                        va="center", color=CONTEXT, fontsize=9)
    ax.plot(x, series[focus], color=FOCUS, linewidth=3)
    ax.annotate(focus, (x[-1], f.end), xytext=(6, 0), textcoords="offset points",
                va="center", color=FOCUS, fontsize=10, fontweight="bold")
    ax.annotate(f"{f.end:,.0f}{unit} ({f.pct_change:+.0f}%)", (x[-1], f.end), xytext=(-10, 14 if f.change >= 0 else -18),
                textcoords="offset points", ha="right", color=FOCUS, fontsize=10)

    ax.set_title(headline(f, metric, period), loc="left", fontsize=13, fontweight="bold", color=TEXT)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.tick_params(colors=TEXT, labelsize=9)
    ax.grid(axis="y", color="#E5E5E5", linewidth=0.8)
    ax.set_axisbelow(True)
    if source:
        fig.text(0.01, 0.01, f"Source: {source}", fontsize=8, color="#666666")
    fig.tight_layout()
    if path:
        fig.savefig(path)
    return fig, ax, f
