"""How each currency was managed against the euro, and when it stopped being fixed at all.

A quality rule that judges an exchange rate without knowing its regime gets
three things systematically wrong. Run on 27 years of ECB fixings, version 1.1.0
raised 1,282 findings, most of them for these reasons:

- **A pegged rate is supposed to look stale.** The Bulgarian lev was fixed at
  1.95583 to the euro by a currency board, and the ECB printed 1.9558 every day for
  a quarter of a century. That is a policy, not a frozen feed.
- **A pegged rate makes a robust scale of zero.** Against a window of identical
  fixings, the one-tick wobble of a rounded print is "infinitely many" median
  absolute deviations away.
- **A currency that joined the euro is supposed to stop.** From 1 January 2008 there
  was no Cypriot pound to fix, and 4,801 "missing" days afterwards are not missing.

This module is the reference data those rules need:

- the periods in which the ECB fixed each currency, and why each period ended;
- the regime in force: a currency board, an ERM II band, or a float;
- the irrevocable conversion rates of the currencies that became the euro.

Dates and rates are from the ECB, the Council of the EU's conversion-rate
regulations and the national central banks. Each record names its source.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum


class RegimeKind(str, Enum):
    FLOAT = "float"
    CURRENCY_BOARD = "currency board"  # fixed by law, backed one for one by reserves
    ERM_II = "ERM II"  # a central rate with a fluctuation band, on the way to the euro
    UNILATERAL_PEG = "unilateral peg"  # a band the central bank chose, without ERM II
    CRAWLING_PEG = "crawling peg"  # a central rate devalued on a pre-announced schedule
    FLOOR = "floor"  # a one-sided limit defended by the central bank


@dataclass(frozen=True, slots=True)
class Regime:
    """One currency's regime against the euro over a period."""

    currency: str
    kind: RegimeKind
    start: date
    end: date | None
    central: Decimal | None = None
    band: float | None = None  # +/- fraction of the central rate
    source: str = ""

    def covers(self, day: date) -> bool:
        return self.start <= day and (self.end is None or day <= self.end)

    @property
    def is_managed(self) -> bool:
        """A regime under which a central bank, not the market, decides where the rate sits."""
        return self.kind is not RegimeKind.FLOAT

    def deviation(self, rate: Decimal) -> float | None:
        """How far a fixing sits from the central rate, as a fraction of it."""
        return float(rate / self.central - 1) if self.central else None


class EndReason(str, Enum):
    EURO = "joined the euro"
    REDENOMINATED = "redenominated"
    SUSPENDED = "fixing suspended"


@dataclass(frozen=True, slots=True)
class Ending:
    """Why the ECB stopped fixing a currency on a day, and at what rate if it became the euro."""

    currency: str
    last_fixing: date
    reason: EndReason
    detail: str
    conversion_rate: Decimal | None = None
    resumed: date | None = None


D = Decimal

REGIMES: tuple[Regime, ...] = (
    # currency boards: the rate is the law
    # a board fixes the rate at the central bank's own window; the market fixing the ECB samples sits
    # within a fraction of a per cent of it, so the band is the 1% a board's counterparties are held to
    Regime("BGN", RegimeKind.CURRENCY_BOARD, date(1999, 1, 1), date(2025, 12, 31), D("1.95583"), 0.01,
           "Bulgarian National Bank: currency board since 1997, re-anchored to the euro at the DEM rate"),
    Regime("EEK", RegimeKind.CURRENCY_BOARD, date(1999, 1, 1), date(2010, 12, 31), D("15.6466"), 0.01,
           "Eesti Pank: currency board, ERM II from 2004 at the same rate"),
    Regime("LTL", RegimeKind.CURRENCY_BOARD, date(2002, 2, 2), date(2014, 12, 31), D("3.4528"), 0.01,
           "Lietuvos bankas: board re-pegged from the dollar to the euro on 2 February 2002"),
    # ERM II and unilateral bands
    Regime("DKK", RegimeKind.ERM_II, date(1999, 1, 1), None, D("7.46038"), 0.0225,
           "Danmarks Nationalbank: ERM II, central rate 7.46038, band +/-2.25%"),
    Regime("LVL", RegimeKind.UNILATERAL_PEG, date(2005, 1, 1), date(2013, 12, 31), D("0.702804"), 0.01,
           "Latvijas Banka: pegged to the euro at 0.702804 +/-1% (ERM II from May 2005)"),
    Regime("CYP", RegimeKind.UNILATERAL_PEG, date(1999, 1, 1), date(2005, 5, 1), D("0.585274"), 0.15,
           "Central Bank of Cyprus: pegged to the euro, the band widened from 2.25% to 15% in 2001"),
    Regime("MTL", RegimeKind.UNILATERAL_PEG, date(1999, 1, 1), date(2005, 5, 1), None, None,
           "Central Bank of Malta: pegged to a basket of the euro, sterling and the dollar"),
    Regime("TRL", RegimeKind.CRAWLING_PEG, date(2000, 1, 1), date(2001, 2, 21), None, None,
           "Central Bank of Turkey: a pre-announced crawl against a dollar-euro basket, the IMF programme of 2000"),
    Regime("SIT", RegimeKind.CRAWLING_PEG, date(1999, 1, 1), date(2004, 6, 27), None, None,
           "Banka Slovenije: a managed float with a steady, pre-signalled depreciation against the euro"),
    Regime("SIT", RegimeKind.ERM_II, date(2004, 6, 28), date(2006, 12, 31), D("239.640"), 0.15,
           "Banka Slovenije: ERM II at 239.640, held within a fraction of a per cent of it"),
    Regime("HUF", RegimeKind.CRAWLING_PEG, date(1999, 1, 1), date(2001, 5, 3), None, 0.0225,
           "Magyar Nemzeti Bank: crawling peg against the euro, +/-2.25%"),
    Regime("HUF", RegimeKind.UNILATERAL_PEG, date(2001, 5, 4), date(2008, 2, 25), None, 0.15,
           "Magyar Nemzeti Bank: band widened to +/-15% around a euro central rate, abandoned February 2008"),
    Regime("CYP", RegimeKind.ERM_II, date(2005, 5, 2), date(2007, 12, 31), D("0.585274"), 0.15,
           "Central Bank of Cyprus: ERM II, central rate 0.585274, band +/-15%"),
    Regime("MTL", RegimeKind.ERM_II, date(2005, 5, 2), date(2007, 12, 31), D("0.429300"), 0.15,
           "Central Bank of Malta: ERM II at 0.429300, held unilaterally at the central rate"),
    Regime("SKK", RegimeKind.ERM_II, date(2005, 11, 28), date(2007, 3, 16), D("38.4550"), 0.15,
           "Narodna banka Slovenska: ERM II entry at 38.4550"),
    Regime("SKK", RegimeKind.ERM_II, date(2007, 3, 19), date(2008, 5, 28), D("35.4424"), 0.15,
           "ERM II central rate revalued by 8.5% to 35.4424"),
    Regime("SKK", RegimeKind.ERM_II, date(2008, 5, 29), date(2008, 12, 31), D("30.1260"), 0.15,
           "ERM II central rate revalued by 17.6% to 30.1260, later the conversion rate"),
    Regime("HRK", RegimeKind.ERM_II, date(2020, 7, 10), date(2022, 12, 31), D("7.53450"), 0.15,
           "Hrvatska narodna banka: ERM II, central rate 7.53450, band +/-15%"),
    Regime("BGN", RegimeKind.ERM_II, date(2020, 7, 10), date(2025, 12, 31), D("1.95583"), 0.15,
           "Bulgarian National Bank: ERM II alongside the board, central rate 1.95583"),
    # floors defended by a central bank
    Regime("CHF", RegimeKind.FLOOR, date(2011, 9, 6), date(2015, 1, 14), D("1.20"), None,
           "Swiss National Bank: minimum rate of 1.20 per euro, 6 September 2011 to 15 January 2015"),
    Regime("CZK", RegimeKind.FLOOR, date(2013, 11, 7), date(2017, 4, 5), D("27.0"), None,
           "Czech National Bank: koruna kept above 27 per euro, 7 November 2013 to 6 April 2017"),
)  # fmt: skip

ENDINGS: tuple[Ending, ...] = (
    Ending("SIT", date(2006, 12, 29), EndReason.EURO, "Slovenia adopted the euro on 1 January 2007", D("239.640")),
    Ending("CYP", date(2007, 12, 31), EndReason.EURO, "Cyprus adopted the euro on 1 January 2008", D("0.585274")),
    Ending("MTL", date(2007, 12, 31), EndReason.EURO, "Malta adopted the euro on 1 January 2008", D("0.429300")),
    Ending("SKK", date(2008, 12, 31), EndReason.EURO, "Slovakia adopted the euro on 1 January 2009", D("30.1260")),
    Ending("EEK", date(2010, 12, 31), EndReason.EURO, "Estonia adopted the euro on 1 January 2011", D("15.6466")),
    Ending("LVL", date(2013, 12, 31), EndReason.EURO, "Latvia adopted the euro on 1 January 2014", D("0.702804")),
    Ending("LTL", date(2014, 12, 31), EndReason.EURO, "Lithuania adopted the euro on 1 January 2015", D("3.45280")),
    Ending("HRK", date(2022, 12, 30), EndReason.EURO, "Croatia adopted the euro on 1 January 2023", D("7.53450")),
    Ending("BGN", date(2025, 12, 31), EndReason.EURO, "Bulgaria adopted the euro on 1 January 2026", D("1.95583")),
    Ending("TRL", date(2004, 12, 31), EndReason.REDENOMINATED,
           "Turkey redenominated: 1 new lira (TRY) for 1,000,000 old, 1 January 2005"),
    Ending("ROL", date(2005, 6, 30), EndReason.REDENOMINATED,
           "Romania redenominated: 1 new leu (RON) for 10,000 old, 1 July 2005"),
    Ending("ISK", date(2008, 12, 9), EndReason.SUSPENDED,
           "The ECB stopped fixing the krona after Iceland's banking collapse", resumed=date(2018, 2, 1)),
    Ending("RUB", date(2022, 3, 1), EndReason.SUSPENDED,
           "The ECB suspended the rouble fixing after Russia's invasion of Ukraine"),
)  # fmt: skip


def regimes_for(currency: str) -> tuple[Regime, ...]:
    return tuple(regime for regime in REGIMES if regime.currency == currency.upper())


def regime_on(currency: str, day: date) -> Regime | None:
    """The managed regime in force on a day, the tightest band first; None for a free float."""
    matching = [regime for regime in regimes_for(currency) if regime.covers(day)]
    if not matching:
        return None
    return min(matching, key=lambda regime: regime.band if regime.band is not None else 1.0)


def ending_for(currency: str) -> Ending | None:
    return next((ending for ending in ENDINGS if ending.currency == currency.upper()), None)


def inactive_spans(currency: str) -> tuple[tuple[date, date | None], ...]:
    """Periods with no fixing to expect: after the euro or a redenomination, or while suspended."""
    ending = ending_for(currency)
    if ending is None:
        return ()
    if ending.reason is EndReason.SUSPENDED and ending.resumed is not None:
        return ((ending.last_fixing, ending.resumed),)
    return ((ending.last_fixing, None),)
