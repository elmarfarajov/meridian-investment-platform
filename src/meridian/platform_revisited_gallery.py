"""The Day 9 revisit charts: the platform under concurrent requests and an attacker's questions.

The load and sign-in figures were measured, not simulated: four API processes on
one PostgreSQL database, and sign-ins at the production work factor, against the
Day 9 code and the revisited code. They are kept in ``docs/data/platform-under-load.json``
with how they were measured, because a gallery build has neither a database
server nor the old code to run them again; the tests that guard each fault run
in CI.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

from matplotlib.figure import Figure

from .viz.platform_revisited import (
    Promise,
    Race,
    ReviewPanel,
    plot_races,
    plot_review,
    plot_sign_in,
    plot_stale_rights,
    plot_under_load,
)

if TYPE_CHECKING:
    from .gallery import GalleryItem

DATA = Path(__file__).resolve().parents[2] / "docs" / "data" / "platform-under-load.json"
RETRIES_PER_KEY = 10


@lru_cache(maxsize=1)
def measured() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(DATA.read_text(encoding="utf-8"))
    return data


def rates(version: str) -> tuple[float, float, float]:
    """Of each kind of attempt, the share that broke its promise: orders, retried orders, decisions."""
    run = measured()["load"][version]
    return (
        run["orders_500"] / run["orders_sent"],
        run["key_requests_500"] / (run["keys_sent"] * RETRIES_PER_KEY),
        run["both_told_decided"] / run["decisions"],
    )


def promises() -> list[Promise]:
    old, new = rates("day9"), rates("revisited")
    day9 = measured()["load"]["day9"]
    return [
        Promise(
            "Every order entered is accepted",
            old[0],
            new[0],
            f"{day9['orders_500']} of {day9['orders_sent']} failed with a 500: two took the same number",
        ),
        Promise(
            "A retried order (same Idempotency-Key) answers like the first",
            old[1],
            new[1],
            f"{day9['key_requests_500']} of {day9['keys_sent'] * RETRIES_PER_KEY} retries failed with a 500",
        ),
        Promise(
            "Two approvers at once: one decides, the other is told",
            old[2],
            new[2],
            f"{day9['both_told_decided']} of {day9['decisions']} orders: both told they had decided",
        ),
    ]


def under_load_chart() -> Figure:
    return plot_under_load(promises(), measured()["how"])


def sign_in_chart() -> Figure:
    return plot_sign_in(measured()["sign_in_ms"])


RACES = [
    Race(
        "Two orders entered at once",
        ("count the orders: 41", "number it ORD-000042", "insert, commit"),
        ("count the orders: 41", "number it ORD-000042", "", "insert: the number is taken"),
        "The second order fails with a 500, though nothing was wrong with it.",
        "The number comes from one UPDATE ... RETURNING on a counter row: the database hands each out once.",
    ),
    Race(
        "One order, sent twice at once with the same Idempotency-Key",
        ("is the key known? no", "enter the order", "store the key"),
        ("is the key known? no", "enter the order", "", "store the key: taken"),
        "Entered twice, or the retry answers 500: the key was checked and stored in separate steps.",
        "The order and its key are one transaction; a key already taken returns the first request's answer.",
    ),
    Race(
        "Two approvers decide one order at once",
        ("read: pending", "write: approved", "200: approved"),
        ("read: pending", "", "write: rejected", "200: rejected"),
        "Both are told they decided it; the order ends rejected while one officer believes it approved.",
        "One conditional UPDATE where the order is still pending: the second approver is told it was decided.",
    ),
]


def races_chart() -> Figure:
    return plot_races(RACES)


def stale_rights_chart() -> Figure:
    return plot_stale_rights(30, 5)


def median(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[len(ordered) // 2]


def review_chart() -> Figure:
    load = measured()["load"]["day9"]
    old, new = rates("day9"), rates("revisited")
    times = measured()["sign_in_ms"]
    unknown = "no such user"
    panels = [
        ReviewPanel(
            "Simultaneous orders failed, %",
            ("orders", "retries"),
            (old[0] * 100, old[1] * 100),
            (new[0] * 100, new[1] * 100),
            ".0f",
            f"Four processes, one PostgreSQL: {load['orders_sent']} orders and "
            f"{load['keys_sent'] * RETRIES_PER_KEY} retries sent in bursts.",
        ),
        ReviewPanel(
            "Orders decided twice, %",
            ("two approvers",),
            (old[2] * 100,),
            (new[2] * 100,),
            ".0f",
            "Both sessions were told 200, though only one decision stood.",
        ),
        ReviewPanel(
            "Failed sign-in, unknown name, ms",
            ("unknown user",),
            (median(times["day9"][unknown]),),
            (median(times["revisited"][unknown]),),
            ".0f",
            "Now as long as one for a real user: the time no longer tells which names exist.",
        ),
    ]
    return plot_review(panels)


def platform_revisited_items() -> tuple[GalleryItem, ...]:
    from .gallery import GalleryItem

    return (
        GalleryItem(
            "platform-under-load.png",
            "The promises Day 9 broke under load",
            "Four API processes on one PostgreSQL: orders failed, retries failed, orders decided twice.",
            under_load_chart,
            "web platform",
        ),
        GalleryItem(
            "race-timelines.png",
            "Three checks that two requests passed together",
            "The interleavings behind each fault, and how the database now decides.",
            races_chart,
            "web platform",
        ),
        GalleryItem(
            "sign-in-timing.png",
            "What a failed sign-in told an attacker",
            "Failed sign-ins for a real, an unknown and a deactivated user, before and after.",
            sign_in_chart,
            "web platform",
        ),
        GalleryItem(
            "stale-rights.png",
            "An account switched off is switched off at once",
            "A deactivated account's token, as Day 9 honoured it and as the platform does now.",
            stale_rights_chart,
            "web platform",
        ),
        GalleryItem(
            "platform-review.png",
            "A second reading of Day 9",
            "The figures the faults changed, before and after.",
            review_chart,
            "web platform",
        ),
    )
