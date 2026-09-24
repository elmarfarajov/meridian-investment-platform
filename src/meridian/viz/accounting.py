"""Charts for the book of record.

Each chart answers one question an investment committee, an auditor or an
operations team actually asks of a portfolio's accounts:

* **Where did the value go?** The valuation waterfall, from opening to
  closing NAV through flows, price, currency, income and costs.
* **What is the portfolio made of, and what has it earned?** NAV through time
  by holding, with the investment result decomposed underneath it.
* **How much of a foreign holding's return is the currency?** Local price and
  currency, holding by holding.
* **Will the cash be there on settlement day?** Settled against projected cash,
  and the ladder of what settles next.
* **What did the move to T+1 change?** Settlement lags by market, before and
  after 28 May 2024.
* **When does income arrive, and how much is lost to tax?** Dividends and
  coupons from ex-date to pay date, with withholding split.
* **Does the book balance?** The trial balance as a chart.
* **What did a correction change?** NAV as it was known before an amended
  trade, and after.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import date, timedelta
from decimal import Decimal

import matplotlib.dates as mdates
import numpy as np
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

from ..accounting.book import Book
from ..accounting.bridge import ValueBridge
from ..accounting.chart_of_accounts import AccountClass, Accounts
from ..accounting.ledger import TrialBalanceLine
from ..accounting.settlement import US_T1_EFFECTIVE, SettlementRules
from ..accounting.valuation import PortfolioValuation
from ..core.enums import TransactionType
from ..domain.instruments import Instrument
from .style import PALETTE, annotate, caption, new_figure, style_axes, title_block, x_of

COMPONENT_COLOURS = {
    "Flows": PALETTE["sky"],
    "Price": PALETTE["navy"],
    "Currency": PALETTE["violet"],
    "Income": PALETTE["teal"],
    "Costs": PALETTE["loss"],
}
CURRENCY_COLOURS = {"USD": PALETTE["navy"], "EUR": PALETTE["teal"], "GBP": PALETTE["violet"], "CHF": PALETTE["sky"]}
#: Shades within each currency family, so a stacked chart of holdings also shows the currency exposure.
FAMILY_SHADES = {
    "USD": ["#12305E", "#1B3A6B", "#2C5282", "#3D6A9E", "#5584BA", "#7AA2CF", "#A3C0E2", "#C7DAF0"],
    "EUR": ["#1F8A80", "#5DB3A8"],
    "GBP": ["#6A4C93", "#9C86C0"],
    "CHF": ["#4A5C75", "#8A9BB0"],
}


def _family_rank(currency: str) -> int:
    families = list(FAMILY_SHADES)
    return families.index(currency) if currency in families else len(families)


def holding_colours(currencies: dict[str, str]) -> dict[str, str]:
    """A colour per holding, shaded within its currency's family."""
    used: dict[str, int] = defaultdict(int)
    colours: dict[str, str] = {}
    for key in sorted(currencies, key=lambda item: (_family_rank(currencies[item]), item)):
        shades = FAMILY_SHADES.get(currencies[key], [PALETTE["slate"]])
        colours[key] = shades[used[currencies[key]] % len(shades)]
        used[currencies[key]] += 1
    return colours


def _margins(
    figure: Figure, *, top: float = 1.25, bottom: float = 0.75, left: float = 0.07, right: float = 0.975
) -> dict:
    height = figure.get_figheight()
    return {"top": 1 - top / height, "bottom": bottom / height, "left": left, "right": right}


def _money(value: float, *, signed: bool = False) -> str:
    size = abs(value)
    text = f"{size / 1e6:,.2f}m" if size >= 1e6 else f"{size / 1e3:,.1f}k" if size >= 1e3 else f"{size:,.0f}"
    if signed:
        return ("+" if value >= 0 else "-") + text
    return ("-" if value < 0 else "") + text


def _thousands(axis: Axes, *, which: str = "y") -> None:
    formatter = axis.yaxis if which == "y" else axis.xaxis
    formatter.set_major_formatter(lambda value, _: _money(value))


# ---------------------------------------------------------------------------- the waterfall
def plot_valuation_waterfall(bridge: ValueBridge, *, title: str | None = None) -> Figure:
    """Opening NAV to closing NAV, component by component, with the price and currency effect per holding."""
    figure = new_figure(15.5, 7.6)
    grid = figure.add_gridspec(1, 2, width_ratios=[1.55, 1.0], wspace=0.24, **_margins(figure, bottom=1.05))
    axis = figure.add_subplot(grid[0])
    components = bridge.components()
    opening = float(bridge.opening)
    running = 0.0
    tops: list[float] = []
    for index, (label, amount) in enumerate(components):
        value = float(amount)
        if label in {"Opening NAV", "Closing NAV"}:
            axis.bar(index, value, color=PALETTE["slate"] if label == "Opening NAV" else PALETTE["navy"], width=0.62)
            running = value
            tops.append(value)
            axis.text(index, value, _money(value), ha="center", va="bottom", fontsize=9, weight="bold")
            continue
        colour = COMPONENT_COLOURS[label]
        start = running
        running += value
        axis.bar(index, value, bottom=start, color=colour, width=0.62, alpha=0.95)
        edge = max(start, running)
        tops.append(edge)
        share = value / opening if opening else 0.0
        axis.annotate(
            _money(value, signed=True),
            (index, edge),
            xytext=(0, 15),
            textcoords="offset points",
            ha="center",
            fontsize=9,
            weight="bold",
        )
        axis.annotate(
            f"{share:+.2%} of opening",
            (index, edge),
            xytext=(0, 4),
            textcoords="offset points",
            ha="center",
            fontsize=7.4,
            color=PALETTE["muted"],
        )
    for index in range(len(components) - 1):
        level = float(components[0][1]) + sum(float(amount) for _, amount in components[1 : index + 1])
        axis.plot([index + 0.31, index + 0.69], [level, level], color=PALETTE["muted"], linewidth=0.8, linestyle=":")
    low = min(opening, float(bridge.closing)) * 0.9
    high = max(tops) * 1.05
    axis.set_ylim(low, high)
    axis.set_xticks(range(len(components)), labels=[label for label, _ in components])
    _thousands(axis)
    style_axes(axis, title=f"Net asset value, {bridge.start:%d %b %Y} to {bridge.end:%d %b %Y}", ylabel="USD")
    result = float(bridge.investment_result)
    annotate(
        axis,
        f"investment result {_money(result, signed=True)} ({result / opening:+.2%}); residual "
        f"{float(bridge.residual):.1e}",
        (0.02, 0.965),
        xycoords="axes fraction",
        highlight=True,
        fontsize=8.5,
    )

    detail = figure.add_subplot(grid[1])
    effects = sorted(bridge.by_instrument.values(), key=lambda item: float(item.price + item.fx + item.income))
    names = [item.instrument_id for item in effects]
    rows = np.arange(len(effects))
    series = [
        (np.array([float(item.price) for item in effects]), COMPONENT_COLOURS["Price"], "Price", -0.27),
        (np.array([float(item.fx) for item in effects]), COMPONENT_COLOURS["Currency"], "Currency", 0.0),
        (np.array([float(item.income) for item in effects]), COMPONENT_COLOURS["Income"], "Accrued interest", 0.27),
    ]
    for values, colour, label, offset in series:
        if np.any(values):
            detail.barh(rows + offset, values, height=0.26, color=colour, label=label)
    detail.set_yticks(rows, labels=names)
    detail.axvline(0, color=PALETTE["ink"], linewidth=0.8)
    _thousands(detail, which="x")
    style_axes(detail, title="Price and currency, holding by holding", xlabel="USD", grid="x")
    detail.legend(loc="lower right")

    title_block(
        figure,
        title or "Where the value went",
        "Flows are money the client moved; everything else is what the portfolio earned. "
        "Price is measured in local currency at the opening rate, currency on the closing local value.",
    )
    caption(
        figure,
        "Daily bridges summed: each day's change in NAV is split exactly, and the residual is carried to show it is "
        "zero. Dividends are income on the ex-date; unreclaimable withholding is a cost. The NAV axis does not start "
        "at zero.",
    )
    return figure


# ---------------------------------------------------------------------------- NAV through time
def plot_nav_history(
    valuations: Sequence[PortfolioValuation],
    bridges: Sequence[ValueBridge],
    book: Book,
    instruments: dict[str, Instrument],
) -> Figure:
    """NAV stacked by holding, flows marked, and the cumulative investment result decomposed below it."""
    figure = new_figure(15.5, 9.4)
    grid = figure.add_gridspec(2, 1, height_ratios=[1.55, 1.0], hspace=0.2, **_margins(figure, bottom=0.95))
    top = figure.add_subplot(grid[0])
    days = [item.day for item in valuations]
    holdings = sorted({position.instrument_id for item in valuations for position in item.positions})
    order = sorted(holdings, key=lambda key: (_family_rank(instruments[key].currency.code), key))
    palette = holding_colours({key: instruments[key].currency.code for key in order})
    layers = [
        [
            float(next((p.total_base for p in item.positions if p.instrument_id == key), Decimal(0)))
            for item in valuations
        ]
        for key in order
    ]
    cash = [float(item.cash_like) for item in valuations]
    colours = [palette[key] for key in order]
    top.stackplot(days, *layers, cash, colors=[*colours, PALETTE["grid"]], alpha=0.95, linewidth=0.3, edgecolor="white")
    top.plot(days, [float(item.nav) for item in valuations], color=PALETTE["ink"], linewidth=1.3, label="NAV")
    for movement in book.cash_movements:
        if movement.kind in {"deposit", "withdrawal"} and days[0] < movement.trade_date <= days[-1]:
            nav = float(next(item.nav for item in valuations if item.day >= movement.trade_date))
            marker = "^" if movement.amount > 0 else "v"
            top.scatter([movement.trade_date], [nav], marker=marker, s=70, color=PALETTE["accent"], zorder=5)
            top.annotate(
                f"{movement.kind} {_money(float(movement.amount), signed=True)}",
                (x_of(movement.trade_date), nav),
                xytext=(6, 10 if movement.amount > 0 else -16),
                textcoords="offset points",
                fontsize=7.8,
                color=PALETTE["ink"],
            )
    for transfer in book.transactions:
        if transfer.transaction_type is TransactionType.TRANSFER_IN:
            nav = float(next(item.nav for item in valuations if item.day >= transfer.trade_date))
            top.scatter([transfer.trade_date], [nav], marker="D", s=40, color=PALETTE["accent"], zorder=5)
            top.annotate(
                f"{transfer.instrument_id} transferred in kind",
                (x_of(transfer.trade_date), nav),
                xytext=(6, 8),
                textcoords="offset points",
                fontsize=7.8,
            )
    handles = [
        Patch(color=colour, label=f"{key} ({instruments[key].currency.code})")
        for key, colour in zip(order, colours, strict=True)
    ]
    handles.append(Patch(color=PALETTE["grid"], label="cash, receivables and payables"))
    top.legend(handles=handles, loc="upper left", ncol=4, fontsize=7.5)
    top.set_xlim(x_of(days[0]), x_of(days[-1]))
    top.set_ylim(0, max(float(item.nav) for item in valuations) * 1.28)
    _thousands(top)
    style_axes(top, title="Net asset value by holding (USD)")

    bottom = figure.add_subplot(grid[1], sharex=top)
    cumulative: dict[str, list[float]] = defaultdict(list)
    totals = dict.fromkeys(("price", "fx", "income", "costs"), 0.0)
    step_days = [bridges[0].start] + [step.end for step in bridges]
    for key in totals:
        cumulative[key].append(0.0)
    for step in bridges:
        totals["price"] += float(step.price)
        totals["fx"] += float(step.fx)
        totals["income"] += float(step.income)
        totals["costs"] += float(step.costs)
        for key, value in totals.items():
            cumulative[key].append(value)
    labels = {"price": "Price", "fx": "Currency", "income": "Income", "costs": "Costs"}
    for key, series in cumulative.items():
        bottom.plot(step_days, series, color=COMPONENT_COLOURS[labels[key]], label=labels[key], linewidth=1.6)
        bottom.annotate(
            _money(series[-1], signed=True),
            (x_of(step_days[-1]), series[-1]),
            xytext=(4, 0),
            textcoords="offset points",
            fontsize=8,
            color=COMPONENT_COLOURS[labels[key]],
            va="center",
        )
    result = [sum(values) for values in zip(*cumulative.values(), strict=True)]
    bottom.plot(step_days, result, color=PALETTE["ink"], linewidth=2.0, label="Investment result")
    bottom.axhline(0, color=PALETTE["muted"], linewidth=0.8)
    _thousands(bottom)
    style_axes(bottom, title="Cumulative investment result, decomposed (USD)")
    bottom.legend(loc="lower left", ncol=5)
    title_block(
        figure,
        "Two and a half years of the book",
        "Global Equity Core: ten holdings in four currencies, valued every New York business day from the book of "
        "record.",
    )
    caption(
        figure,
        "Triangles mark client contributions and the distribution, the diamond the in-kind transfer: flows, not "
        "return, "
        "and therefore absent from the result below.",
    )
    return figure


# ---------------------------------------------------------------------------- currency
def plot_fx_separation(
    valuation: PortfolioValuation, fx_history: dict[str, list[tuple[date, float]]], *, base: str = "USD"
) -> Figure:
    """For each holding: unrealised result in base currency split into local price and currency."""
    figure = new_figure(15.5, 7.2)
    grid = figure.add_gridspec(1, 2, width_ratios=[1.25, 1.0], wspace=0.22, **_margins(figure, bottom=1.0))
    axis = figure.add_subplot(grid[0])
    positions = sorted(valuation.positions, key=lambda item: (item.currency == base, float(item.unrealised_base)))
    names = [f"{item.instrument_id} ({item.currency})" for item in positions]
    price = np.array([float(item.unrealised_price_base) for item in positions])
    fx = np.array([float(item.unrealised_fx_base) for item in positions])
    rows = np.arange(len(positions))
    axis.barh(rows - 0.18, price, height=0.34, color=COMPONENT_COLOURS["Price"], label="Price, in local currency")
    axis.barh(rows + 0.18, fx, height=0.34, color=COMPONENT_COLOURS["Currency"], label="Currency")
    for row, item in enumerate(positions):
        total = float(item.unrealised_base)
        axis.text(
            max(price[row], fx[row], 0) + abs(total) * 0.02 + 2000,
            row,
            f"total {_money(total, signed=True)}",
            va="center",
            fontsize=7.8,
            color=PALETTE["gain"] if total >= 0 else PALETTE["loss"],
        )
    axis.set_yticks(rows, labels=names)
    axis.axvline(0, color=PALETTE["ink"], linewidth=0.8)
    _thousands(axis, which="x")
    style_axes(axis, title=f"Unrealised result on open lots, {valuation.day:%d %b %Y} (USD)", grid="x")
    axis.legend(loc="lower right")
    foreign = [item for item in positions if item.currency != base]
    currency_share = sum(abs(float(item.unrealised_fx_base)) for item in foreign) / max(
        sum(abs(float(item.unrealised_base)) for item in foreign), 1.0
    )
    annotate(
        axis,
        f"on foreign holdings the currency is {currency_share:.0%} of the gross unrealised result",
        (0.02, 0.975),
        xycoords="axes fraction",
        highlight=True,
    )

    rates = figure.add_subplot(grid[1])
    for currency, series in sorted(fx_history.items()):
        if not series:
            continue
        first = series[0][1]
        rates.plot(
            [day for day, _ in series],
            [100 * value / first for _, value in series],
            color=CURRENCY_COLOURS.get(currency, PALETTE["slate"]),
            label=f"{currency} in {base}",
        )
    rates.axhline(100, color=PALETTE["muted"], linewidth=0.8)
    style_axes(rates, title=f"The currencies, in {base} (indexed to 100)")
    rates.legend(loc="upper left")
    title_block(
        figure,
        "Price and currency, separated",
        "Each lot's gain is split at its own purchase rate: (value - cost) at today's rate, plus cost times the move "
        "in "
        "the rate since the lot was bought.",
    )
    caption(
        figure,
        "The same split is used for realised gains and in the daily value bridge, so a gain does not change character "
        "when it is realised.",
    )
    return figure


# ---------------------------------------------------------------------------- cash and settlement
def plot_cash_ladder(book: Book, start: date, end: date, ladder_day: date) -> Figure:
    """Settled against projected cash per currency over a busy period, and the ladder of what settles next."""
    currencies = [c for c in ("USD", "EUR", "GBP", "CHF") if any(m.currency == c for m in book.cash_movements)]
    figure = new_figure(15.5, 8.6)
    grid = figure.add_gridspec(
        len(currencies), 2, width_ratios=[1.6, 1.0], hspace=0.45, wspace=0.2, **_margins(figure, bottom=0.9)
    )
    days = [start + timedelta(days=offset) for offset in range((end - start).days + 1)]
    days = [day for day in days if day.weekday() < 5]
    for row, currency in enumerate(currencies):
        axis = figure.add_subplot(grid[row, 0])
        settled = [float(book.settled_cash(currency, day)) for day in days]
        projected = [float(book.projected_cash(currency, day)) for day in days]
        colour = CURRENCY_COLOURS.get(currency, PALETTE["slate"])
        axis.fill_between(days, settled, projected, color=colour, alpha=0.15, step="post", linewidth=0)
        axis.step(days, settled, where="post", color=colour, linewidth=1.6, label="settled (what the custodian holds)")
        axis.step(
            days, projected, where="post", color=colour, linewidth=1.1, linestyle="--", label="projected (trade date)"
        )
        axis.axvline(x_of(ladder_day), color=PALETTE["accent"], linewidth=0.9)
        _thousands(axis)
        style_axes(axis, title=f"{currency} cash", grid="y")
        if row == 0:
            axis.legend(loc="upper left", ncol=2)
    ladder_axis = figure.add_subplot(grid[:, 1])
    ladder = book.cash_ladder(ladder_day, horizon_days=10)
    shown = [currency for currency in currencies if currency in ladder]
    width = 0.8 / max(len(shown), 1)
    labels: list[date] = []
    for index, currency in enumerate(shown):
        rows = ladder[currency]
        labels = [day for day, _, _ in rows]
        heights = [float(settling) for _, settling, _ in rows]
        ladder_axis.bar(
            np.arange(len(rows)) + index * width - 0.4 + width / 2,
            heights,
            width=width,
            color=CURRENCY_COLOURS.get(currency, PALETTE["slate"]),
            label=currency,
        )
    ladder_axis.set_xticks(range(len(labels)), labels=[f"{day:%a\n%d %b}" for day in labels], fontsize=7.5)
    ladder_axis.axhline(0, color=PALETTE["ink"], linewidth=0.8)
    _thousands(ladder_axis)
    style_axes(ladder_axis, title=f"Settling in the ten days after {ladder_day:%d %b %Y}", ylabel="local currency")
    ladder_axis.legend(loc="lower right")
    title_block(
        figure,
        "Cash by settlement date",
        "Trades move the position on trade date and the cash on settlement date; the gap between the two lines is "
        "money already committed.",
    )
    caption(figure, "The shaded band is the cash owed or owing on trades agreed but not yet settled.")
    return figure


def plot_settlement_cycles(book: Book, instruments: dict[str, Instrument]) -> Figure:
    """Business days from trade to settlement by market, before and after the US move to T+1."""
    rules = SettlementRules()
    figure = new_figure(15.5, 6.6)
    grid = figure.add_gridspec(1, 2, width_ratios=[1.0, 1.25], wspace=0.22, **_margins(figure, bottom=0.95))
    axis = figure.add_subplot(grid[0])
    counts: dict[tuple[str, str, int], int] = defaultdict(int)
    points: list[tuple[date, int, str]] = []
    for transaction in book.transactions:
        if (
            transaction.transaction_type not in {TransactionType.BUY, TransactionType.SELL}
            or not transaction.instrument_id
        ):
            continue
        instrument = instruments[transaction.instrument_id]
        calendar = rules.calendar_for(instrument)
        lag = calendar.business_days_between(transaction.trade_date, transaction.settles_on)
        market = "US" if instrument.currency.code == "USD" and (instrument.country or "US") == "US" else "Europe"
        if instrument.asset_class.value == "fixed_income":
            market = "Treasuries"
        era = "before 28 May 2024" if transaction.trade_date < US_T1_EFFECTIVE else "from 28 May 2024"
        counts[(market, era, lag)] += 1
        points.append((transaction.trade_date, lag, market))
    groups = [
        (market, era) for market in ("US", "Europe", "Treasuries") for era in ("before 28 May 2024", "from 28 May 2024")
    ]
    groups = [group for group in groups if any(key[:2] == group for key in counts)]
    lags = sorted({key[2] for key in counts})
    bottom = np.zeros(len(groups))
    lag_colours = {
        0: PALETTE["grid"],
        1: PALETTE["teal"],
        2: PALETTE["navy"],
        3: PALETTE["violet"],
        4: PALETTE["loss"],
        5: PALETTE["loss"],
    }
    for lag in lags:
        values = np.array([counts.get((*group, lag), 0) for group in groups], dtype=float)
        axis.bar(
            range(len(groups)), values, bottom=bottom, color=lag_colours.get(lag, PALETTE["slate"]), label=f"T+{lag}"
        )
        bottom += values
    short = {"before 28 May 2024": "before", "from 28 May 2024": "after"}
    axis.set_xticks(range(len(groups)), labels=[f"{market}\n{short[era]}" for market, era in groups], fontsize=8)
    axis.set_ylim(0, float(bottom.max()) * 1.15)
    style_axes(axis, title="Trades by settlement cycle, before and after 28 May 2024", ylabel="trades")
    axis.legend(loc="upper right")

    timeline = figure.add_subplot(grid[1])
    market_colours = {"US": PALETTE["navy"], "Europe": PALETTE["teal"], "Treasuries": PALETTE["violet"]}
    rng = np.random.default_rng(3)
    for market, colour in market_colours.items():
        selected = [(day, lag) for day, lag, name in points if name == market]
        if selected:
            jitter = rng.uniform(-0.12, 0.12, len(selected))
            timeline.scatter(
                [day for day, _ in selected],
                [lag + offset for (_, lag), offset in zip(selected, jitter, strict=True)],
                s=22,
                color=colour,
                label=market,
                alpha=0.85,
            )
    timeline.axvline(x_of(US_T1_EFFECTIVE), color=PALETTE["accent"], linewidth=1.2)
    annotate(
        timeline,
        "US equities move to T+1",
        (x_of(US_T1_EFFECTIVE), 3.3),
        highlight=True,
        xytext=(6, 0),
        textcoords="offset points",
    )
    timeline.set_yticks(range(0, max(lags) + 2), labels=[f"T+{lag}" for lag in range(0, max(lags) + 2)])
    style_axes(timeline, title="Every trade in the book: trade date against business days to settle")
    timeline.legend(loc="upper right")
    title_block(
        figure,
        "The day the settlement cycle changed",
        "The rule table is dated: the same stock settles T+2 on 24 May 2024 and T+1 on 28 May. Counting is on the "
        "joint "
        "calendar of the exchange and the settlement currency.",
    )
    caption(figure, "A failed settlement shows as a longer lag: the trade settled three business days late.")
    return figure


# ---------------------------------------------------------------------------- income
def plot_income_calendar(book: Book, instruments: dict[str, Instrument]) -> Figure:
    """Dividends and coupons from ex-date to pay date, and gross income against what withholding took."""
    figure = new_figure(15.5, 7.4)
    grid = figure.add_gridspec(1, 2, width_ratios=[1.45, 1.0], wspace=0.22, **_margins(figure, bottom=0.95))
    axis = figure.add_subplot(grid[0])
    events = [movement for movement in book.cash_movements if movement.kind in {"dividend", "interest"}]
    names = sorted({(entry_instrument(book, movement.transaction_id) or "?") for movement in events})
    rows = {name: index for index, name in enumerate(names)}
    biggest = max((float(movement.amount) for movement in events), default=1.0)
    for movement in events:
        instrument_id = entry_instrument(book, movement.transaction_id) or "?"
        row = rows[instrument_id]
        currency = movement.currency
        colour = CURRENCY_COLOURS.get(currency, PALETTE["slate"])
        start, end = movement.trade_date, movement.value_date
        axis.plot(
            [start, max(end, start + timedelta(days=2))], [row, row], color=colour, linewidth=3.2, solid_capstyle="butt"
        )
        axis.scatter([end], [row], s=18 + 180 * float(movement.amount) / biggest, color=colour, zorder=4, alpha=0.9)
    axis.set_yticks(range(len(names)), labels=names)
    axis.set_ylim(-0.7, len(names) - 0.3)
    style_axes(axis, title="Ex-date to pay date (dot size: amount received)", grid="x")
    axis.legend(
        handles=[
            Line2D([], [], color=colour, linewidth=4, label=currency) for currency, colour in CURRENCY_COLOURS.items()
        ],
        loc="lower left",
        ncol=4,
    )

    panel = figure.add_subplot(grid[1])
    gross: dict[str, float] = defaultdict(float)
    lost: dict[str, float] = defaultdict(float)
    reclaim: dict[str, float] = defaultdict(float)
    for entry in book.ledger:
        for posting in entry.postings:
            if not posting.instrument_id:
                continue
            key = posting.instrument_id
            if posting.account_code in {Accounts.DIVIDEND_INCOME.code, Accounts.INTEREST_INCOME.code}:
                gross[key] -= float(posting.base_amount)
            elif posting.account_code == Accounts.WITHHOLDING_TAX.code:
                lost[key] += float(posting.base_amount)
            elif posting.account_code == Accounts.TAX_RECLAIMABLE.code:
                reclaim[key] += float(posting.base_amount)
    keys = sorted(gross, key=lambda key: gross[key])
    positions = np.arange(len(keys))
    net = [gross[key] - lost[key] - reclaim[key] for key in keys]
    panel.barh(positions, net, color=PALETTE["teal"], label="received")
    panel.barh(positions, [reclaim[key] for key in keys], left=net, color=PALETTE["sky"], label="withheld, reclaimable")
    panel.barh(
        positions,
        [lost[key] for key in keys],
        left=[a + b for a, b in zip(net, [reclaim[key] for key in keys], strict=True)],
        color=PALETTE["loss"],
        label="withheld, lost",
    )
    for row, key in enumerate(keys):
        if lost[key] or reclaim[key]:
            rate = (lost[key] + reclaim[key]) / gross[key] if gross[key] else 0
            panel.text(gross[key] * 1.02, row, f"{rate:.1%} withheld", va="center", fontsize=7.8)
    panel.set_yticks(positions, labels=keys)
    _thousands(panel, which="x")
    style_axes(panel, title="Income by holding, and what withholding took (USD)", grid="x")
    panel.legend(loc="lower right")
    title_block(
        figure,
        "Income: earned on the ex-date, paid later, taxed at source",
        "A dividend is a receivable from the ex-date to the pay date. German and Swiss withholding is split into the "
        "part the treaty lets the account reclaim and the part that is lost.",
    )
    caption(figure, "Coupons on the Treasury net of the accrued interest paid when it was bought; dividends gross.")
    return figure


def entry_instrument(book: Book, source_id: str) -> str | None:
    for entry in book.ledger:
        if entry.source_id == source_id:
            for posting in entry.postings:
                if posting.instrument_id:
                    return posting.instrument_id
    return None


# ---------------------------------------------------------------------------- the ledger
CLASS_COLOURS = {
    AccountClass.ASSET: PALETTE["navy"],
    AccountClass.LIABILITY: PALETTE["violet"],
    AccountClass.CAPITAL: PALETTE["slate"],
    AccountClass.INCOME: PALETTE["teal"],
    AccountClass.EXPENSE: PALETTE["loss"],
}


def _ledger_bars(axis: Axes, lines: Sequence[TrialBalanceLine], title: str) -> None:
    rows = list(reversed(lines))
    values = [float(line.balance) for line in rows]
    axis.barh(range(len(rows)), values, color=[CLASS_COLOURS[line.account.account_class] for line in rows], height=0.64)
    reach = max((abs(value) for value in values), default=1.0)
    for row, value in enumerate(values):
        axis.text(
            value + (0.015 if value >= 0 else -0.015) * reach,
            row,
            f"{'Dr' if value >= 0 else 'Cr'} {_money(abs(value))}",
            va="center",
            ha="left" if value >= 0 else "right",
            fontsize=7.8,
        )
    axis.set_yticks(range(len(rows)), labels=[f"{line.account.code}  {line.account.name}" for line in rows], fontsize=8)
    axis.set_xlim(-reach * 1.35, reach * 1.35)
    axis.axvline(0, color=PALETTE["ink"], linewidth=0.8)
    axis.xaxis.set_major_formatter(lambda value, _: _money(value))
    style_axes(axis, title=title, grid="x")


def plot_trial_balance(book: Book, as_of: date) -> Figure:
    """The trial balance as a chart - balance sheet and income statement - and the accounting identity through time."""
    trial = book.ledger.trial_balance(as_of)
    figure = new_figure(16.0, 8.4)
    grid = figure.add_gridspec(
        2,
        2,
        width_ratios=[1.25, 1.0],
        height_ratios=[1.0, 1.3],
        hspace=0.42,
        wspace=0.62,
        **_margins(figure, bottom=1.05, left=0.19),
    )
    sheet = [line for line in trial.lines if line.account.account_class.is_balance_sheet]
    results = [line for line in trial.lines if not line.account.account_class.is_balance_sheet]
    _ledger_bars(figure.add_subplot(grid[0, 0]), sheet, "Balance sheet accounts (debits right, credits left)")
    income_axis = figure.add_subplot(grid[1, 0])
    _ledger_bars(income_axis, results, "Income and expense accounts (a realised loss is a debit)")
    income_axis.legend(
        handles=[Patch(color=colour, label=kind.value) for kind, colour in CLASS_COLOURS.items()],
        loc="upper center",
        ncol=5,
        bbox_to_anchor=(0.4, -0.12),
    )

    identity = figure.add_subplot(grid[:, 1])
    month_ends: list[date] = []
    cursor = date(book.first_day.year, book.first_day.month, 1) if book.first_day else as_of
    while cursor <= as_of:
        following = date(cursor.year + (cursor.month == 12), cursor.month % 12 + 1, 1)
        month_ends.append(min(following - timedelta(days=1), as_of))
        cursor = following
    net_assets, capital, gaps = [], [], []
    for month_end in month_ends:
        balance = book.ledger.trial_balance(month_end)
        net_assets.append(float(balance.net_assets))
        capital.append(float(balance.total(AccountClass.CAPITAL)))
        gaps.append(float(balance.difference))
    identity.plot(month_ends, capital, color=PALETTE["slate"], linewidth=2.0, label="capital contributed")
    identity.plot(
        month_ends, net_assets, color=PALETTE["navy"], linewidth=2.0, label="assets less liabilities, at cost"
    )
    identity.fill_between(
        month_ends,
        capital,
        net_assets,
        where=[a >= c for a, c in zip(net_assets, capital, strict=True)],
        color=PALETTE["gain"],
        alpha=0.25,
        interpolate=True,
    )
    identity.fill_between(
        month_ends,
        capital,
        net_assets,
        where=[a < c for a, c in zip(net_assets, capital, strict=True)],
        color=PALETTE["loss"],
        alpha=0.2,
        interpolate=True,
        label="net income to date (realised, at cost)",
    )
    _thousands(identity)
    style_axes(identity, title="Net assets = capital + net income, every month-end")
    identity.xaxis.set_major_locator(mdates.MonthLocator(bymonth=(1, 7)))
    identity.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    identity.legend(loc="upper right", bbox_to_anchor=(1.0, 0.93))
    worst = max(abs(gap) for gap in gaps)
    annotate(
        identity,
        f"debits {_money(float(trial.total_debits))} = credits {_money(float(trial.total_credits))}; "
        f"largest month-end difference {worst:.0e}",
        (0.02, 0.975),
        xycoords="axes fraction",
        highlight=True,
    )
    title_block(
        figure,
        "The book balances",
        "Every entry balances in base currency and in each local currency; the trial balance is their sum. The ledger "
        "is at cost: market value is a valuation of it, not an entry in it.",
    )
    caption(
        figure,
        f"{len(book.ledger):,} journal entries at {as_of:%d %b %Y}. The currency result on settlements and "
        "conversions has its own account, apart from the currency part of realised gains.",
    )
    return figure


# ---------------------------------------------------------------------------- corrections
def plot_restatement(
    days: Sequence[date],
    reported: Sequence[Decimal],
    restated: Sequence[Decimal],
    changes: dict[str, Decimal],
    *,
    trade_date: date,
    corrected_on: date,
    description: str,
) -> Figure:
    """NAV as reported each evening against NAV as now known, and what the correction changed in the accounts."""
    figure = new_figure(15.5, 7.4)
    grid = figure.add_gridspec(
        2,
        2,
        width_ratios=[1.45, 1.0],
        height_ratios=[1.3, 1.0],
        hspace=0.45,
        wspace=0.3,
        **_margins(figure, bottom=0.95),
    )
    axis = figure.add_subplot(grid[0, 0])
    axis.plot(days, [float(value) for value in restated], color=PALETTE["navy"], linewidth=1.8, label="as now known")
    axis.plot(
        days,
        [float(value) for value in reported],
        color=PALETTE["accent"],
        linewidth=1.2,
        linestyle="--",
        marker="o",
        markersize=3,
        label="as reported that evening",
    )
    for axes in (axis,):
        axes.axvspan(x_of(trade_date), x_of(corrected_on), color=PALETTE["band"], zorder=0)
    _thousands(axis)
    style_axes(axis, title="Net asset value, two versions of the same evenings (USD)")
    axis.legend(loc="lower left")
    difference = figure.add_subplot(grid[1, 0], sharex=axis)
    gaps = [float(now - then) for then, now in zip(reported, restated, strict=True)]
    difference.bar(days, gaps, color=PALETTE["loss"] if min(gaps, default=0) < 0 else PALETTE["gain"], width=0.8)
    difference.axhline(0, color=PALETTE["ink"], linewidth=0.8)
    difference.axvspan(x_of(trade_date), x_of(corrected_on), color=PALETTE["band"], zorder=0)
    wrong = sum(1 for gap in gaps if gap)
    style_axes(difference, title=f"Restated less reported: {wrong} evening reports were wrong")
    annotate(
        difference,
        "booked at the wrong price",
        (x_of(trade_date), max(gaps, default=0) * 1.02),
        xytext=(2, 6),
        textcoords="offset points",
    )
    annotate(
        difference,
        "corrected",
        (x_of(corrected_on), max(gaps, default=0) * 0.5),
        highlight=True,
        xytext=(6, 0),
        textcoords="offset points",
    )
    bars = figure.add_subplot(grid[:, 1])
    labels = list(changes)
    amounts = [float(changes[label]) for label in labels]
    bars.barh(
        range(len(labels)), amounts, color=[PALETTE["gain"] if value >= 0 else PALETTE["loss"] for value in amounts]
    )
    for row, value in enumerate(amounts):
        bars.text(value, row, f" {value:+,.2f} ", va="center", ha="left" if value >= 0 else "right", fontsize=8.5)
    bars.set_yticks(range(len(labels)), labels=labels)
    bars.axvline(0, color=PALETTE["ink"], linewidth=0.8)
    reach = max(abs(value) for value in amounts) or 1.0
    bars.set_xlim(-reach * 1.7, reach * 1.7)
    style_axes(bars, title="What the correction changed in the accounts", grid="x")
    title_block(
        figure,
        "A correction is a replay, not an edit",
        f"{description}. Each evening's NAV is rebuilt from the blotter exactly as it stood that evening; the "
        "difference from today's view is the restatement.",
    )
    caption(
        figure,
        "The overpayment was cash, so NAV was understated from settlement until the correction; the lot's cost falls "
        "by the same amount, and a later sale of it realises a correspondingly larger gain.",
    )
    return figure
