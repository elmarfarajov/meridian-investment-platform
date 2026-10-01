"""Exchange-rate quality checks that know each currency's regime, lifecycle and history.

The series rules in :mod:`meridian.quality.rules` were written for share prices and
measured against a synthetic market. Run unchanged on 27 years of ECB fixings, they
raised 1,282 findings. Most were not faults in the data. They were facts about
currencies that a rule needs to be told:

- a currency board or an ERM II band makes a rate *meant* to be flat, so it is judged
  against its band (:class:`PegBand`), not by how unusual a move looks;
- a currency that joined the euro, was redenominated or was suspended has no
  fixings to expect afterwards;
- some days really are extraordinary - the Swiss National Bank removing its floor,
  the Brexit vote. A finding on such a day is *explained*, not dismissed: it stays
  in the report, labelled with the event (:data:`MARKET_EVENTS`).

What is left after that is what a data team should look at.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta

from ..marketdata.series import TimeSeries
from ..refdata.currency_regimes import RegimeKind, inactive_spans, regime_on
from .context import SeriesContext
from .findings import Dimension, Finding, Severity
from .rules import Rule

#: A fixing is printed to four or five significant figures; a band edge needs that much slack.
ROUNDING_SLACK = 0.0005


@dataclass
class PegBand(Rule):
    """A managed rate outside its band, or a defended floor broken by more than ``floor_slack``."""

    floor_slack: float = 0.01
    name = "peg_band"
    dimension = Dimension.VALIDITY
    description = "Managed exchange rate outside its band or floor"

    def check(self, context: SeriesContext) -> list[Finding]:
        currency = context.key[3:]
        findings: list[Finding] = []
        for point in context.series:
            regime = regime_on(currency, point.day)
            if regime is None or regime.central is None:
                continue
            deviation = regime.deviation(point.value)
            assert deviation is not None
            if regime.kind is RegimeKind.FLOOR:
                if deviation < -self.floor_slack:
                    findings.append(
                        self.finding(
                            context,
                            point.day,
                            Severity.WARNING,
                            f"{context.key} at {point.value} is {deviation:+.2%} through the {regime.central} floor",
                            observed=float(point.value),
                            expected=float(regime.central),
                        )
                    )
                continue
            if regime.band is not None and abs(deviation) > regime.band + ROUNDING_SLACK:
                findings.append(
                    self.finding(
                        context,
                        point.day,
                        Severity.ERROR,
                        f"{context.key} at {point.value} is {deviation:+.2%} from the {regime.kind.value} central "
                        f"rate {regime.central}, outside its +/-{regime.band:.2%} band",
                        observed=float(point.value),
                        expected=float(regime.central),
                    )
                )
        return findings


#: After a regime ends, or a suspended fixing resumes, this many fixings pass before statistics mean anything.
WARM_UP = 60


def managed_days(currency: str, days: Sequence[date]) -> frozenset[date]:
    """The days on which statistics cannot judge a rate.

    These are days under a managed regime - a board, a band, a crawl or a floor,
    when the central bank and not the market decides where the rate sits. They
    are also the ``WARM_UP`` fixings after a regime ends or a suspended fixing
    resumes, while the trailing window still holds the managed period. A window of
    a floor's barely moving fixings makes every ordinary move after its removal
    look like a hundred deviations.
    """
    ordered = sorted(days)
    excluded: set[date] = set()
    previous_managed = False
    countdown = 0
    previous_day: date | None = None
    inactive = inactive_spans(currency)
    for day in ordered:
        managed = (regime := regime_on(currency, day)) is not None and regime.is_managed
        resumed = previous_day is not None and any(
            after <= previous_day and until is not None and day >= until for after, until in inactive
        )
        if managed:
            excluded.add(day)
        elif previous_managed or resumed:
            countdown = WARM_UP
        if not managed and countdown > 0:
            excluded.add(day)
            countdown -= 1
        previous_managed = managed
        previous_day = day
    return frozenset(excluded)


def fx_context(pair: str, series: TimeSeries, *, calendar: str = "TARGET", as_of: date | None = None) -> SeriesContext:
    """A context for a rate against the euro, told its currency's regimes and lifecycle."""
    currency = pair[3:]
    return SeriesContext.from_series(
        pair,
        series,
        calendar,
        as_of=as_of,
        inactive=inactive_spans(currency),
        managed=managed_days(currency, series.days),
    )


# ---------------------------------------------------------------------------- what really happened
@dataclass(frozen=True, slots=True)
class MarketEvent:
    """A day on which a currency genuinely did something extraordinary, with what and why."""

    day: date
    currencies: tuple[str, ...]
    title: str
    detail: str
    aftermath_days: int = 10  # how long the volatility it caused can trip the rules

    def explains(self, currency: str, day: date) -> bool:
        return (currency in self.currencies or "*" in self.currencies) and self.day - timedelta(
            days=3
        ) <= day <= self.day + timedelta(days=self.aftermath_days)


MARKET_EVENTS: tuple[MarketEvent, ...] = (
    MarketEvent(date(2001, 2, 22), ("TRL",), "Turkey floats the lira", "the crawling peg abandoned in a crisis", 60),
    MarketEvent(date(2001, 9, 11), ("*",), "The 11 September attacks", "markets shut, then a flight to safety"),
    MarketEvent(date(2011, 8, 8), ("*",), "The US downgrade sell-off", "after S&P cut the US rating", 10),
    MarketEvent(date(2001, 12, 20), ("ZAR",), "The rand collapses and rebounds", "13.85 to the dollar"),
    MarketEvent(date(2007, 8, 16), ("AUD", "NZD", "JPY"), "The carry trade unwinds", "the yen rallies"),
    MarketEvent(date(2008, 3, 17), ("*",), "Bear Stearns is rescued", "a weekend sale to JPMorgan"),
    MarketEvent(date(2012, 7, 6), ("RON",), "Romania's president is suspended", "a constitutional crisis", 10),
    MarketEvent(date(2013, 12, 17), ("TRY",), "Turkey's corruption probe", "arrests close to the government", 15),
    MarketEvent(date(2020, 11, 7), ("TRY",), "Turkey replaces its central bank governor", "the lira rebounds", 5),
    MarketEvent(date(2021, 1, 14), ("ILS",), "Bank of Israel buys $30 billion", "a year of intervention announced", 5),
    MarketEvent(date(2021, 3, 20), ("TRY",), "Turkey's central bank governor is dismissed", "after a rate rise", 5),
    MarketEvent(date(2023, 6, 7), ("TRY",), "Turkey's lira is let go after the election", "a new economic team", 10),
    MarketEvent(date(2025, 4, 2), ("*",), "US 'Liberation Day' tariffs", "the broadest US tariffs in a century", 10),
    MarketEvent(date(2025, 5, 5), ("RON",), "Romania's election: the leu is let fall", "after the first round", 30),
    MarketEvent(date(2001, 5, 4), ("HUF",), "Hungary widens its band", "the forint's band widened to +/-15%"),
    MarketEvent(date(2003, 1, 15), ("HUF",), "The forint's band is attacked", "speculation on a stronger edge", 10),
    MarketEvent(date(2003, 6, 4), ("HUF",), "Hungary devalues its central rate", "the central parity moved 2.26%"),
    MarketEvent(date(2010, 5, 6), ("*",), "The euro-area debt crisis", "the Greek bailout and the flash crash", 20),
    MarketEvent(date(2008, 9, 15), ("*",), "Lehman Brothers fails", "the global financial crisis", 60),
    MarketEvent(date(2008, 10, 6), ("ISK",), "Iceland's banks collapse", "the krona in free fall", 60),
    MarketEvent(date(2011, 9, 6), ("CHF",), "SNB sets a floor of 1.20", "EURCHF jumps about 9% in a morning"),
    MarketEvent(date(2013, 11, 7), ("CZK",), "CNB caps the koruna at 27", "the Czech National Bank intervenes"),
    MarketEvent(date(2014, 12, 15), ("RUB", "TRY"), "The rouble crisis", "a rise to 17% fails", 20),
    MarketEvent(date(2015, 1, 15), ("CHF",), "SNB removes the floor", "EURCHF falls about 20% intraday", 20),
    MarketEvent(date(2016, 6, 24), ("GBP", "JPY"), "The Brexit referendum", "sterling's largest fall in decades"),
    MarketEvent(date(2017, 4, 6), ("CZK",), "CNB exits the cap", "the koruna floats again"),
    MarketEvent(date(2018, 8, 10), ("TRY",), "The lira crisis", "US sanctions and tariffs on Turkey", 20),
    MarketEvent(date(2020, 3, 9), ("*",), "The COVID-19 crash", "dollar funding stress across emerging markets", 30),
    MarketEvent(date(2021, 11, 23), ("TRY",), "The lira falls 15% in a day", "rate cuts into inflation", 40),
    MarketEvent(date(2022, 2, 24), ("RUB", "CZK", "PLN", "HUF"), "Russia invades Ukraine", "sanctions", 10),
    MarketEvent(date(2022, 9, 23), ("GBP",), "The mini-budget", "sterling's gilt and currency crisis", 10),
)  # fmt: skip


@dataclass
class Review:
    """The findings on one series, sorted into explained by a market event and left to investigate."""

    key: str
    explained: list[tuple[Finding, MarketEvent]] = field(default_factory=list)
    open: list[Finding] = field(default_factory=list)


def review(findings: Sequence[Finding], events: Sequence[MarketEvent] = MARKET_EVENTS) -> dict[str, Review]:
    """Attach each finding to the market event that explains it, if one does."""
    results: dict[str, Review] = {}
    for finding in findings:
        entry = results.setdefault(finding.key, Review(finding.key))
        currency = finding.key[3:] if len(finding.key) == 6 else finding.key
        event = next((item for item in events if item.explains(currency, finding.day)), None)
        if event is not None and finding.rule in {"robust_outlier", "spike_reversal"}:
            entry.explained.append((finding, event))
        else:
            entry.open.append(finding)
    return results
