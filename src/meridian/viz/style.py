"""The house style for every chart the platform produces.

Client-facing material has to look like it came from one firm, so colours,
fonts and spacing are defined once here and nothing downstream hard-codes a hex
value. The palette is deliberately restrained: a navy, a teal and a violet carry
the data, green and crimson are reserved for gain and loss, and the amber accent
is used only to draw the eye to a single thing on a chart - never as a fill for a
whole series.

Matplotlib is forced onto the ``Agg`` backend because charts are produced by a
CLI and by CI, where there is no display attached.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from datetime import date
from pathlib import Path
from typing import Any, Literal

import matplotlib

matplotlib.use("Agg")

# These imports must follow the backend selection above
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.axes import Axes
from matplotlib.figure import Figure

PALETTE: dict[str, str] = {
    "ink": "#12203A",  # headings and body text
    "muted": "#5C6B82",  # secondary text
    "navy": "#1B3A6B",
    "teal": "#1F8A80",
    "violet": "#6A4C93",
    "slate": "#4A5C75",
    "sky": "#4E86C7",
    "gain": "#2E7D5B",
    "loss": "#B3202C",
    "accent": "#E07A29",  # amber: highlights only, never a whole series
    "grid": "#D7DEE8",
    "band": "#EDF2F8",
    "surface": "#FFFFFF",
}

#: Default series colours, in order. The accent is not in the cycle on purpose.
SERIES: tuple[str, ...] = (
    PALETTE["navy"],
    PALETTE["teal"],
    PALETTE["violet"],
    PALETTE["sky"],
    PALETTE["slate"],
    PALETTE["gain"],
    PALETTE["loss"],
)

FONT_STACK = ["DejaVu Sans", "Segoe UI", "Helvetica Neue", "Arial", "sans-serif"]


def apply_house_style() -> None:
    """Set the global rcParams. Idempotent, and safe to call from any entry point."""
    plt.rcParams.update(
        {
            "figure.facecolor": PALETTE["surface"],
            "figure.dpi": 110,
            "savefig.facecolor": PALETTE["surface"],
            "savefig.bbox": "tight",
            "axes.facecolor": PALETTE["surface"],
            "axes.edgecolor": PALETTE["grid"],
            "axes.labelcolor": PALETTE["muted"],
            "axes.titlecolor": PALETTE["ink"],
            "axes.titlesize": 11,
            "axes.titleweight": "bold",
            "axes.titlelocation": "left",
            "axes.titlepad": 10,
            "axes.labelsize": 9,
            "axes.linewidth": 0.8,
            "axes.grid": True,
            "axes.axisbelow": True,
            "axes.prop_cycle": plt.cycler(color=list(SERIES)),
            "axes.spines.top": False,
            "axes.spines.right": False,
            "grid.color": PALETTE["grid"],
            "grid.linewidth": 0.7,
            "grid.alpha": 0.9,
            "font.family": "sans-serif",
            "font.sans-serif": FONT_STACK,
            "font.size": 9,
            "text.color": PALETTE["ink"],
            "xtick.color": PALETTE["muted"],
            "ytick.color": PALETTE["muted"],
            "xtick.labelsize": 8,
            "ytick.labelsize": 8,
            "legend.frameon": False,
            "legend.fontsize": 8,
            "lines.linewidth": 1.8,
            "lines.solid_capstyle": "round",
            "patch.linewidth": 0,
        }
    )


def new_figure(width: float = 11.0, height: float = 6.0, **kwargs: Any) -> Figure:
    apply_house_style()
    return plt.figure(figsize=(width, height), **kwargs)


def title_block(fig: Figure, title: str, subtitle: str | None = None) -> None:
    """A left-aligned title with an optional explanatory line, as used in client packs.

    The offsets are computed in inches rather than in figure fractions, so the
    block looks the same on a tall multi-panel page and on a single wide chart.
    """
    height = fig.get_figheight()
    fig.suptitle(
        title,
        x=0.012,
        y=1 - 0.22 / height,
        ha="left",
        va="top",
        fontsize=15,
        fontweight="bold",
        color=PALETTE["ink"],
    )
    if subtitle:
        fig.text(0.012, 1 - 0.52 / height, subtitle, ha="left", va="top", fontsize=9.5, color=PALETTE["muted"])


def caption(fig: Figure, text: str) -> None:
    """A source or methodology note along the bottom edge."""
    fig.text(0.012, 0.16 / fig.get_figheight(), text, ha="left", va="bottom", fontsize=7.5, color=PALETTE["muted"])


def style_axes(
    ax: Axes,
    *,
    title: str | None = None,
    xlabel: str | None = None,
    ylabel: str | None = None,
    grid: Literal["x", "y", "both"] | None = "y",
) -> Axes:
    if title:
        ax.set_title(title)
    if xlabel:
        ax.set_xlabel(xlabel)
    if ylabel:
        ax.set_ylabel(ylabel)
    if grid is None:
        ax.grid(visible=False)
    else:
        ax.grid(visible=True, axis=grid)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    return ax


def annotate(ax: Axes, text: str, xy: tuple[float, float], *, highlight: bool = False, **kwargs: Any) -> None:
    """Point at one number. ``highlight`` is the only route to the amber accent."""
    ax.annotate(
        text,
        xy=xy,
        color=PALETTE["accent"] if highlight else PALETTE["muted"],
        fontsize=kwargs.pop("fontsize", 8),
        fontweight="bold" if highlight else "normal",
        **kwargs,
    )


def x_of(day: date) -> float:
    """A date as a matplotlib x coordinate.

    Plotting calls accept dates directly, but the typed signatures of ``axvline``,
    ``axvspan``, ``annotate`` and ``set_xlim`` only admit floats; converting once
    here keeps the charts type-checked without scattering ignores.
    """
    return float(mdates.date2num(day))


def series_colours(count: int) -> list[str]:
    """As many distinct series colours as asked for, cycling if necessary."""

    def cycle() -> Iterator[str]:
        while True:
            yield from SERIES

    stream = cycle()
    return [next(stream) for _ in range(count)]


def legend_below(ax: Axes, handles: Sequence[Any] | None = None, *, columns: int = 4) -> None:
    ax.legend(
        handles=list(handles) if handles is not None else None,
        loc="upper center",
        bbox_to_anchor=(0.5, -0.12),
        ncol=columns,
        frameon=False,
    )


def save_figure(fig: Figure, path: str | Path, *, dpi: int = 150, close: bool = True) -> Path:
    """Write a figure to disk, creating the directory, and return where it landed."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(destination, dpi=dpi)
    if close:
        plt.close(fig)
    return destination
