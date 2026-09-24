"""Settlement cycles, and the day they changed.

A trade is agreed on the trade date and settles - cash for securities - some
business days later. How many depends on the market and, since 28 May 2024,
on the date: the United States moved equities and ETFs from T+2 to T+1 that
day, and Canada and Mexico with it. The UK and the EU remain on T+2 and have
announced their own move to T+1 for October 2027. Treasuries have settled T+1
for years, and spot FX settles T+2.

The rule table is therefore dated, and the settlement date is found by
counting business days on the *joint* calendar of the exchange and the
settlement currency: a US stock bought on the day after a UK bank holiday
settles on a day both New York and the currency's clearing system are open.
Getting this wrong is not a rounding error - it moves cash between days and
creates overdrafts that do not exist, or hides ones that do.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from functools import lru_cache

from ..core.calendars import JointCalendar, TradingCalendar, get_calendar
from ..core.enums import AssetClass, InstrumentType
from ..core.exceptions import ValidationError
from ..domain.instruments import Instrument

US_T1_EFFECTIVE = date(2024, 5, 28)
#: The UK and EU move to T+1 was set for 11 October 2027; it is in the table so the change needs no code.
EUROPE_T1_EFFECTIVE = date(2027, 10, 11)


@dataclass(frozen=True, slots=True)
class SettlementRule:
    """``days`` business days after trade for trades in ``markets`` on or after ``effective_from``."""

    name: str
    markets: frozenset[str]
    days: int
    effective_from: date = date.min
    effective_to: date = date.max
    asset_classes: frozenset[AssetClass] = frozenset({AssetClass.EQUITY, AssetClass.MULTI_ASSET})

    def __post_init__(self) -> None:
        if self.days < 0:
            raise ValidationError(f"{self.name}: settlement cannot precede the trade")
        if self.effective_to <= self.effective_from:
            raise ValidationError(f"{self.name}: the rule ends before it starts")

    def applies(self, market: str, asset_class: AssetClass, trade_date: date) -> bool:
        return (
            market in self.markets
            and asset_class in self.asset_classes
            and self.effective_from <= trade_date < self.effective_to
        )


US_MARKETS = frozenset({"XNYS", "XNAS", "ARCX", "BATS", "US"})
UK_MARKETS = frozenset({"XLON", "UK"})
EU_MARKETS = frozenset({"XETR", "XAMS", "XPAR", "XMIL", "XMAD", "TARGET", "XSWX", "SIX"})

DEFAULT_RULES: tuple[SettlementRule, ...] = (
    SettlementRule("US equities T+2", US_MARKETS, 2, effective_to=US_T1_EFFECTIVE),
    SettlementRule("US equities T+1", US_MARKETS, 1, effective_from=US_T1_EFFECTIVE),
    SettlementRule("UK equities T+2", UK_MARKETS, 2, effective_to=EUROPE_T1_EFFECTIVE),
    SettlementRule("UK equities T+1", UK_MARKETS, 1, effective_from=EUROPE_T1_EFFECTIVE),
    SettlementRule("EU and Swiss equities T+2", EU_MARKETS, 2, effective_to=EUROPE_T1_EFFECTIVE),
    SettlementRule("EU and Swiss equities T+1", EU_MARKETS, 1, effective_from=EUROPE_T1_EFFECTIVE),
    SettlementRule(
        "Government bonds T+1",
        US_MARKETS | UK_MARKETS | EU_MARKETS | frozenset({"SIFMA"}),
        1,
        asset_classes=frozenset({AssetClass.FIXED_INCOME}),
    ),
)
FX_SPOT_DAYS = 2


@lru_cache(maxsize=64)
def _joint(names: tuple[str, ...]) -> TradingCalendar:
    if len(names) == 1:
        return get_calendar(names[0])
    return JointCalendar(list(names), name="+".join(names))


def settlement_calendar(*names: str) -> TradingCalendar:
    """The calendar on which every named market and currency is open."""
    unique = tuple(sorted({get_calendar(name).name for name in names}))
    return _joint(unique)


class SettlementRules:
    """Finds the contractual settlement date of a trade."""

    def __init__(self, rules: Sequence[SettlementRule] = DEFAULT_RULES, *, default_days: int = 2) -> None:
        self.rules = tuple(rules)
        self.default_days = default_days

    @staticmethod
    def market_of(instrument: Instrument) -> str:
        return (instrument.exchange or instrument.calendar or "").upper()

    def rule_for(self, instrument: Instrument, trade_date: date) -> SettlementRule | None:
        asset_class = instrument.asset_class
        markets = {self.market_of(instrument), instrument.calendar.upper()}
        if instrument.instrument_type in {InstrumentType.GOVERNMENT_BOND, InstrumentType.CORPORATE_BOND}:
            markets.add("SIFMA")
        for rule in self.rules:
            if any(rule.applies(market, asset_class, trade_date) for market in markets):
                return rule
        return None

    def cycle(self, instrument: Instrument, trade_date: date) -> int:
        rule = self.rule_for(instrument, trade_date)
        return rule.days if rule else self.default_days

    def calendar_for(self, instrument: Instrument) -> TradingCalendar:
        return settlement_calendar(instrument.calendar, instrument.currency.code)

    def settlement_date(self, instrument: Instrument, trade_date: date) -> date:
        calendar = self.calendar_for(instrument)
        start = trade_date if calendar.is_business_day(trade_date) else calendar.adjust(trade_date)
        return calendar.add_business_days(start, self.cycle(instrument, trade_date))

    def fx_settlement_date(self, sold: str, bought: str, trade_date: date) -> date:
        calendar = settlement_calendar(sold, bought, "USD")
        start = trade_date if calendar.is_business_day(trade_date) else calendar.adjust(trade_date)
        return calendar.add_business_days(start, FX_SPOT_DAYS)
