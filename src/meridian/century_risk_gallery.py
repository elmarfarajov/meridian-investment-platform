"""The Day 5 revisit charts: risk against its references and on a century of daily US returns.

The real-data charts draw from :mod:`meridian.services.century_risk` and the reference
chart from :mod:`meridian.devtools.risk_reference`, the same functions the tests check.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import numpy as np
from matplotlib.figure import Figure
from scipy import stats

from .devtools.risk_reference import BASEL_TABLE, reconciliation
from .marketdata.french import INDUSTRY_NAMES
from .risk.exposures import standardise, standardise_against
from .risk.validation import confidence_band, cumulative_probability, traffic_light
from .risk.var import TAIL_DOF, monte_carlo
from .services import century_risk as century
from .viz.century_risk import (
    CrisisPanel,
    ReferenceGap,
    ReviewPanel,
    Surprise,
    plot_bias_heatmap,
    plot_crises,
    plot_forecast_losses,
    plot_minimum_variance,
    plot_references,
    plot_review,
    plot_surprises,
    plot_zone_heatmap,
)

if TYPE_CHECKING:
    from .gallery import GalleryItem

#: Days whose cause is documented; other large losses are left unnamed rather than guessed at.
EVENTS = {
    date(1955, 9, 26): "Eisenhower's heart attack",
    date(1987, 10, 19): "Black Monday",
    date(1989, 10, 13): "the Friday the 13th mini-crash",
    date(1962, 5, 28): "the Kennedy Slide",
    date(1997, 10, 27): "the Asian crisis mini-crash",
    date(2020, 3, 16): "COVID-19",
    date(2020, 3, 12): "COVID-19",
    date(2001, 9, 17): "markets reopen after 9/11",
}
CRISES = (
    ("September 1955: a president's heart attack", date(1955, 8, 1), date(1955, 12, 31)),
    ("October 1987: Black Monday", date(1987, 8, 1), date(1987, 12, 31)),
    ("2008: the financial crisis", date(2008, 8, 1), date(2009, 3, 31)),
    ("2020: the pandemic", date(2020, 1, 15), date(2020, 6, 30)),
)


def references_chart() -> Figure:
    counts = list(BASEL_TABLE)
    gaps = [
        ReferenceGap(check.reference, check.subject, check.difference, bool(check.convention))
        for check in reconciliation()
        if check.reference != "Basel Committee (1996)"
    ]
    return plot_references(
        counts,
        [cumulative_probability(count) for count in counts],
        [BASEL_TABLE[count][2] for count in counts],
        [traffic_light(count).zone for count in counts],
        gaps,
    )


def zones_chart() -> Figure:
    results = century.var_backtest()
    lights = [result.by_year() for result in results]
    years = sorted(lights[0])
    zones = [[by_year[year].zone for year in years] for by_year in lights]
    totals = [(result.rate, *result.zone_counts().values()) for result in results]
    return plot_zone_heatmap([result.method for result in results], years, zones, totals)  # type: ignore[arg-type]


def crises_chart() -> Figure:
    results = century.var_backtest()
    days = np.array([day.toordinal() for day in results[0].days])
    panels = []
    for title, start, end in CRISES:
        chosen = (days >= start.toordinal()) & (days <= end.toordinal())
        panels.append(
            CrisisPanel(
                title,
                tuple(day for day, keep in zip(results[0].days, chosen, strict=True) if keep),
                results[0].returns[chosen],
                {result.method: result.var[chosen] for result in results},
            )
        )
    return plot_crises(panels)


def surprises_chart() -> Figure:
    normal = century.var_backtest()[0]
    surprises = [Surprise(day, -loss, multiple, EVENTS.get(day, "")) for day, loss, multiple in normal.worst(12)]
    return plot_surprises(surprises, normal.method)


def bias_chart() -> Figure:
    rows = century.bias_by_decade()
    series = list(dict.fromkeys(row.series for row in rows))
    decades = sorted({row.decade for row in rows})
    grid = np.full((len(series), len(decades)), np.nan)
    for row in rows:
        grid[series.index(row.series), decades.index(row.decade)] = row.bias
    _, high = confidence_band(2500)
    return plot_bias_heatmap(series, decades, grid, high - 1.0, {"Market": "US market", **INDUSTRY_NAMES})


def losses_chart() -> Figure:
    fits = century.garch_fits()
    return plot_forecast_losses(
        century.forecast_losses(),
        [day for day, *_ in fits],
        [alpha + beta for _, alpha, beta, _ in fits],
        [dof for *_, dof in fits],
    )


def minimum_variance_chart() -> Figure:
    trials = century.minimum_variance_trials()
    days = sorted({trial.day for trial in trials})
    delivered = {name: [trial.delivered for trial in trials if trial.estimator == name] for name in century.ESTIMATORS}
    return plot_minimum_variance(century.covariance_summary(), days, delivered)


def review_chart() -> Figure:
    # 1. the Monte Carlo specific tail: one t(5) draw for the book against one per holding (fifty holdings)
    count, sigma = 50, 0.01
    scale = np.sqrt((TAIL_DOF - 2) / TAIL_DOF)
    old_quantile = float(stats.t.ppf(0.99, TAIL_DOF)) * scale  # in units of the specific volatility
    estimate, _ = monte_carlo(
        np.zeros((count, 1)), np.zeros((1, 1)), np.full(count, sigma**2), np.full(count, 1 / count), draws=400_000
    )
    new_quantile = estimate.var / (sigma / np.sqrt(count))
    # 2. the first yellow count for windows of 100, 250 and 500 days
    windows = (100, 250, 500)
    old_yellow = (5.0, 5.0, 5.0)  # the 250-day table, whatever the window
    new_yellow = tuple(float(next(n for n in range(w) if traffic_light(n, w).zone != "green")) for w in windows)
    # 3. a stock outside the estimation universe with a universe stock's descriptor
    rng = np.random.default_rng(4)
    values, caps = rng.normal(0, 1, 300), rng.lognormal(3, 1, 300)
    values[:4] = [4.5, 5.0, 5.5, -4.8]  # a few outliers, as a descriptor has
    inside = standardise(values, caps)
    picks = [int(np.argmax(values)), int(np.argsort(values)[150]), int(np.argmin(values))]
    weights = caps / caps.sum()
    centre = float(weights @ values)
    old_scale = float((values - centre).std())
    old = tuple(float(np.clip((values[i] - centre) / old_scale, -3, 3)) for i in picks)
    new = tuple(float(standardise_against(np.array([values[i]]), values, caps)[0]) for i in picks)
    assert np.allclose(new, inside[picks])  # the point of the fix: the universe stock's own exposure
    panels = [
        ReviewPanel(
            "Monte Carlo: 99% specific VaR of fifty holdings (in sigma)",
            ("specific VaR",),
            (old_quantile,),
            (float(new_quantile),),
            ".3f",
            "One Student-t draw for the whole book kept a single stock's fat tail; fifty independent draws "
            "summed are nearly normal, as diversified specific risk is (2.33 for a normal).",
        ),
        ReviewPanel(
            "Basel: the first yellow count, by window length",
            tuple(f"{w} days" for w in windows),
            old_yellow,
            new_yellow,
            ".0f",
            "The 250-day table was applied to any window. The Committee's own rule, the binomial probability, "
            f"gives {new_yellow[0]:.0f} for 100 days and {new_yellow[2]:.0f} for 500, and the same "
            f"{new_yellow[1]:.0f} for 250.",
        ),
        ReviewPanel(
            "An off-universe stock's exposure, same descriptor",
            ("largest", "median", "smallest"),
            old,
            new,
            ".3f",
            "standardise_against skipped the re-centring and rescaling after winsorising; it now gives "
            "exactly the exposure of the universe stock with the same descriptor.",
        ),
    ]
    return plot_review(panels)


def century_risk_items() -> tuple[GalleryItem, ...]:
    from .gallery import GalleryItem

    return (
        GalleryItem(
            "risk-references.png",
            "Day 5 against its references",
            "The Basel traffic-light table reproduced, and arch, pandas, scikit-learn and PyPortfolioOpt.",
            references_chart,
            "validation",
        ),
        GalleryItem(
            "var-century-zones.png",
            "Ninety-seven years of 99% VaR",
            "Four forecasters scored year by year in Basel's traffic-light zones.",
            zones_chart,
            "risk",
        ),
        GalleryItem(
            "var-crises.png",
            "Four crises, four forecasters",
            "Daily returns against each method's VaR through 1955, 1987, 2008 and 2020.",
            crises_chart,
            "risk",
        ),
        GalleryItem(
            "var-surprises.png",
            "The worst surprises in a century",
            "Losses in units of that morning's VaR forecast.",
            surprises_chart,
            "risk",
        ),
        GalleryItem(
            "bias-by-decade.png",
            "Is the risk forecast the right size?",
            "The bias statistic of the RiskMetrics forecast for the market and twelve industries, by decade.",
            bias_chart,
            "risk",
        ),
        GalleryItem(
            "garch-vs-ewma.png",
            "GARCH against EWMA on a century of returns",
            "QLIKE by decade, and the GARCH parameters refitted every year.",
            losses_chart,
            "risk",
        ),
        GalleryItem(
            "industry-minimum-variance.png",
            "Twelve industries, four covariance estimators",
            "Minimum-variance portfolios since 1927: risk promised against risk delivered.",
            minimum_variance_chart,
            "risk",
        ),
        GalleryItem(
            "risk-review.png",
            "A second reading of Day 5",
            "Three faults, each figure before and after the fix.",
            review_chart,
            "risk",
        ),
    )
