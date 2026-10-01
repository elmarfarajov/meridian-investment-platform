"""The Day 1 revisit charts: the rates engine validated, curves built from instruments, and 36 years of history.

Every number is computed here:

- from the analytics layer;
- from the packaged US Treasury and Federal Reserve data;
- from QuantLib, for the validation charts. QuantLib is a development dependency.

The calendar breaks of version 1.0.0 are the one recorded input
(``docs/data/calendar-breaks-v1.0.0.json``). The old calendars no longer exist in
the code to be measured again.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
from matplotlib.figure import Figure

from .analytics.bonds import FixedRateBond
from .analytics.curve_building import (
    SOFR_TENORS,
    InstrumentCurve,
    OvernightIndexSwap,
    overnight_index_swap,
    sofr_curve,
)
from .analytics.curve_pca import CurvePCA, curve_pca, rolling_explained
from .analytics.curves import bootstrap_par_curve
from .analytics.parametric import NelsonSiegelSvensson, fit_par_curve
from .core.astronomy import JST, equinox
from .marketdata.rates_history import (
    GSW_TENORS,
    TENOR_YEARS,
    gsw_curve,
    illustrative_sofr_quotes,
    par_curve_on,
    treasury_matrix,
    treasury_par_yields,
)
from .viz.rates_engine import (
    BreakSet,
    CheckRow,
    FitPanel,
    plot_bucketed_dv01,
    plot_calendar_breaks,
    plot_equinox_arbiter,
    plot_gilt,
    plot_interpolation_forwards,
    plot_jacobian,
    plot_locality,
    plot_nss_fits,
    plot_nss_history,
    plot_pca,
    plot_pca_history,
    plot_reconciliation,
    plot_sofr_curve,
    plot_treasury_heatmap,
    plot_treasury_surface,
)
from .viz.style import PALETTE

if TYPE_CHECKING:
    from .gallery import GalleryItem

ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / "docs" / "data" / "calendar-breaks-v1.0.0.json"
VALUATION = date(2026, 9, 30)
METHODS = ("linear", "log_linear", "monotone_cubic", "monotone_convex")
PCA_LABELS = ("3M", "6M", "1Y", "2Y", "3Y", "5Y", "7Y", "10Y")
HEATMAP_LABELS = ("1M", "3M", "6M", "1Y", "2Y", "3Y", "5Y", "7Y", "10Y", "20Y", "30Y")
FORWARD_GRID = tuple(week / 52 for week in range(1, 52 * 50))


# ---------------------------------------------------------------------------- shared inputs
@lru_cache(maxsize=1)
def sofr_quotes() -> tuple[float, ...]:
    return illustrative_sofr_quotes(VALUATION)


@lru_cache(maxsize=8)
def sofr(method: str = "log_linear") -> InstrumentCurve:
    return sofr_curve(VALUATION, sofr_quotes(), interpolation=method)


def _forwards(curve: InstrumentCurve, times: tuple[float, ...] = FORWARD_GRID) -> list[float]:
    if curve.interpolation.value == "log_linear":
        # the exact staircase: the forward over each week, which is flat between pillars
        return [curve.curve.forward_rate(t, t + 1 / 365) for t in times]
    return [curve.curve.instantaneous_forward(t) for t in times]


@lru_cache(maxsize=1)
def pca_history() -> tuple[list[date], np.ndarray, CurvePCA]:
    days, yields = treasury_matrix(PCA_LABELS)
    return days, yields, curve_pca(days, yields, PCA_LABELS, [TENOR_YEARS[label] for label in PCA_LABELS])


# ---------------------------------------------------------------------------- validation
def reconciliation_chart() -> Figure:
    from .devtools.reference import monotone_convex_variant, reconciliation

    rows = [
        CheckRow(check.area, check.name, check.cases, check.max_error, check.tolerance, check.explained)
        for check in reconciliation()
    ]
    return plot_reconciliation(rows, monotone_convex_variant()["max_forward_gap_bp"])


def calendar_breaks_chart() -> Figure:
    from .devtools.reference import KNOWN_DIFFERENCES, compare_calendars, explain

    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))["calendars"]
    calendar_differences = [item for item in KNOWN_DIFFERENCES if item.area == "calendars"]
    colours = (PALETTE["teal"], PALETTE["violet"], PALETTE["accent"])
    reasons = {item.label: colour for item, colour in zip(calendar_differences, colours, strict=True)}
    sets = []
    for comparison in compare_calendars():
        before = baseline[comparison.calendar]
        old = tuple(
            sorted(
                date.fromisoformat(day) for day in before["closed_only_by_meridian"] + before["closed_only_by_quantlib"]
            )
        )
        now = []
        for day, _ in comparison.breaks():
            difference = explain("calendars", comparison.calendar, day)
            now.append((day, difference.label if difference else "unexplained"))
        sets.append(BreakSet(comparison.calendar, old, tuple(sorted(now))))
    return plot_calendar_breaks(sets, reasons)


def equinox_chart() -> Figure:
    from .devtools.reference import compare_calendars

    tokyo = next(item for item in compare_calendars() if item.calendar == "XTKS")
    disputed_days = {day for day, _ in tokyo.breaks()}
    years = list(range(1990, 2061))

    def hours(year: int, season: str) -> float:
        moment = equinox(year, season).astimezone(JST)  # type: ignore[arg-type]
        return moment.hour + moment.minute / 60

    def disputed(year: int, month: int) -> bool:
        return any(day.year == year and day.month == month for day in disputed_days)

    return plot_equinox_arbiter(
        years,
        [hours(year, "march") for year in years],
        [hours(year, "september") for year in years],
        [disputed(year, 3) for year in years],
        [disputed(year, 9) for year in years],
    )


# ---------------------------------------------------------------------------- curves from instruments
def sofr_chart() -> Figure:
    flat, convex = sofr("log_linear"), sofr("monotone_convex")
    times = list(FORWARD_GRID)
    return plot_sofr_curve(
        list(SOFR_TENORS),
        [flat.time(day) for day in flat.pillars],
        list(sofr_quotes()),
        times,
        [flat.curve.zero_rate(t) for t in times],
        _forwards(flat),
        _forwards(convex),
        [error * 1e4 for _, _, error in flat.repricing()],
        VALUATION,
    )


def interpolation_chart() -> Figure:
    curves = {method: sofr(method) for method in METHODS}
    quantlib: list[float] | None = None
    try:
        import QuantLib as ql

        from .devtools.reference import quantlib_sofr_curve

        _, helpers = quantlib_sofr_curve(VALUATION, list(sofr_quotes()))
        reference = ql.PiecewiseConvexMonotoneForward(ql.Date(30, 9, 2026), helpers, ql.Actual365Fixed())
        reference.enableExtrapolation()
        quantlib = [reference.forwardRate(t, t, ql.Continuous, ql.NoFrequency).rate() for t in FORWARD_GRID]
    except ImportError:  # pragma: no cover - QuantLib is a development dependency
        quantlib = None
    pillars = [curves["log_linear"].time(day) for day in curves["log_linear"].pillars]
    return plot_interpolation_forwards(
        list(FORWARD_GRID), {method: _forwards(curve) for method, curve in curves.items()}, pillars, quantlib
    )


def locality_chart() -> Figure:
    bumped = SOFR_TENORS.index("5Y")
    times = tuple(step / 100 for step in range(1, 4_000))
    responses = {}
    for method in METHODS:
        base = sofr(method)
        moved = base.rebuilt([q + 1e-4 * (index == bumped) for index, q in enumerate(sofr_quotes())])
        responses[method] = [
            (after - before) * 1e4
            for after, before in zip(_forwards(moved, times), _forwards(base, times), strict=True)
        ]
    base = sofr("log_linear")
    return plot_locality(list(times), responses, base.time(base.pillars[bumped]), "5-year")


def jacobian_chart() -> Figure:
    labels = list(SOFR_TENORS)
    return plot_jacobian(
        labels, {method: np.array(sofr(method).jacobian()) for method in ("log_linear", "monotone_convex")}
    )


BOOK = (
    ("receive 4.20% on $75m, 8 years", "8Y", 0.0420, 75e6),
    ("pay 4.60% on $40m, 13 years", "13Y", 0.0460, -40e6),
    ("receive 4.90% on $25m, 27 years", "27Y", 0.0490, 25e6),
    ("pay 3.90% on $120m, 42 months", "42M", 0.0390, -120e6),
)


def bucketed_dv01_chart() -> Figure:
    curve = sofr("log_linear")
    quotes = list(sofr_quotes())
    swaps: list[tuple[str, OvernightIndexSwap, float]] = [
        (name, overnight_index_swap(VALUATION, tenor, rate), notional) for name, tenor, rate, notional in BOOK
    ]
    contributions: dict[str, list[float]] = {name: [] for name, _, _ in swaps}
    hedges: list[float] = []
    for index, instrument in enumerate(curve.instruments):
        up = curve.rebuilt([q + 1e-4 * (k == index) for k, q in enumerate(quotes)])
        down = curve.rebuilt([q - 1e-4 * (k == index) for k, q in enumerate(quotes)])
        bucket = 0.0
        for name, swap, notional in swaps:
            change = (swap.value(up.discount, notional) - swap.value(down.discount, notional)) / 2
            contributions[name].append(change)
            bucket += change
        assert isinstance(instrument, OvernightIndexSwap)
        per_unit = instrument.annuity(curve.discount) * 1e-4  # receiving one dollar of the quoted swap
        hedges.append(bucket / per_unit)  # received notional that cancels the bucket, sign flipped below
    parallel = curve.rebuilt([q + 1e-4 for q in quotes])
    total = sum(swap.value(parallel.discount, n) - swap.value(curve.discount, n) for _, swap, n in swaps)
    return plot_bucketed_dv01(list(SOFR_TENORS), contributions, [-h for h in hedges], total)


# ---------------------------------------------------------------------------- 36 years of history
def _heatmap_matrix() -> tuple[list[date], np.ndarray]:
    days, rows = [], []
    for curve in treasury_par_yields():
        lookup = dict(zip(curve.labels, curve.yields, strict=True))
        days.append(curve.day)
        rows.append([lookup.get(label, np.nan) for label in HEATMAP_LABELS])
    return days, np.array(rows)


def treasury_heatmap_chart() -> Figure:
    days, matrix = _heatmap_matrix()
    return plot_treasury_heatmap(days, list(HEATMAP_LABELS), matrix)


def treasury_surface_chart() -> Figure:
    days, yields = treasury_matrix(PCA_LABELS)
    month_ends = [index for index in range(len(days) - 1) if days[index + 1].month != days[index].month] + [
        len(days) - 1
    ]
    return plot_treasury_surface(
        [days[i] for i in month_ends],
        [TENOR_YEARS[label] for label in PCA_LABELS],
        list(PCA_LABELS),
        yields[month_ends],
    )


def pca_chart() -> Figure:
    days, _, result = pca_history()
    return plot_pca(
        list(PCA_LABELS),
        result.loadings,
        list(result.explained),
        [result.volatility_bp(index) for index in range(3)],
        len(days) - 1,
    )


def pca_history_chart() -> Figure:
    days, yields, result = pca_history()
    ends, shares = rolling_explained(days, yields, PCA_LABELS, [TENOR_YEARS[label] for label in PCA_LABELS])
    return plot_pca_history(ends, shares, list(result.days), list(result.scores[:, 0]), list(result.scores[:, 1]))


def _gsw_model(day: date) -> NelsonSiegelSvensson:
    parameters, _ = gsw_curve()
    item = next(p for p in reversed(parameters) if p.day <= day)
    return NelsonSiegelSvensson.from_gsw(item.beta0, item.beta1, item.beta2, item.beta3, item.tau1, item.tau2)


FIT_DAYS = (
    (date(2000, 5, 19), "inverted before the 2001 recession"),
    (date(2008, 12, 31), "after Lehman: the short end at zero"),
    (date(2019, 8, 28), "the 2019 inversion"),
    (date(2026, 9, 25), "the latest Federal Reserve curve"),
)


def nss_fits_chart() -> Figure:
    panels = []
    grid = tuple(float(x) for x in np.geomspace(0.08, 30, 160))
    for day, note in FIT_DAYS:
        curve = par_curve_on(day)
        zeros = bootstrap_par_curve(day, curve.tenors, curve.yields, interpolation="monotone_convex")
        starting = [zeros.zero_rate(t) for t in curve.tenors]
        svensson = fit_par_curve(curve.tenors, curve.yields, starting_zeros=starting)
        nelson_siegel = fit_par_curve(curve.tenors, curve.yields, svensson=False, starting_zeros=starting)
        panels.append(
            FitPanel(
                curve.day,
                curve.tenors,
                curve.yields,
                grid,
                tuple(float(v) for v in svensson.model.par_yields(grid)),
                tuple(float(v) for v in nelson_siegel.model.par_yields(grid)),
                tuple(float(v) for v in _gsw_model(day).par_yields(grid)),
                svensson.rmse_bp,
                nelson_siegel.rmse_bp,
                note,
            )
        )
    return plot_nss_fits(panels)


@lru_cache(maxsize=1)
def quarterly_fits() -> tuple[list[date], dict[str, list[float]], list[float]]:
    """A Svensson fit at every quarter end since 1990, each started from the one before."""
    parameters, _ = gsw_curve()
    gsw_days = {item.day for item in parameters}
    curves = [curve for curve in treasury_par_yields() if curve.day in gsw_days and len(curve) >= 7]
    quarter_ends = [
        curve for curve, following in zip(curves, [*curves[1:], None], strict=True)
        if following is None or (following.day.month - 1) // 3 != (curve.day.month - 1) // 3
    ]  # fmt: skip
    days: list[date] = []
    gaps: dict[str, list[float]] = {"2-year": [], "10-year": [], "30-year": []}
    rmse: list[float] = []
    previous: NelsonSiegelSvensson | None = None
    for curve in quarter_ends:
        fit = fit_par_curve(curve.tenors, curve.yields, initial=previous)
        if previous is not None and fit.rmse_bp > 8:  # a regime change: search the grid again
            fit = fit_par_curve(curve.tenors, curve.yields)
        previous = fit.model
        theirs = _gsw_model(curve.day)
        difference = (fit.model.zero_rates([2, 10, 30]) - theirs.zero_rates([2, 10, 30])) * 1e4
        if max(curve.tenors) < 30:  # no 30-year published (2002-2006): the fit would only be extrapolating
            difference[2] = np.nan
        days.append(curve.day)
        for key, value in zip(gaps, difference, strict=True):
            gaps[key].append(float(value))
        rmse.append(fit.rmse_bp)
    return days, gaps, rmse


def nss_history_chart() -> Figure:
    days, gaps, rmse = quarterly_fits()
    parameters, published = gsw_curve()
    worst = 0.0
    for item, row in zip(parameters, published, strict=True):
        fitted = NelsonSiegelSvensson.from_gsw(item.beta0, item.beta1, item.beta2, item.beta3, item.tau1, item.tau2)
        finite = np.isfinite(row)
        if finite.any():
            worst = max(worst, float(np.max(np.abs(fitted.zero_rates(GSW_TENORS)[finite] * 100 - row[finite]))))
    return plot_nss_history(days, gaps, rmse, worst * 100)


# ---------------------------------------------------------------------------- gilts
def gilt_chart() -> Figure:
    gilt = FixedRateBond.gilt(issue_date=date(2023, 1, 31), maturity=date(2034, 7, 31), coupon_rate=0.04625)
    from .core.calendars import get_calendar

    london = get_calendar("XLON")
    days = list(london.business_days(date(2025, 10, 1), date(2026, 9, 30)))
    accrued = [gilt.accrued_interest(day) for day in days]
    clean = [gilt.clean_price_from_yield(0.045, day) for day in days]
    dirty = [gilt.dirty_price_from_yield(0.045, day) for day in days]
    windows = []
    for period in gilt.schedule.periods:
        ex = gilt.ex_dividend_date(period)
        if ex and days[0] <= period.end <= days[-1] + timedelta(days=40):
            windows.append((ex, period.end))
    return plot_gilt(days, accrued, clean, dirty, windows, "4 5/8% Treasury Gilt 2034")


# ---------------------------------------------------------------------------- the gallery
def rates_engine_items() -> tuple[GalleryItem, ...]:
    from .gallery import GalleryItem

    def item(filename: str, title: str, description: str, builder, group: str) -> GalleryItem:  # type: ignore[no-untyped-def]
        return GalleryItem(filename, title, description, builder, group)

    return (
        item("quantlib-reconciliation.png", "Meridian against QuantLib",
             "Every check of the rates engine against the reference library, with its tolerance.",
             reconciliation_chart, "validation"),
        item("calendar-breaks.png", "What QuantLib found in the calendars",
             "Every weekday 1990-2060 the two disagreed, before and after the calendars learnt history.",
             calendar_breaks_chart, "validation"),
        item("equinox-arbiter.png", "The astronomy decides",
             "The time of Japan's equinoxes, and the years QuantLib's formula names the wrong day.",
             equinox_chart, "validation"),
        item("sofr-curve.png", "A SOFR curve from twenty swaps",
             "Zero and forward curves bootstrapped from dated OIS instruments, each repriced exactly.",
             sofr_chart, "rates"),
        item("interpolation-forwards.png", "Four interpolators, one set of quotes",
             "What linear, log-linear, monotone cubic and monotone convex say about forwards.",
             interpolation_chart, "rates"),
        item("interpolation-locality.png", "Locality",
             "How far a one basis point bump in the 5-year quote travels along the forward curve.",
             locality_chart, "rates"),
        item("curve-jacobian.png", "The Jacobian",
             "How each quote moves each point of the zero curve, local and non-local.",
             jacobian_chart, "rates"),
        item("bucketed-dv01.png", "Bucketed DV01 and its hedge",
             "A swap book's risk in the quoted instruments, and the swaps that flatten it.",
             bucketed_dv01_chart, "rates"),
        item("treasury-history.png", "The Treasury curve since 1990",
             "Every published par curve, 1990-2026, with the events that moved it.",
             treasury_heatmap_chart, "rates"),
        item("treasury-surface.png", "The yield curve as a landscape",
             "Month-end par yields since 1990 as a surface.",
             treasury_surface_chart, "rates"),
        item("curve-pca.png", "Level, slope and curvature",
             "Principal components of 36 years of daily Treasury curve changes.",
             pca_chart, "rates"),
        item("curve-pca-history.png", "The factors through time",
             "Rolling variance explained, and the cumulative level and slope factors.",
             pca_history_chart, "rates"),
        item("nss-fits.png", "Nelson-Siegel and Svensson on real curves",
             "Four days of the Treasury curve, fitted, beside the Federal Reserve's own fit.",
             nss_fits_chart, "rates"),
        item("nss-vs-gsw.png", "Our fit against the Fed's, since 1990",
             "Quarterly Svensson fits to the Treasury curve minus GSW, and how well six numbers fit.",
             nss_history_chart, "rates"),
        item("gilt-ex-dividend.png", "A gilt goes ex-dividend",
             "Negative accrued interest and the cum-to-ex drop, priced by the DMO's formula.",
             gilt_chart, "cashflows"),
    )  # fmt: skip
