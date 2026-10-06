"""The client report: one PDF that assembles what every module of the platform knows about the account.

A client does not read a risk model or a ledger; they read a report, and the
report is where every number in the platform has to agree with every other. The
pack is built from the same objects the modules use - nothing is re-keyed - so
the NAV on the summary page is the valuation's, the returns are the
performance module's, the risk is the factor model's, the limits are the
compliance engine's, the tax position is the book's lots, and the trading costs
are the transaction cost analysis of the orders that were actually worked:

====  ============================  ======================================
page  content                       from
====  ============================  ======================================
1     cover and contents
2     summary                       valuation, performance, risk, compliance
3     holdings and tax position     the book's lots (Day 3), the rebalance
4     performance factsheet         Day 4
5     risk report                   Day 5
6     compliance report             Day 6
7     rebalance proposal            Day 7
8     trading and costs             Day 8: allocations and shortfall
9     methodology and disclosures
====  ============================  ======================================

The PDF is written by Matplotlib's PDF backend with the document's metadata,
and without a creation date, so the same data gives a byte-identical file.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.figure import Figure

from ..core.exceptions import ValidationError
from ..services.demo_execution import DemoExecution
from ..viz.accounting import _money
from ..viz.reporting import plot_cover, plot_holdings, plot_notes, plot_summary, plot_trading

PORTFOLIO = "PF-GLOBAL-EQ"
CONTENTS = (
    "Summary",
    "Holdings and tax position",
    "Performance",
    "Risk",
    "Compliance with the mandate",
    "The rebalance",
    "Trading and costs",
    "Methodology and important information",
)
TOTAL_PAGES = len(CONTENTS) + 1
SMALL_NUMBERS = ("no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine")


def in_words(count: int) -> str:
    """A count as a client report writes it: in words up to nine, in figures above."""
    return SMALL_NUMBERS[count] if 0 <= count < len(SMALL_NUMBERS) else f"{count:,}"


NOTES = (
    (
        "Valuation",
        "Positions are valued at the golden-copy closing price of each market (Day 2), converted to US dollars at the "
        "WM/Reuters-style 16:00 London fix; bonds include accrued interest. The book of record is a double-entry "
        "ledger "
        "at cost; market value is a valuation of it, and every change in value is explained by flows, price, currency, "
        "income and costs with no residual.",
    ),
    (
        "Performance",
        "Returns are time-weighted, chained daily from the value bridge with flows at the start of the day, net of "
        "trading costs and before management fees and tax. Periods over a year are annualised. The benchmark is the "
        "account's policy benchmark, rebalanced daily. Attribution is Brinson-Fachler on local returns, with currency "
        "and costs apart and index funds looked through, linked over time by Carino's method.",
    ),
    (
        "Risk",
        "Risk figures are forecasts from a 21-factor fundamental model estimated on a universe whose true risk is "
        "known, with EWMA factor covariance. Tracking error is the forecast standard deviation of the return against "
        "the policy benchmark; value at risk is the 99% one-day loss. Forecasts are not guarantees; the model is "
        "validated daily by bias statistics and value-at-risk backtests.",
    ),
    (
        "Tax",
        "Unrealised gains are shown against each lot's tax basis, which includes wash-sale adjustments, split by "
        "holding period (long-term after one year). Rates quoted are US federal including the 3.8% net investment "
        "income tax; state tax is not included. This report is not tax advice.",
    ),
    (
        "Trading and costs",
        "The rebalance was traded as block orders shared among the accounts following the same model, allocated at "
        "one average price, pro rata. Costs are implementation shortfall against the previous close (the decision "
        "price): spread, market impact, fees, the market's move before and during trading, and the cost of shares "
        "not traded, marked at the close.",
    ),
    (
        "Important information",
        "This report is produced by the Meridian Investment Platform, a demonstration system; the account, its "
        "holdings and all market data are simulated. Past performance is not a guide to future returns. The value "
        "of investments can fall as well as rise.",
    ),
)


@dataclass(frozen=True)
class Page:
    title: str
    build: Callable[[], Figure]


class ClientPack:
    def __init__(self, execution: DemoExecution, portfolio_id: str = PORTFOLIO) -> None:
        self.execution = execution
        self.optimisation = execution.optimisation
        self.portfolio_id = portfolio_id

    # ------------------------------------------------------------------ the data
    @property
    def as_of(self) -> date:
        return self.optimisation.as_of

    @property
    def names(self) -> tuple[str, str, str]:
        accounting = self.optimisation.accounting
        portfolio = accounting.portfolio
        return "Aliyeva Family Office", f"{portfolio.account_id} · Aliyeva Taxable Brokerage", portfolio.name

    def _performance(self):  # type: ignore[no-untyped-def]
        return self.optimisation.risk.performance

    def limit(self, rule_id: str) -> float:
        """A one-sided limit of the account's mandate, as written in it: never re-keyed into the report's text."""
        bound = self.optimisation.compliance.mandate.rule(rule_id).bound
        value = bound.upper if bound.upper is not None else bound.lower
        assert value is not None  # Rule guarantees a bound has a side
        return float(value)

    @property
    def blocks_traded(self) -> int:
        """The block orders the account's orders were worked in."""
        return sum(
            1 for block in self.execution.blocks if any(m.portfolio_id == self.portfolio_id for m in block.members)
        )

    @property
    def other_accounts(self) -> int:
        """The other accounts whose orders were in the same blocks."""
        accounts = {
            member.portfolio_id
            for block in self.execution.blocks
            if any(m.portfolio_id == self.portfolio_id for m in block.members)
            for member in block.members
        }
        return len(accounts - {self.portfolio_id})

    # ------------------------------------------------------------------ the pages
    def cover(self) -> Figure:
        client, account, portfolio = self.names
        start = self._performance().portfolio_returns.start
        return plot_cover(
            client, account, portfolio, (start, self.as_of), self.execution.trade_date, CONTENTS, TOTAL_PAGES
        )

    def summary(self) -> Figure:
        from ..compliance.engine import STATUSES

        perf = self._performance()
        risk = self.optimisation.risk
        compliance = self.optimisation.compliance
        valuation = self.optimisation.valuation
        mine = perf.portfolio_returns
        theirs = perf.benchmark_returns
        today = compliance.today
        counts = {status: today.count(status) for status in STATUSES}
        unrealised_lt = sum(float(position.unrealised_long_term) for position in valuation.positions)
        unrealised_st = sum(float(position.unrealised_short_term) for position in valuation.positions)
        mine_ytd = mine.total(date(self.as_of.year - 1, 12, 31), self.as_of)
        theirs_ytd = theirs.total(date(self.as_of.year - 1, 12, 31), self.as_of)
        costs = self.execution.account_costs[self.portfolio_id]
        value = sum(item.allocation.requested * item.decision for item in costs)
        shortfall = sum(item.shortfall for item in costs)
        tiles = [
            ("Portfolio value", _money(float(valuation.nav)), f"on {self.as_of:%d %b %Y}"),
            ("Return this year", f"{mine_ytd:+.2%}", f"benchmark {theirs_ytd:+.2%}"),
            ("Return since inception", f"{mine.total():+.2%}", f"benchmark {theirs.total():+.2%}"),
            (
                "Volatility (forecast)",
                f"{risk.portfolio.volatility:.1%}",
                f"tracking error {risk.active.volatility:.1%}",
            ),
            (
                "Mandate",
                f"{counts['pass']} of {sum(counts.values())} pass",
                f"{counts['warning']} warnings, {counts['breach']} breaches",
            ),
            (
                "Unrealised gains",
                _money(unrealised_lt + unrealised_st),
                f"long-term {_money(unrealised_lt)}, short-term {_money(unrealised_st)}",
            ),
        ]
        growth_mine = mine.index()
        growth_theirs = theirs.index()
        allocation = self._allocation()
        proposal = self.optimisation.proposal
        commentary = [
            f"The account returned {mine_ytd:+.2%} this year against {theirs_ytd:+.2%} for its policy benchmark. "
            f"Its forecast tracking error was {proposal.tracking_error_before:.2%}, against the mandate's "
            f"{self.limit('tracking_error'):.0%} soft limit.",
            f"We rebalanced towards the benchmark: the tracking error falls to {proposal.tracking_error_after:.2%}. "
            f"Choosing which tax lots to sell and harvesting losses turned the rebalance's tax bill into "
            + (f"a saving of {_money(-proposal.tax)}" if proposal.tax < 0 else f"{_money(proposal.tax)}")
            + f", with the account's active share at {proposal.active_share_after:.1%} against the mandate's "
            f"{self.limit('active_share'):.0%} floor.",
            f"The orders were traded on {self.execution.trade_date:%d %B} in {self.blocks_traded} blocks with "
            f"{in_words(self.other_accounts)} other accounts on the same model, at one average price. "
            "The account's share cost "
            f"{shortfall / value * 1e4:+.1f} basis points against the decision prices, including the market's own "
            "move during the day.",
        ]
        growth = (
            [day for day, _ in growth_mine],
            [value for _, value in growth_mine],
            [value for _, value in growth_theirs],
        )
        return plot_summary(tiles, growth, allocation, commentary, self.names[1], self.as_of, 2, TOTAL_PAGES)

    def _allocation(self) -> list[tuple[str, float]]:
        weights: dict[str, float] = {}
        for asset in self.optimisation.assets:
            if asset.quantity <= 0:
                continue
            label = str(asset.attributes.get("asset_class") or "other")
            label = {"fund": "equity funds", "equity": "equities", "fixed income": "bonds"}.get(label, label)
            weights[label] = weights.get(label, 0.0) + asset.value / self.optimisation.nav
        weights["cash"] = self.optimisation.cash
        return sorted(weights.items(), key=lambda item: -item[1])

    def holdings(self) -> Figure:
        valuation = self.optimisation.valuation
        after = self.optimisation.proposal.after
        nav = float(valuation.nav)
        rows = []
        for asset in sorted(self.optimisation.assets, key=lambda item: -item.value):
            if asset.quantity <= 0:
                continue
            position = valuation.position(asset.asset_id)
            long_term = float(position.unrealised_long_term) if position is not None else 0.0
            short_term = float(position.unrealised_short_term) if position is not None else 0.0
            rows.append(
                (
                    asset.asset_id,
                    str(asset.attributes.get("asset_class") or ""),
                    asset.quantity,
                    asset.value,
                    asset.value / nav,
                    long_term,
                    short_term,
                    after.get(asset.asset_id, 0.0),
                )
            )
        cash = self.optimisation.cash * nav
        return plot_holdings(rows, cash, nav, self.names[1], self.as_of, 3, TOTAL_PAGES)

    def trading(self) -> Figure:
        costs = self.execution.account_costs[self.portfolio_id]
        value = sum(item.allocation.requested * item.decision for item in costs)
        shortfall = sum(item.shortfall for item in costs)
        filled = sum(item.allocation.quantity * item.allocation.price for item in costs)
        rows = [
            (
                item.allocation.instrument_id,
                item.allocation.side.value,
                f"{item.allocation.requested:,.0f}",
                f"{item.allocation.quantity:,.0f}",
                f"{item.allocation.price:,.4f}" if item.allocation.quantity else "-",
                f"{item.shortfall_bps:+.1f} bp",
            )
            for item in sorted(costs, key=lambda item: (item.allocation.side.value, item.allocation.instrument_id))
        ]
        totals = self.execution.totals()
        paper = totals["paper value"]
        components = [
            (name.replace(" impact", "\nimpact"), totals[name] / paper * 1e4)
            for name in ("delay", "spread", "temporary impact", "permanent impact", "timing", "opportunity", "fees")
        ]
        unfilled = sum(
            item.allocation.requested - item.allocation.quantity
            for item in costs
            if item.allocation.quantity < item.allocation.requested
        )
        tiles = [
            ("Orders", f"{len(costs)}", f"shares of {self.blocks_traded} block orders"),
            ("Traded value", _money(filled), f"of {_money(value)} requested"),
            ("Cost against decision", f"{shortfall / value * 1e4:+.1f} bp", _money(shortfall)),
        ]
        if unfilled > 0:
            # expired blocks are not carried over (Day 8): what was not done is reported as not done
            tiles.append(("Not traded", f"{unfilled:,.0f} shares", "large blocks that expired at the close"))
        return plot_trading(tiles, rows, components, self.names[1], self.execution.trade_date, 8, TOTAL_PAGES)

    def notes(self) -> Figure:
        return plot_notes(NOTES, self.names[1], TOTAL_PAGES, TOTAL_PAGES)

    def pages(self) -> list[Page]:
        from ..compliance_gallery import report_chart as compliance_report
        from ..optimisation_gallery import report_chart as rebalance_report
        from ..performance_gallery import factsheet_chart
        from ..risk_gallery import report_chart as risk_report

        return [
            Page("Cover", self.cover),
            Page(CONTENTS[0], self.summary),
            Page(CONTENTS[1], self.holdings),
            Page(CONTENTS[2], factsheet_chart),
            Page(CONTENTS[3], risk_report),
            Page(CONTENTS[4], compliance_report),
            Page(CONTENTS[5], rebalance_report),
            Page(CONTENTS[6], self.trading),
            Page(CONTENTS[7], self.notes),
        ]

    # ------------------------------------------------------------------ the document
    def write(self, path: str | Path) -> Path:
        import matplotlib.pyplot as plt

        destination = Path(path)
        if destination.suffix.lower() != ".pdf":
            raise ValidationError("the client report is a PDF: give a path ending in .pdf")
        destination.parent.mkdir(parents=True, exist_ok=True)
        client, account, portfolio = self.names
        metadata = {
            "Title": f"{portfolio} - client report to {self.as_of:%d %B %Y}",
            "Author": "Meridian Investment Platform",
            "Subject": f"{client}, {account}",
            "Keywords": "performance, risk, compliance, tax, trading costs",
            "Creator": "meridian.reporting.client_pack",
            "CreationDate": None,
        }
        with PdfPages(destination, metadata=metadata) as pdf:
            for page in self.pages():
                figure = page.build()
                figure.set_size_inches(11.7, 16.5)
                pdf.savefig(figure)
                plt.close(figure)
        return destination
