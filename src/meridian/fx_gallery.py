"""The Day 2 revisit charts: market data and its quality, on 27 years of real central bank fixings.

Computed from the packaged ECB and Federal Reserve rates (``marketdata.fx_reference``),
the currency regimes (``refdata.currency_regimes``) and the quality engine. The
pence-trap and missing-ex-date figures use small demonstration series, because those
faults were found by reading the code rather than in this data.
"""

from __future__ import annotations

import math
from datetime import date, time, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

import numpy as np
from matplotlib.figure import Figure

from .domain.corporate_actions import CashDividend, StockSplit
from .marketdata.adjustments import adjust_history
from .marketdata.fx_reference import ecb_rates
from .marketdata.golden import FixingTime
from .marketdata.quotes import Quote
from .marketdata.series import TimeSeries
from .quality.context import SeriesContext
from .quality.fx_regimes import fx_context, managed_days
from .quality.rules import RobustOutlier, StaleMark, UnexplainedJump
from .refdata.currency_regimes import EndReason, ending_for, inactive_spans, regime_on, regimes_for
from .services.fx_review import fx_quality_review, source_comparison
from .viz.fx_reference import (
    BandPanel,
    EventPanel,
    Fix,
    GapSeries,
    Lifeline,
    StageBar,
    StalePoint,
    plot_bands,
    plot_events,
    plot_findings_waterfall,
    plot_fixing_clock,
    plot_lifecycles,
    plot_missing_ex_date,
    plot_open_findings,
    plot_pence_trap,
    plot_staleness,
    plot_two_sources,
    plot_volatility_map,
)
from .viz.style import PALETTE

if TYPE_CHECKING:
    from .gallery import GalleryItem

TODAY = date(2026, 10, 1)
LESSONS = (
    "Day 2's rules, written for share prices and measured on a synthetic market",
    "a price cannot move by less than a tick, and repeats are a probability",
    "no fixings after the euro, a redenomination or a suspension",
    "pegs, bands, crawls and floors are judged against the band, not by statistics",
    "documented market days explain their findings; the rest is a work queue",
)


def waterfall_chart() -> Figure:
    review = fx_quality_review()
    stages = [
        StageBar(stage.name, dict(stage.by_rule()), stage.explained, lesson)
        for stage, lesson in zip(review.stages, LESSONS, strict=True)
    ]
    return plot_findings_waterfall(
        stages, review.observations, len(review.pairs), f"{review.first.year}-{review.last.year}"
    )


# ---------------------------------------------------------------------------- lifecycles
def _segments(currency: str, days: tuple[date, ...]) -> tuple[tuple[date, date, str], ...]:
    segments: list[tuple[date, date, str]] = []
    for day in days:
        regime = regime_on(currency, day)
        kind = regime.kind.value if regime is not None else "float"
        if segments and segments[-1][2] == kind:
            segments[-1] = (segments[-1][0], day, kind)
        else:
            segments.append((day, day, kind))
    return tuple(segments)


def _ending_label(currency: str) -> str:
    ending = ending_for(currency)
    if ending is None:
        return ""
    if ending.reason is EndReason.EURO:
        return f"euro {ending.last_fixing.year + 1} at {ending.conversion_rate}"
    if ending.reason is EndReason.REDENOMINATED:
        return "redenominated " + ("1:1,000,000" if currency == "TRL" else "1:10,000")
    return "suspended" if ending.resumed is None else ""


def lifecycle_chart() -> Figure:
    rates = ecb_rates()
    lines = []
    for pair, series in rates.items():
        currency = pair[3:]
        gaps = tuple((after, until) for after, until in inactive_spans(currency) if until is not None)
        lines.append(Lifeline(currency, series.first.day, series.last.day, _segments(currency, series.days), gaps,
                              _ending_label(currency)))  # fmt: skip
    lines.sort(
        key=lambda line: (line.last < TODAY - timedelta(days=30), -line.last.toordinal(), line.first, line.currency)
    )
    return plot_lifecycles(lines, TODAY)


# ---------------------------------------------------------------------------- bands
def _deviation_panel(currency: str, start: date, end: date, title: str, note: str) -> BandPanel:
    series = ecb_rates()[f"EUR{currency}"]
    days, values, bands = [], [], []
    floor = False
    for point in series:
        if not start <= point.day <= end:
            continue
        regime = regime_on(currency, point.day)
        if regime is None or regime.central is None:
            continue
        days.append(point.day)
        values.append(float(point.value / regime.central - 1) * 100)
        floor = regime.kind.value == "floor"
        if regime.band:
            bands.append(regime.band * 100)
    return BandPanel(title, tuple(days), tuple(values), max(bands) if bands else None, floor, note)


def bands_chart() -> Figure:
    panels = [
        _deviation_panel("BGN", date(2000, 7, 19), date(2025, 12, 31), "BGN: a currency board, 1.95583",
                         "25 years within 0.6% of the board rate"),
        _deviation_panel("DKK", date(1999, 1, 4), TODAY, "DKK: ERM II, 7.46038 +/-2.25%",
                         "never further than 0.5% from the centre"),
        _deviation_panel("LVL", date(2005, 1, 1), date(2013, 12, 31), "LVL: pegged at 0.702804 +/-1%",
                         "held at the edges of its band"),
        _deviation_panel("SKK", date(2005, 11, 28), date(2008, 12, 31), "SKK: ERM II, two revaluations",
                         "each against the central rate of its day"),
        _deviation_panel("CHF", date(2011, 9, 6), date(2015, 1, 14), "CHF: the SNB's floor of 1.20",
                         "defended for three years and four months"),
        _deviation_panel("CZK", date(2013, 11, 7), date(2017, 4, 5), "CZK: the CNB's floor of 27",
                         "held, then released on 6 April 2017"),
    ]  # fmt: skip
    return plot_bands(panels)


# ---------------------------------------------------------------------------- volatility
def volatility_chart() -> Figure:
    rates = ecb_rates()
    pairs = sorted(rates, key=lambda pair: pair[3:])
    years = list(range(1999, TODAY.year + 1))
    matrix = np.full((len(pairs), len(years)), np.nan)
    for row, pair in enumerate(pairs):
        context = SeriesContext.from_series(pair, rates[pair], "TARGET", inactive=inactive_spans(pair[3:]))
        by_year: dict[int, list[float]] = {}
        for _, day, value in context.adjusted_spans:
            by_year.setdefault(day.year, []).append(value)
        for column, year in enumerate(years):
            values = by_year.get(year, [])
            if len(values) >= 50:
                matrix[row, column] = float(np.std(values)) * math.sqrt(252)
    order = np.argsort(np.nanmean(matrix, axis=1))
    return plot_volatility_map([pairs[i][3:] for i in order], years, matrix[order])


# ---------------------------------------------------------------------------- staleness
def staleness_chart() -> Figure:
    rule = StaleMark()
    points = []
    for pair, series in ecb_rates().items():
        currency = pair[3:]
        context = fx_context(pair, series)
        sigmas = context.recent_volatility()
        expected = [rule.chance_unchanged(sigma, tick) for sigma, tick in zip(sigmas, context.tick_returns, strict=True)
                    if sigma is not None]  # fmt: skip
        returns = [value for _, value in context.adjusted_returns[20:]]
        if not expected or not returns:
            continue
        kinds = [regime.kind.value for regime in regimes_for(currency)]
        regime = kinds[0] if kinds and kinds[0] != "floor" else "float"
        observed = sum(1 for value in returns if value == 0) / len(returns)
        points.append(StalePoint(currency, float(np.mean(expected)), observed, regime))
    return plot_staleness(points)


# ---------------------------------------------------------------------------- events
def _spans(days: frozenset[date], start: date, end: date) -> tuple[tuple[date, date], ...]:
    inside = sorted(day for day in days if start <= day <= end)
    spans: list[tuple[date, date]] = []
    for day in inside:
        if spans and (day - spans[-1][1]).days <= 5:
            spans[-1] = (spans[-1][0], day)
        else:
            spans.append((day, day))
    return tuple(spans)


EVENT_WINDOWS = (
    ("EURCHF", "the floor and its end", date(2010, 6, 1), date(2015, 8, 31), date(2015, 1, 15)),
    ("EURGBP", "the Brexit vote", date(2016, 3, 1), date(2016, 10, 31), date(2016, 6, 24)),
    ("EURTRY", "the 2018 lira crisis", date(2018, 4, 1), date(2018, 11, 30), date(2018, 8, 10)),
    ("EURRUB", "the rouble crisis", date(2014, 9, 1), date(2015, 3, 31), date(2014, 12, 16)),
    ("EURCZK", "the CNB cap, 2013-2017", date(2013, 6, 1), date(2017, 9, 30), date(2017, 4, 6)),
    ("EURISK", "Iceland, 2008: a frozen fixing", date(2008, 1, 1), date(2008, 12, 9), date(2008, 10, 6)),
)


def events_chart() -> Figure:
    review = fx_quality_review()
    rates = ecb_rates()
    panels = []
    for pair, title, start, end, marker in EVENT_WINDOWS:
        series = rates[pair]
        days = tuple(day for day in series.days if start <= day <= end)
        entry = review.reviews.get(pair)
        flagged: list[tuple[date, float, str]] = []
        if entry is not None:
            for finding, _ in entry.explained:
                if start <= finding.day <= end:
                    flagged.append((finding.day, float(series[finding.day]), "explained"))
            for finding in entry.open:
                if start <= finding.day <= end and finding.day in series:
                    flagged.append((finding.day, float(series[finding.day]), "open"))
        excluded = _spans(managed_days(pair[3:], series.days), start, end)
        panels.append(EventPanel(pair, title, days, tuple(float(series[day]) for day in days), tuple(flagged), excluded,
                                 marker))  # fmt: skip
    return plot_events(panels)


# ---------------------------------------------------------------------------- two central banks
LABELS = {
    date(2016, 3, 10): "ECB eases between the fixes",
    date(2022, 11, 10): "US inflation surprise",
    date(2008, 12, 18): "the dollar slides after the Fed's cut to zero",
    date(2015, 1, 16): "the day after the SNB",
    date(2022, 10, 21): "Bank of Japan intervenes",
}


def two_sources_chart() -> Figure:
    series = []
    for gap in source_comparison():
        largest = tuple((day, value, LABELS.get(day, f"{day:%d %b %Y}")) for day, value in gap.largest(3))
        series.append(GapSeries(gap.pair, gap.days, gap.gaps_bp, gap.next_ecb_move_bp, gap.median_abs,
                                gap.lead_correlation, largest))  # fmt: skip
    return plot_two_sources(series)


def _utc_hour(fixing: FixingTime, day: date) -> float:
    moment = fixing.on(day)
    return moment.hour + moment.minute / 60


def fixing_clock_chart() -> Figure:
    winter, summer, mismatch = date(2026, 1, 15), date(2026, 7, 15), date(2026, 3, 10)
    fixings = {
        "Tokyo 9:55 (TTM)": FixingTime(time(9, 55), "Asia/Tokyo"),
        "ECB 14:15 Frankfurt": FixingTime(time(14, 15), "Europe/Berlin"),
        "WM/Reuters 16:00 London": FixingTime(time(16, 0), "Europe/London"),
        "Fed H.10 noon New York": FixingTime(time(12, 0), "America/New_York"),
    }
    colours = (PALETTE["violet"], PALETTE["navy"], PALETTE["teal"], PALETTE["accent"])
    fixes = [Fix(name, _utc_hour(fixing, winter), _utc_hour(fixing, summer), colour)
             for (name, fixing), colour in zip(fixings.items(), colours, strict=True)]  # fmt: skip

    def gap(a: str, b: str, day: date) -> float:
        return (fixings[b].on(day) - fixings[a].on(day)).total_seconds() / 3600

    gaps = [
        ("ECB to Fed", gap("ECB 14:15 Frankfurt", "Fed H.10 noon New York", winter),
         gap("ECB 14:15 Frankfurt", "Fed H.10 noon New York", mismatch)),
        ("ECB to WM/Reuters", gap("ECB 14:15 Frankfurt", "WM/Reuters 16:00 London", winter),
         gap("ECB 14:15 Frankfurt", "WM/Reuters 16:00 London", mismatch)),
        ("WM/Reuters to Fed", gap("WM/Reuters 16:00 London", "Fed H.10 noon New York", winter),
         gap("WM/Reuters 16:00 London", "Fed H.10 noon New York", mismatch)),
    ]  # fmt: skip
    return plot_fixing_clock(fixes, gaps)


# ---------------------------------------------------------------------------- the review fixes
def pence_trap_chart() -> Figure:
    rng = np.random.default_rng(11)
    days: list[date] = []
    points: list[tuple[date, Decimal]] = []
    price = 1950.0
    day = date(2025, 1, 2)
    while len(days) < 330:
        if day.weekday() < 5:
            price *= math.exp(rng.normal(0.0002, 0.012))
            days.append(day)
            points.append((day, Decimal(f"{price:.1f}")))
        day += timedelta(days=1)
    series = TimeSeries(points, name="GB-DEMO")
    ex_days = [days[90], days[220]]
    dividends = [CashDividend(action_id=f"DEMO-{index}", instrument_id="GB-DEMO", ex_date=ex, amount=Decimal("0.198"),
                              currency="GBP") for index, ex in enumerate(ex_days)]  # fmt: skip
    correct = adjust_history(series, dividends, price_unit="GBX")
    naive = adjust_history(series, dividends)
    return plot_pence_trap(
        days,
        [float(value) for _, value in points],
        [float(correct[d]) for d in days],
        [float(naive[d]) for d in days],
        ex_days,
        19.8 / 1950,
        0.198 / 1950,
    )


def missing_ex_date_chart() -> Figure:
    rng = np.random.default_rng(4)
    days: list[date] = []
    day = date(2026, 1, 5)
    while len(days) < 120:
        if day.weekday() < 5:
            days.append(day)
        day += timedelta(days=1)
    split_day = days[80]
    quotes, price = [], 400.0
    for item in days:
        price *= float(np.exp(rng.normal(0, 0.01)))
        if item == split_day:
            continue
        shown = price / 4 if item > split_day else price
        quotes.append(Quote(instrument_id="X", day=item, close=Decimal(f"{shown:.2f}"), currency="USD"))
    split = StockSplit(action_id="X-SPLIT", instrument_id="X", ex_date=split_day, numerator=4)
    fixed = SeriesContext.build("X", quotes, "WEEKEND", actions=[split])
    blind = SeriesContext.build("X", quotes, "WEEKEND")  # as v1.1.0 saw it: the event never matched a print
    rules = (RobustOutlier(), UnexplainedJump())
    before = dict(blind.adjusted_returns)
    after = dict(fixed.adjusted_returns)
    window = [d for d in days if d in after and days[50] <= d <= days[110]]
    return plot_missing_ex_date(
        window,
        [before[d] for d in window],
        [after[d] for d in window],
        split_day,
        sum(len(rule.check(blind)) for rule in rules),
        sum(len(rule.check(fixed)) for rule in rules),
    )


def open_findings_chart() -> Figure:
    review = fx_quality_review()
    rows = [(finding.key[3:], finding.day, finding.rule, finding.message) for finding in review.open_findings]
    return plot_open_findings(rows, len(review.explained))


def fx_reference_items() -> tuple[GalleryItem, ...]:
    from .gallery import GalleryItem

    def item(filename: str, title: str, description: str, builder, group: str) -> GalleryItem:  # type: ignore[no-untyped-def]
        return GalleryItem(filename, title, description, builder, group)

    return (
        item("fx-quality-waterfall.png", "The quality engine on real data",
             "1,282 findings on 27 years of ECB fixings, and where each step of awareness sent them.",
             waterfall_chart, "quality"),
        item("currency-lifecycles.png", "Forty-one currencies against the euro",
             "Every currency the ECB has fixed since 1999: its regime, and how it ended.",
             lifecycle_chart, "reference data"),
        item("pegs-and-bands.png", "A pegged rate is supposed to look stale",
             "Boards, ERM II bands and floors, as distances from their central rates.",
             bands_chart, "market data"),
        item("euro-volatility-map.png", "Twenty-seven years of the euro, currency by currency",
             "Annualised volatility of every ECB fixing, year by year.",
             volatility_chart, "market data"),
        item("staleness-model.png", "How often should a rate not move?",
             "Expected unchanged fixings from volatility and resolution, against the real ones.",
             staleness_chart, "quality"),
        item("real-fx-events.png", "Real days, real findings",
             "The findings around six documented events, explained and open.",
             events_chart, "quality"),
        item("ecb-vs-fed.png", "Two central banks, one exchange rate",
             "The ECB's 14:15 fix against the Fed's noon rate, and why they differ.",
             two_sources_chart, "market data"),
        item("fixing-clock.png", "When is 'the' price?",
             "The world's FX fixes on one UTC day, and how daylight saving moves them.",
             fixing_clock_chart, "market data"),
        item("pence-trap.png", "The pence trap",
             "A sterling dividend on a share quoted in pence, adjusted right and wrong.",
             pence_trap_chart, "market data"),
        item("missing-ex-date.png", "A split on a day with no print",
             "The returns around an ex-date the feed missed, before and after the fix.",
             missing_ex_date_chart, "quality"),
        item("fx-open-findings.png", "What is left for a person",
             "Every finding still open after 27 years of fixings were reviewed.",
             open_findings_chart, "quality"),
    )  # fmt: skip
