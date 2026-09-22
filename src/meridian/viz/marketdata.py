"""Charts for market data: adjustment, point-in-time history, consensus pricing and FX.

Each makes one argument that is easy to state and easy to forget:

* a split is not a crash, and a dividend is not a loss;
* a history can be restated, and a backtest run on the restated version knew
  things nobody knew at the time;
* no single vendor is right every day, and the consensus is measurably closer
  to the truth than any of them;
* FX rates are not independent numbers - the triangle must close;
* market returns have fat tails, which is what every statistical check has to
  be robust to.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import date
from decimal import Decimal

import matplotlib.dates as mdates
import numpy as np
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.lines import Line2D

from ..core.currency import USD
from ..domain.corporate_actions import AdjustmentMode, CashDividend, CorporateAction, SpinOff, StockSplit
from ..domain.entitlements import apply_action
from ..domain.positions import TaxLot
from ..marketdata.adjustments import adjust_history
from ..marketdata.bitemporal import BitemporalStore
from ..marketdata.fx_history import FxHistory
from ..marketdata.golden import GoldenCopy
from ..marketdata.quotes import MarketDataset
from ..marketdata.series import TimeSeries
from .style import PALETTE, annotate, caption, new_figure, style_axes, title_block, x_of


def _margins(
    figure: Figure, *, top: float = 1.2, bottom: float = 0.7, left: float = 0.07, right: float = 0.975
) -> dict:
    height = figure.get_figheight()
    return {"top": 1 - top / height, "bottom": bottom / height, "left": left, "right": right}


# ---------------------------------------------------------------------------- corporate action adjustment
def plot_split_adjustment(
    raw: TimeSeries,
    actions: Sequence[CorporateAction],
    economic: TimeSeries | None = None,
    *,
    instrument_id: str,
) -> Figure:
    """Raw, capital-adjusted and total-return-adjusted histories, and the truth where it is known."""
    capital = adjust_history(raw, actions, AdjustmentMode.CAPITAL, instrument_id=instrument_id)
    total = adjust_history(raw, actions, AdjustmentMode.TOTAL_RETURN, instrument_id=instrument_id)
    own = [action for action in actions if action.instrument_id == instrument_id and action.ex_date > raw.first.day]
    splits = [action for action in own if isinstance(action, StockSplit)]
    dividends = [action for action in own if isinstance(action, CashDividend)]

    figure = new_figure(14.0, 5.8)
    grid = figure.add_gridspec(1, 2, width_ratios=[1.15, 1.0], wspace=0.2, **_margins(figure, bottom=0.8))
    price_axis = figure.add_subplot(grid[0])
    price_axis.plot(raw.days, raw.floats(), color=PALETTE["loss"], linewidth=1.4, label="Quoted (raw)")
    price_axis.plot(
        capital.days, capital.floats(), color=PALETTE["teal"], linewidth=1.4, label="Adjusted for capital events"
    )
    price_axis.plot(total.days, total.floats(), color=PALETTE["navy"], linewidth=1.8, label="Adjusted for total return")
    for event in splits:
        price_axis.axvline(x_of(event.ex_date), color=PALETTE["ink"], linewidth=0.8, linestyle="--")
        cum = raw.as_of(event.ex_date)
        annotate(
            price_axis,
            f"{event.numerator}-for-{event.denominator} split",
            (x_of(event.ex_date), float(cum.value) if cum else float(raw.last.value)),
            highlight=True,
            xytext=(8, 40),
            textcoords="offset points",
            arrowprops={"arrowstyle": "-", "color": PALETTE["accent"]},
        )
    for payout in dividends:
        price_axis.axvline(x_of(payout.ex_date), color=PALETTE["grid"], linewidth=0.8, zorder=0)
    style_axes(price_axis, title="The same share, three ways", ylabel="Price")
    price_axis.legend(loc="upper right")

    index_axis = figure.add_subplot(grid[1])
    for series, label, colour, width in (
        (raw, "Raw price: looks like a -80% collapse", PALETTE["loss"], 1.4),
        (capital, "Price return", PALETTE["teal"], 1.4),
        (total, "Total return", PALETTE["navy"], 1.8),
    ):
        points = series.cumulative_index()
        index_axis.plot(
            [day for day, _ in points], [value for _, value in points], color=colour, linewidth=width, label=label
        )
    if economic is not None:
        truth = economic.cumulative_index()
        index_axis.plot(
            [day for day, _ in truth],
            [value for _, value in truth],
            color=PALETTE["accent"],
            linestyle=":",
            linewidth=2.0,
            label="Economic value (the generator's truth)",
        )
    index_axis.axhline(100, color=PALETTE["ink"], linewidth=0.6)
    style_axes(index_axis, title="Growth of 100", ylabel="Index")
    index_axis.legend(loc="lower left")
    if economic is not None:
        left, right = total.align(economic)
        ours = np.array(left.floats()) / float(left.last.value)
        theirs = np.array(right.floats()) / float(right.last.value)
        worst = float(np.max(np.abs(ours / theirs - 1))) * 10_000
        annotate(
            index_axis,
            f"total return tracks the truth to {worst:.1f} bp",
            (0.98, 0.82),
            xycoords="axes fraction",
            ha="right",
            highlight=True,
        )

    title_block(
        figure,
        "A split is not a crash",
        f"{instrument_id}: {len(splits)} split(s) and {len(dividends)} dividends. Prices before each ex-date are "
        "multiplied by the event's factor, so the adjusted series ends at the price on the screen today.",
    )
    caption(
        figure,
        "CRSP convention: split factor = old/new shares; dividend factor = (P - D) / P with P the last cum-dividend "
        "close. Adjustment is a view derived on demand - the raw record is never overwritten (ADR 0011).",
    )
    return figure


def plot_lot_adjustments(
    lots: Sequence[TaxLot],
    split_event: StockSplit,
    spin_off: SpinOff,
    dividend_event: CashDividend,
    *,
    portfolio_id: str = "DEMO",
) -> Figure:
    """What three corporate actions do to one holding's tax lots and cash."""
    split_result = apply_action(split_event, lots, portfolio_id=portfolio_id)
    spin_result = apply_action(spin_off, split_result.lots_after, portfolio_id=portfolio_id)
    dividend_result = apply_action(dividend_event, spin_result.lots_after, portfolio_id=portfolio_id)

    figure = new_figure(15.0, 6.2)
    grid = figure.add_gridspec(1, 3, wspace=0.32, **_margins(figure, bottom=1.0))
    lot_colours = [PALETTE["navy"], PALETTE["sky"], PALETTE["slate"], PALETTE["violet"]]

    def stacked(axis: Axes, groups: list[tuple[str, list[TaxLot]]], child: str | None = None) -> None:
        tallest = max(float(sum(lot.cost_basis.amount for lot in group)) for _, group in groups)
        for position, (_label, group) in enumerate(groups):
            bottom = 0.0
            for index, lot in enumerate(
                sorted(group, key=lambda item: (item.instrument_id != split_event.instrument_id, item.lot_id))
            ):
                basis = float(lot.cost_basis.amount)
                is_child = child is not None and lot.instrument_id == child
                colour = PALETTE["teal"] if is_child else lot_colours[index % len(lot_colours)]
                axis.bar(position, basis, bottom=bottom, color=colour, width=0.58, edgecolor="white", linewidth=0.8)
                text = f"{lot.lot_id}  {lot.quantity.normalize():,f} @ {float(lot.cost_per_unit):,.2f}"
                if basis / tallest >= 0.09:
                    axis.text(
                        position,
                        bottom + basis / 2,
                        text.replace("  ", "\n", 1),
                        ha="center",
                        va="center",
                        fontsize=7,
                        color="white",
                    )
                else:  # too thin to label inside: label beside the bar instead
                    axis.text(
                        position + 0.32, bottom + basis / 2, text, va="center", fontsize=6.8, color=PALETTE["ink"]
                    )
                bottom += basis
            axis.text(position, bottom * 1.01, f"{bottom:,.0f}", ha="center", va="bottom", fontsize=8.5, weight="bold")
        axis.set_xticks(range(len(groups)), labels=[label for label, _ in groups])

    split_axis = figure.add_subplot(grid[0])
    stacked(split_axis, [("Before", list(split_result.lots_before)), ("After", list(split_result.lots_after))])
    style_axes(split_axis, title=f"{split_event.numerator}-for-1 split: basis conserved", ylabel="Cost basis")

    spin_axis = figure.add_subplot(grid[1])
    stacked(
        spin_axis,
        [("Before", list(spin_result.lots_before)), ("After", list(spin_result.lots_after))],
        child=spin_off.child_instrument_id,
    )
    style_axes(spin_axis, title=f"Spin-off: {float(spin_off.child_fraction()):.1%} of basis to the child")
    spin_axis.legend(
        handles=[
            Line2D([], [], color=PALETTE["navy"], linewidth=8, label=f"{split_event.instrument_id} lots"),
            Line2D(
                [], [], color=PALETTE["teal"], linewidth=8, label=f"{spin_off.child_instrument_id} lots (dates kept)"
            ),
        ],
        loc="upper center",
        bbox_to_anchor=(0.5, -0.08),
        ncol=2,
    )

    cash_axis = figure.add_subplot(grid[2])
    (cash,) = dividend_result.cash
    gross, tax, net = float(cash.gross.amount), float(cash.tax_withheld.amount), float(cash.net.amount)
    cash_axis.bar(0, gross, color=PALETTE["gain"], width=0.55)
    cash_axis.bar(1, -tax, bottom=gross, color=PALETTE["loss"], width=0.55)
    cash_axis.bar(2, net, color=PALETTE["navy"], width=0.55)
    for position, height, label in ((0, gross, f"{gross:,.2f}"), (1, gross, f"-{tax:,.2f}"), (2, net, f"{net:,.2f}")):
        cash_axis.text(position, height * 1.01, label, ha="center", va="bottom", fontsize=8.5, weight="bold")
    cash_axis.set_ylim(0, gross * 1.18)
    cash_axis.set_xticks([0, 1, 2], labels=["Gross", "Withheld", "Net cash"])
    shares = dividend_result.quantity_after()
    style_axes(
        cash_axis,
        title=f"Dividend on {shares.normalize():,f} shares, paid {cash.pay_date:%d %b}",
        ylabel=cash.gross.currency.code,
    )

    title_block(
        figure,
        "Corporate actions on tax lots",
        "Splits change the count and the cost per share, never the total; a spin-off divides the basis by the issuer's "
        "published allocation and the child inherits the acquisition dates; income arrives net of tax withheld.",
    )
    caption(
        figure,
        "Only lots opened before the ex-date take part. Basis after = basis before to the cent in both capital events; "
        "the holding period tacks, so a long-term lot stays long-term through the split and into the child.",
    )
    return figure


# ---------------------------------------------------------------------------- point in time
def plot_point_in_time(store: BitemporalStore, key: str) -> Figure:
    """First prints against restated values, and how big and how late the corrections were."""
    first = store.first_published(key)
    final = store.as_known_at(key)
    revisions = store.revisions(key)

    figure = new_figure(14.0, 7.6)
    grid = figure.add_gridspec(
        2,
        2,
        height_ratios=[1.5, 1.0],
        width_ratios=[1.6, 1.0],
        hspace=0.38,
        wspace=0.18,
        **_margins(figure, bottom=0.75),
    )
    series_axis = figure.add_subplot(grid[0, :])
    series_axis.plot(
        final.days, final.floats(), color=PALETTE["navy"], linewidth=1.8, label="As known today (restated)"
    )
    series_axis.plot(
        first.days, first.floats(), color=PALETTE["slate"], linewidth=0.9, linestyle="--", label="As first published"
    )
    for revision in revisions:
        series_axis.plot(
            [revision.value_date, revision.value_date],
            [float(revision.first_value), float(revision.final_value)],
            color=PALETTE["loss"],
            linewidth=1.6,
        )
        series_axis.scatter([revision.value_date], [float(revision.first_value)], color=PALETTE["loss"], s=26, zorder=5)
    style_axes(series_axis, title=f"{key}: the series a live system saw, and the one it became", ylabel="Close")
    series_axis.legend(
        handles=[
            Line2D([], [], color=PALETTE["navy"], linewidth=1.8, label="As known today (restated)"),
            Line2D([], [], color=PALETTE["slate"], linestyle="--", label="As first published"),
            Line2D([], [], color=PALETTE["loss"], marker="o", label="Wrong first print, later corrected"),
        ],
        loc="upper left",
    )

    size_axis = figure.add_subplot(grid[1, 0])
    colours = {1: PALETTE["sky"], 2: PALETTE["violet"], 3: PALETTE["loss"]}
    for revision in revisions:
        size_axis.bar(
            revision.value_date,
            revision.change_bps,
            width=2.2,
            color=colours.get(revision.delay_days, PALETTE["loss"]),
        )
    size_axis.axhline(0, color=PALETTE["ink"], linewidth=0.6)
    style_axes(size_axis, title="Each correction: restated minus first print", ylabel="Basis points")
    size_axis.legend(
        handles=[
            Line2D([], [], color=colour, linewidth=6, label=f"corrected after {days} day(s)")
            for days, colour in colours.items()
        ],
        loc="upper center",
        bbox_to_anchor=(0.5, -0.14),
        ncol=3,
    )

    lag_axis = figure.add_subplot(grid[1, 1])
    moments = store.knowledge_times(key)
    known_counts = [len(store.as_known_at(key, moment)) for moment in moments]
    lag_axis.step([moment.date() for moment in moments], known_counts, where="post", color=PALETTE["teal"])
    style_axes(lag_axis, title="Dates known, by knowledge time", ylabel="Dates in the series")
    for axis in (series_axis, size_axis, lag_axis):
        locator = mdates.AutoDateLocator(maxticks=7)
        axis.xaxis.set_major_locator(locator)
        axis.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))

    worst = max(revisions, key=lambda item: abs(item.change_bps)) if revisions else None
    detail = f"; the largest moved the price {worst.change_bps:+,.0f} bp" if worst else ""
    title_block(
        figure,
        "What we knew, and when",
        f"{len(revisions)} values were corrected after first publication{detail}. Each correction is a new record "
        "with a later knowledge time, so the series as it stood on any past evening can be rebuilt exactly.",
    )
    caption(
        figure,
        "A backtest run on today's restated history uses the blue line; a strategy trading live saw the grey one. "
        "The gap between them is look-ahead the backtest was not entitled to (ADR 0009).",
    )
    return figure


# ---------------------------------------------------------------------------- consensus pricing
def plot_vendor_consensus(
    vendors: MarketDataset,
    golden: GoldenCopy,
    errors: Mapping[str, Sequence[float]],
    instrument_id: str,
    *,
    tolerance_bps: float = 25.0,
    days: int = 130,
) -> Figure:
    """Each vendor's distance from the published price, and every source's error against the truth."""
    published = golden.series(instrument_id)
    window = published.days[-days:]
    challenged = {price.day for price in golden.challenges() if price.instrument_id == instrument_id}

    figure = new_figure(14.5, 6.2)
    grid = figure.add_gridspec(1, 2, width_ratios=[1.6, 1.0], wspace=0.22, **_margins(figure, bottom=0.85))
    gap_axis = figure.add_subplot(grid[0])
    colours = {"exchange": PALETTE["navy"], "vendor-b": PALETTE["teal"], "evaluated": PALETTE["violet"]}
    for source in sorted({quote.source for quote in vendors.for_instrument(instrument_id)}):
        series = vendors.close_series(instrument_id, source=source)
        points = [
            (day, float(series[day] / published[day] - 1) * 10_000)
            for day in window
            if day in series and day in published
        ]
        gap_axis.plot(
            [day for day, _ in points],
            [max(-150.0, min(150.0, value)) for _, value in points],
            color=colours.get(source, PALETTE["slate"]),
            linewidth=1.0,
            marker="o",
            markersize=2.2,
            label=source,
        )
    gap_axis.axhspan(-tolerance_bps, tolerance_bps, color=PALETTE["band"], zorder=0)
    for day in challenged:
        if day in window:
            gap_axis.axvline(x_of(day), color=PALETTE["grid"], linewidth=0.7, zorder=0)
    gap_axis.axhline(0, color=PALETTE["ink"], linewidth=0.7)
    style_axes(
        gap_axis,
        title=f"{instrument_id}: each vendor against the published price (clipped at +/-150 bp)",
        ylabel="Basis points",
    )
    gap_axis.legend(loc="lower left", ncol=3)
    annotate(
        gap_axis,
        f"tolerance +/-{tolerance_bps:g} bp; grey lines mark price challenges",
        (0.01, 0.95),
        xycoords="axes fraction",
    )

    error_axis = figure.add_subplot(grid[1])
    order = ["golden", "exchange", "vendor-b", "evaluated"]
    names = [name for name in order if name in errors]
    mean = [float(np.mean(np.abs(errors[name]))) for name in names]
    p99 = [float(np.percentile(np.abs(errors[name]), 99)) for name in names]
    worst = [float(np.max(np.abs(errors[name]))) for name in names]
    positions = np.arange(len(names))
    width = 0.26
    error_axis.bar(positions - width, mean, width=width, color=PALETTE["sky"], label="Mean")
    error_axis.bar(positions, p99, width=width, color=PALETTE["slate"], label="99th percentile")
    error_axis.bar(positions + width, worst, width=width, color=PALETTE["loss"], label="Worst day")
    error_axis.set_yscale("log")
    error_axis.set_xticks(positions, labels=[name.replace("golden", "golden copy") for name in names])
    for position, value in zip(positions, mean, strict=True):
        error_axis.text(
            position - width, value * 1.15, f"{value:.1f}", ha="center", fontsize=7.5, color=PALETTE["muted"]
        )
    style_axes(error_axis, title="Absolute error against the truth", ylabel="Basis points (log scale)")
    error_axis.legend(loc="upper left", fontsize=7.5)

    share = golden.source_share()
    title_block(
        figure,
        "Three vendors, one price",
        f"The golden copy takes the highest-ranked source within {tolerance_bps:g} bp of the consensus. "
        f"{len(golden):,} prices published, {len(golden.challenges()):,} challenged; "
        + ", ".join(f"{name} supplied {count:,}" for name, count in share.items())
        + ".",
    )
    caption(
        figure,
        "Errors are measured against the synthetic truth, which a real desk never has - that is the point of the "
        "simulation. The exchange feed carries the planted faults; the other vendors carry noise, staleness and gaps.",
    )
    return figure


# ---------------------------------------------------------------------------- FX
def plot_fx_triangle(
    residuals: Mapping[str, Sequence[tuple[date, float]]],
    fx: FxHistory,
    on: date,
    *,
    tolerance_bps: float = 2.0,
    currencies: Sequence[str] = ("USD", "EUR", "GBP", "CHF", "JPY"),
) -> Figure:
    """Cross rates against their legs over time, and the full cross matrix on one day."""
    figure = new_figure(15.0, 6.0)
    grid = figure.add_gridspec(1, 2, width_ratios=[1.55, 1.0], wspace=0.2, **_margins(figure, bottom=0.8))
    gap_axis = figure.add_subplot(grid[0])
    colours = [PALETTE["navy"], PALETTE["teal"], PALETTE["violet"], PALETTE["sky"]]
    worst: tuple[str, date, float] | None = None
    for index, (cross, gaps) in enumerate(sorted(residuals.items())):
        gap_axis.plot(
            [day for day, _ in gaps], [value for _, value in gaps], color=colours[index % 4], linewidth=0.9, label=cross
        )
        for day, value in gaps:
            if worst is None or abs(value) > abs(worst[2]):
                worst = (cross, day, value)
    gap_axis.axhspan(-tolerance_bps, tolerance_bps, color=PALETTE["band"], zorder=0)
    gap_axis.axhline(0, color=PALETTE["ink"], linewidth=0.6)
    if worst is not None and abs(worst[2]) > tolerance_bps:
        annotate(
            gap_axis,
            f"{worst[0]} {worst[2]:+.0f} bp from its legs on {worst[1]:%d %b %Y}",
            (x_of(worst[1]), worst[2]),
            highlight=True,
            xytext=(12, -12),
            textcoords="offset points",
        )
    style_axes(gap_axis, title="Quoted cross against the cross implied by its two USD legs", ylabel="Basis points")
    gap_axis.legend(loc="upper left", ncol=3)

    matrix_axis = figure.add_subplot(grid[1])
    matrix = fx.cross_matrix(on, currencies)
    values = np.array([[math.log10(value) if value else np.nan for value in row] for row in matrix])
    matrix_axis.imshow(values, cmap="RdBu_r", vmin=-2.5, vmax=2.5)
    for row in range(len(currencies)):
        for column in range(len(currencies)):
            cell = matrix[row][column]
            if cell is None:
                continue
            text = "1" if row == column else (f"{cell:,.2f}" if cell >= 10 else f"{cell:.4f}")
            shade = abs(values[row][column]) > 1.2
            matrix_axis.text(
                column, row, text, ha="center", va="center", fontsize=7.5, color="white" if shade else PALETTE["ink"]
            )
    matrix_axis.set_xticks(range(len(currencies)), labels=currencies)
    matrix_axis.set_yticks(range(len(currencies)), labels=currencies)
    matrix_axis.xaxis.tick_top()
    matrix_axis.tick_params(length=0)
    matrix_axis.grid(visible=False)
    for spine in matrix_axis.spines.values():
        spine.set_visible(False)
    matrix_axis.set_title(f"Units of column currency per row currency, {on:%d %b %Y}", pad=24)

    title_block(
        figure,
        "The triangle must close",
        "EURGBP has to equal EURUSD / GBPUSD, or there is money in going round the triangle. In end-of-day reference "
        "data a gap is never an opportunity: it is a stale leg or a mis-keyed cross.",
    )
    caption(
        figure,
        f"Tolerance +/-{tolerance_bps:g} bp. Every other cross in the matrix is derived through USD, so one bad leg "
        "would misstate every position held in that currency.",
    )
    return figure


# ---------------------------------------------------------------------------- stylised facts
def plot_return_distribution(log_returns: Mapping[str, Sequence[float]], *, lags: int = 20) -> Figure:
    """Fat tails and volatility clustering in the synthetic market - the reason the checks are robust."""
    standardised: list[float] = []
    for values in log_returns.values():
        data = np.asarray(values, dtype=float)
        if data.size > 30:
            standardised.extend(((data - data.mean()) / data.std()).tolist())
    sample = np.asarray(standardised)
    kurtosis = float((sample**4).mean() - 3)

    figure = new_figure(14.0, 5.6)
    grid = figure.add_gridspec(1, 2, width_ratios=[1.2, 1.0], wspace=0.22, **_margins(figure, bottom=0.8))
    hist_axis = figure.add_subplot(grid[0])
    bins = np.linspace(-8, 8, 81)
    hist_axis.hist(
        sample, bins=bins, density=True, color=PALETTE["sky"], alpha=0.85, label="Synthetic returns, standardised"
    )
    grid_x = np.linspace(-8, 8, 400)
    normal = np.exp(-0.5 * grid_x**2) / math.sqrt(2 * math.pi)
    hist_axis.plot(grid_x, normal, color=PALETTE["ink"], linewidth=1.4, label="Normal distribution")
    hist_axis.set_yscale("log")
    hist_axis.set_ylim(1e-5, 1)
    beyond = int((np.abs(sample) > 4).sum())
    expected = len(sample) * math.erfc(4 / math.sqrt(2))
    style_axes(hist_axis, title="Fat tails: density on a log scale", xlabel="Standard deviations", ylabel="Density")
    hist_axis.legend(loc="upper right")
    annotate(
        hist_axis,
        f"{beyond} moves beyond 4 sigma; a normal distribution expects {expected:.1f}\n"
        f"excess kurtosis {kurtosis:.1f} (normal: 0)",
        (0.02, 0.05),
        xycoords="axes fraction",
        va="bottom",
        highlight=True,
    )

    acf_axis = figure.add_subplot(grid[1])

    def autocorrelation(series: np.ndarray, lag: int) -> float:
        centred = series - series.mean()
        return float((centred[lag:] * centred[:-lag]).sum() / (centred**2).sum())

    lag_range = np.arange(1, lags + 1)
    pooled = [np.asarray(values, dtype=float) for values in log_returns.values() if len(values) > lags + 10]
    raw_acf = [float(np.mean([autocorrelation(values, lag) for values in pooled])) for lag in lag_range]
    squared_acf = [float(np.mean([autocorrelation(values**2, lag) for values in pooled])) for lag in lag_range]
    acf_axis.bar(lag_range - 0.2, raw_acf, width=0.4, color=PALETTE["slate"], label="Returns")
    acf_axis.bar(lag_range + 0.2, squared_acf, width=0.4, color=PALETTE["navy"], label="Squared returns")
    # the plotted value is a mean over len(pooled) independent series, so its null band narrows accordingly
    band = 1.96 / math.sqrt(sum(len(values) for values in pooled))
    acf_axis.axhspan(-band, band, color=PALETTE["band"], zorder=0)
    acf_axis.axhline(0, color=PALETTE["ink"], linewidth=0.6)
    style_axes(
        acf_axis, title="Volatility clusters: autocorrelation by lag", xlabel="Lag (days)", ylabel="Autocorrelation"
    )
    acf_axis.legend(loc="upper right")

    title_block(
        figure,
        "The synthetic market behaves like a real one",
        "Student-t innovations give the tails; GARCH(1,1) makes a large move raise the variance of the days after it. "
        "Returns themselves are unpredictable; their size is not.",
    )
    caption(
        figure,
        f"{len(sample):,} daily returns pooled across {len(log_returns)} instruments, each standardised by its own "
        "volatility. Shaded band: 95% bound for a zero mean autocorrelation across the instruments.",
    )
    return figure


def demo_lots() -> tuple[list[TaxLot], StockSplit, SpinOff, CashDividend]:
    """A three-lot holding and three events, used by the corporate actions chart and its test."""
    lots = [
        TaxLot(
            lot_id="L1",
            instrument_id="DEMO-SPLIT",
            open_date=date(2024, 5, 2),
            quantity=Decimal(60),
            cost_per_unit=Decimal("455.20"),
            currency=USD,
        ),
        TaxLot(
            lot_id="L2",
            instrument_id="DEMO-SPLIT",
            open_date=date(2024, 11, 18),
            quantity=Decimal(40),
            cost_per_unit=Decimal("512.75"),
            currency=USD,
        ),
        TaxLot(
            lot_id="L3",
            instrument_id="DEMO-SPLIT",
            open_date=date(2025, 3, 7),
            quantity=Decimal(25),
            cost_per_unit=Decimal("398.10"),
            currency=USD,
        ),
    ]
    split_event = StockSplit(
        action_id="DEMO-SPLIT-4:1", instrument_id="DEMO-SPLIT", ex_date=date(2025, 6, 10), numerator=4
    )
    spin_off = SpinOff(
        action_id="DEMO-SPIN",
        instrument_id="DEMO-SPLIT",
        ex_date=date(2025, 10, 1),
        child_instrument_id="DEMO-CHILD",
        ratio=Decimal("0.2"),
        cost_allocation=Decimal("0.186"),
    )
    dividend_event = CashDividend(
        action_id="DEMO-DIV",
        instrument_id="DEMO-SPLIT",
        ex_date=date(2025, 12, 11),
        record_date=date(2025, 12, 11),
        pay_date=date(2025, 12, 29),
        amount=Decimal("0.30"),
        currency="USD",
        withholding_rate=Decimal("0.15"),
    )
    return lots, split_event, spin_off, dividend_event


__all__ = [
    "demo_lots",
    "plot_fx_triangle",
    "plot_lot_adjustments",
    "plot_point_in_time",
    "plot_return_distribution",
    "plot_split_adjustment",
    "plot_vendor_consensus",
]
