"""Charts for the Day 9 revisit: the platform under concurrent requests and an attacker's questions.

The functions take plain inputs, prepared in :mod:`meridian.platform_revisited_gallery`.
"""

from __future__ import annotations

import textwrap
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.patches import FancyBboxPatch

from .style import PALETTE, caption, new_figure, style_axes, title_block

DAY9, REVISITED = PALETTE["muted"], PALETTE["navy"]


# ---------------------------------------------------------------------------- under load
@dataclass(frozen=True)
class Promise:
    label: str
    day9: float  # share of attempts that broke the promise
    revisited: float
    detail: str


def plot_under_load(promises: Sequence[Promise], how: str) -> Figure:
    fig = new_figure(14.0, 6.6)
    title_block(
        fig,
        "Four processes, one database, everything at once: the promises Day 9 broke",
        "Requests sent together to four API processes sharing one PostgreSQL database, spread over them as a load "
        "balancer would. Nothing forced: the races happen by themselves.",
    )
    ax = fig.add_axes((0.30, 0.17, 0.66, 0.62))
    y = np.arange(len(promises))[::-1]
    ax.barh(y + 0.18, [p.day9 for p in promises], height=0.34, color=DAY9, label="Day 9")
    ax.barh(y - 0.18, [p.revisited for p in promises], height=0.34, color=REVISITED, label="revisited")
    for yi, promise in zip(y, promises, strict=True):
        ax.text(promise.day9 + 0.005, yi + 0.18, f"{promise.day9:.0%}", va="center", fontsize=9, color=DAY9)
        ax.text(
            promise.revisited + 0.005,
            yi - 0.18,
            f"{promise.revisited:.0%}",
            va="center",
            fontsize=9,
            color=REVISITED,
            fontweight="bold",
        )
        ax.text(-0.01, yi - 0.42, promise.detail, ha="right", va="center", fontsize=8, color=PALETTE["muted"])
    ax.set_yticks(y, [textwrap.fill(p.label, 34) for p in promises], fontsize=9.5)
    ax.xaxis.set_major_formatter(lambda value, _: f"{value:.0%}")
    ax.set_xlim(0, max(max(p.day9 for p in promises) * 1.25, 0.05))
    style_axes(ax, xlabel="share of attempts that broke the promise", grid="x")
    ax.legend(frameon=False, fontsize=9, loc="lower right")
    caption(fig, textwrap.fill(how, 230))
    return fig


# ---------------------------------------------------------------------------- sign-in timing
def plot_sign_in(times: Mapping[str, Mapping[str, Sequence[float]]]) -> Figure:
    fig = new_figure(14.0, 6.0)
    title_block(
        fig,
        "What a failed sign-in took, and what that told an attacker",
        "The same message for every failure - but Day 9 hashed the password only for an account that existed and was "
        "active, so a wrong guess at a real username took thirty times longer than one at a name that is not there.",
    )
    cases = list(next(iter(times.values())))
    for index, (version, colour) in enumerate((("day9", DAY9), ("revisited", REVISITED))):
        ax = fig.add_axes((0.06 + index * 0.48, 0.17, 0.40, 0.58))
        for position, case in enumerate(cases):
            values = np.array(times[version][case])
            jitter = np.linspace(-0.12, 0.12, len(values))
            ax.scatter(np.full(len(values), position) + jitter, values, s=18, color=colour, alpha=0.8)
            ax.text(position + 0.2, float(np.median(values)), f"{np.median(values):.0f} ms", va="center", fontsize=9)
        ax.set_yscale("log")
        ax.set_ylim(2, 600)
        ax.set_xticks(range(len(cases)), [textwrap.fill(case, 14) for case in cases], fontsize=9)
        ax.set_xlim(-0.5, len(cases) - 0.3)
        style_axes(
            ax,
            title="Day 9" if version == "day9" else "Revisited: one hash for every sign-in",
            ylabel="milliseconds, log scale" if index == 0 else None,
            grid="y",
        )
    caption(
        fig,
        "PBKDF2-HMAC-SHA256 at 600,000 iterations (OWASP 2023). For an unknown username the revisited sign-in checks "
        "the password against a decoy hash no password matches.",
    )
    return fig


# ---------------------------------------------------------------------------- the races, step by step
@dataclass(frozen=True)
class Race:
    title: str
    first: tuple[str, ...]  # the steps of request A, in time
    second: tuple[str, ...]  # of request B
    outcome: str
    fix: str


def _lane(ax: Axes, y: float, steps: Sequence[str], colour: str, name: str) -> None:
    ax.text(-0.02, y, name, ha="right", va="center", fontsize=9, fontweight="bold", color=colour)
    for index, step in enumerate(steps):
        if not step:
            continue
        ax.add_patch(
            FancyBboxPatch(
                (index * 0.25 + 0.01, y - 0.09),
                0.23,
                0.18,
                boxstyle="round,pad=0.005,rounding_size=0.02",
                facecolor=PALETTE["band"],
                edgecolor=colour,
                lw=1.2,
            )
        )
        ax.text(index * 0.25 + 0.125, y, textwrap.fill(step, 20), ha="center", va="center", fontsize=8)


def plot_races(races: Sequence[Race]) -> Figure:
    fig = new_figure(14.0, 9.0)
    title_block(
        fig,
        "Three checks that two requests passed together",
        "Each Day 9 write read the state, decided, then wrote - in separate steps. Two requests in the same moment "
        "both read before either wrote. The fix in each case lets the database decide, in one step.",
    )
    height = 0.80 / len(races)
    for index, race in enumerate(races):
        top = 0.86 - (index + 1) * height
        ax = fig.add_axes((0.10, top + 0.02, 0.56, height - 0.06))
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis("off")
        ax.set_title(race.title, loc="left", fontsize=11, fontweight="bold", color=PALETTE["ink"])
        _lane(ax, 0.70, race.first, PALETTE["teal"], "request A")
        _lane(ax, 0.25, race.second, PALETTE["violet"], "request B")
        side = fig.add_axes((0.69, top + 0.02, 0.29, height - 0.06))
        side.axis("off")
        side.text(0, 0.95, "Day 9", fontsize=9, fontweight="bold", color=PALETTE["loss"], va="top")
        side.text(0, 0.80, textwrap.fill(race.outcome, 52), fontsize=8.5, color=PALETTE["ink"], va="top")
        side.text(0, 0.42, "Revisited", fontsize=9, fontweight="bold", color=PALETTE["gain"], va="top")
        side.text(0, 0.27, textwrap.fill(race.fix, 52), fontsize=8.5, color=PALETTE["ink"], va="top")
    caption(fig, "Each interleaving is forced in the unit tests by a barrier, and occurs unforced under load.")
    return fig


# ---------------------------------------------------------------------------- the stale token
def plot_stale_rights(minutes: int, deactivated_at: int) -> Figure:
    fig = new_figure(14.0, 4.8)
    title_block(
        fig,
        "An account switched off is switched off at once",
        "Day 9 took a caller's rights from their token alone: a leaver deactivated, or a manager moved off the desk, "
        f"kept every right for up to {minutes} minutes. Each request now reads the account as it is.",
    )
    ax = fig.add_axes((0.10, 0.22, 0.86, 0.50))
    ax.set_xlim(-1, minutes + 1)
    ax.set_ylim(-0.5, 1.6)
    ax.axis("off")
    for y, label, colour, until in ((1.1, "Day 9", DAY9, minutes), (0.3, "revisited", REVISITED, deactivated_at)):
        ax.text(-1.5, y, label, ha="right", va="center", fontsize=10, fontweight="bold", color=colour)
        ax.plot([0, until], [y, y], color=colour, lw=10, solid_capstyle="butt")
        if until < minutes:
            ax.plot([until, minutes], [y, y], color=PALETTE["grid"], lw=10, solid_capstyle="butt")
            ax.text(until + 0.5, y + 0.28, "401: the account is not active", fontsize=9, color=colour)
        else:
            ax.text(until - 0.5, y + 0.28, "still trading", ha="right", fontsize=9, color=PALETTE["loss"])
    ax.axvline(deactivated_at, color=PALETTE["accent"], lw=1.4, ymin=0.05, ymax=0.95)
    ax.text(deactivated_at, 1.55, "account deactivated", ha="center", fontsize=9, color=PALETTE["accent"])
    ax.text(0, -0.35, "token issued", fontsize=9, color=PALETTE["muted"])
    ax.text(minutes, -0.35, f"token expires ({minutes} min)", ha="right", fontsize=9, color=PALETTE["muted"])
    caption(fig, "The same holds for a change of role: a manager moved to analyst cannot enter the next order.")
    return fig


# ---------------------------------------------------------------------------- the review
@dataclass(frozen=True)
class ReviewPanel:
    title: str
    labels: tuple[str, ...]
    before: tuple[float, ...]
    after: tuple[float, ...]
    unit: str
    note: str


def plot_review(panels: Sequence[ReviewPanel]) -> Figure:
    fig = new_figure(14.0, 5.6)
    title_block(
        fig,
        "A second reading of Day 9: the figures the faults changed",
        "Each panel sets the figure Day 9 produced (grey) beside the corrected one (navy).",
    )
    for index, panel in enumerate(panels):
        ax = fig.add_axes((0.05 + index * 0.33, 0.30, 0.27, 0.48))
        x = np.arange(len(panel.labels))
        for xi, (old, new) in enumerate(zip(panel.before, panel.after, strict=True)):
            ax.plot([xi, xi], [old, new], color=PALETTE["grid"], lw=3, zorder=1)
            ax.plot(xi, old, "o", color=DAY9, ms=9, zorder=2, label="Day 9" if xi == 0 else None)
            ax.plot(xi, new, "o", color=REVISITED, ms=9, zorder=3, label="revisited" if xi == 0 else None)
            ax.text(xi - 0.08, old, f"{old:{panel.unit}}", va="center", ha="right", fontsize=8, color=DAY9)
            ax.text(
                xi + 0.08, new, f"{new:{panel.unit}}", va="center", fontsize=8, color=PALETTE["ink"], fontweight="bold"
            )
        values = [*panel.before, *panel.after]
        low, high = min(values), max(values)
        pad = (high - low) * 0.3 or abs(high) * 0.1 or 1.0
        ax.set_ylim(low - pad, high + pad)
        ax.set_xlim(-0.6, len(panel.labels) - 0.4)
        ax.set_xticks(x, panel.labels, fontsize=8.5)
        style_axes(ax, title=panel.title, grid="y")
        note = ax.text(0.0, -0.18, textwrap.fill(panel.note, 58), transform=ax.transAxes, fontsize=8)
        note.set_color(PALETTE["muted"])
        note.set_verticalalignment("top")
        if index == 0:
            ax.legend(frameon=False, fontsize=8.5, loc="upper right")
    return fig
