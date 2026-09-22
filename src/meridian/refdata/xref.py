"""Identifier cross-reference with validity periods.

An identifier is not a permanent name for a security. Tickers change and are
reassigned: Facebook traded as ``FB`` until June 2022 and as ``META`` after,
and ``T`` identified AT&T Corp until SBC Communications bought it in 2005 and
took both its name and its ticker. Even ISINs change when a company
redomiciles or restructures. A security master that maps an identifier
straight to an instrument - with no dates - will resolve an old trade file
against whoever holds the ticker today, and nothing downstream will notice.

So every mapping here carries a validity interval ``[valid_from, valid_to)``
and every lookup carries a date. Two rules are enforced when a mapping is
added, because breaking either makes the answer ambiguous:

1. One identifier cannot point at two instruments over overlapping dates.
2. One instrument cannot hold two values of the same scheme over overlapping
   dates (two ISINs at once).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import date, timedelta
from enum import Enum

from ..core.exceptions import ValidationError
from ..core.identifiers import identify, isin_check_digit
from ..domain.corporate_actions import SymbolChange
from ..domain.instruments import Instrument

OPEN_END = date(9999, 12, 31)


class IdentifierScheme(str, Enum):
    ISIN = "isin"
    CUSIP = "cusip"
    SEDOL = "sedol"
    FIGI = "figi"
    TICKER = "ticker"
    LEI = "lei"
    VENDOR = "vendor"  # a vendor's own key, such as a Bloomberg or Refinitiv id

    @property
    def is_check_digit_scheme(self) -> bool:
        return self in {
            IdentifierScheme.ISIN,
            IdentifierScheme.CUSIP,
            IdentifierScheme.SEDOL,
            IdentifierScheme.FIGI,
            IdentifierScheme.LEI,
        }


class XrefConflict(ValidationError):
    """A mapping that would make an identifier or an instrument ambiguous."""


@dataclass(frozen=True, slots=True)
class XrefEntry:
    """``value`` in ``scheme`` identifies ``instrument_id`` from ``valid_from`` until (not including) ``valid_to``."""

    scheme: IdentifierScheme
    value: str
    instrument_id: str
    valid_from: date
    valid_to: date = OPEN_END
    source: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", self.value.strip().upper())
        if not self.value:
            raise ValidationError("an identifier value cannot be empty")
        if self.valid_to <= self.valid_from:
            raise ValidationError(f"{self.scheme.value} {self.value}: validity must end after it starts")
        if self.scheme.is_check_digit_scheme and self.scheme.name not in identify(self.value):
            raise ValidationError(f"{self.value} is not a valid {self.scheme.name}")

    def is_valid_on(self, day: date) -> bool:
        return self.valid_from <= day < self.valid_to

    def overlaps(self, other: XrefEntry) -> bool:
        return self.valid_from < other.valid_to and other.valid_from < self.valid_to

    @property
    def is_open(self) -> bool:
        return self.valid_to == OPEN_END

    def describe(self) -> str:
        end = "open" if self.is_open else (self.valid_to - timedelta(days=1)).isoformat()
        return f"{self.scheme.value}:{self.value} -> {self.instrument_id} [{self.valid_from.isoformat()} .. {end}]"


class CrossReference:
    """A point-in-time map between identifiers and instruments."""

    def __init__(self, entries: Iterable[XrefEntry] = ()) -> None:
        self._by_value: dict[tuple[IdentifierScheme, str], list[XrefEntry]] = defaultdict(list)
        self._by_instrument: dict[str, list[XrefEntry]] = defaultdict(list)
        for entry in entries:
            self.add(entry)

    # ------------------------------------------------------------------ writing
    def add(self, entry: XrefEntry) -> XrefEntry:
        for existing in self._by_value.get((entry.scheme, entry.value), []):
            if existing.overlaps(entry) and existing.instrument_id != entry.instrument_id:
                raise XrefConflict(
                    f"{entry.scheme.value} {entry.value} already identifies {existing.instrument_id} "
                    f"from {existing.valid_from} - it cannot also identify {entry.instrument_id}"
                )
            if existing == entry:
                return existing
        for existing in self._by_instrument.get(entry.instrument_id, []):
            if existing.scheme is entry.scheme and existing.overlaps(entry) and existing.value != entry.value:
                raise XrefConflict(
                    f"{entry.instrument_id} already has {entry.scheme.value} {existing.value} "
                    f"over overlapping dates; close it before adding {entry.value}"
                )
        self._by_value[(entry.scheme, entry.value)].append(entry)
        self._by_value[(entry.scheme, entry.value)].sort(key=lambda item: item.valid_from)
        self._by_instrument[entry.instrument_id].append(entry)
        self._by_instrument[entry.instrument_id].sort(key=lambda item: (item.scheme.value, item.valid_from))
        return entry

    def close(self, scheme: IdentifierScheme, value: str, instrument_id: str, on: date) -> XrefEntry:
        """End an open mapping so that ``on`` is its first invalid day."""
        key = (scheme, value.strip().upper())
        for index, entry in enumerate(self._by_value.get(key, [])):
            if entry.instrument_id == instrument_id and entry.is_valid_on(on - timedelta(days=1)):
                closed = replace(entry, valid_to=on)
                self._by_value[key][index] = closed
                siblings = self._by_instrument[instrument_id]
                siblings[siblings.index(entry)] = closed
                return closed
        raise ValidationError(f"no open {scheme.value} {value} for {instrument_id} on {on}")

    def rename(self, change: SymbolChange, *, source: str = "corporate_action") -> XrefEntry:
        """Apply a ticker change: the old symbol stops on the ex-date and the new one starts."""
        self.close(IdentifierScheme.TICKER, change.old_symbol, change.instrument_id, change.ex_date)
        return self.add(
            XrefEntry(IdentifierScheme.TICKER, change.new_symbol, change.instrument_id, change.ex_date, source=source)
        )

    # ------------------------------------------------------------------ reading
    def __len__(self) -> int:
        return sum(len(items) for items in self._by_value.values())

    def resolve(self, scheme: IdentifierScheme | str, value: str, on: date) -> str | None:
        """The instrument ``value`` identified on ``on``, or ``None``."""
        resolved = IdentifierScheme(scheme)
        for entry in self._by_value.get((resolved, value.strip().upper()), []):
            if entry.is_valid_on(on):
                return entry.instrument_id
        return None

    def resolve_any(self, value: str, on: date) -> list[tuple[IdentifierScheme, str]]:
        """Try every scheme: useful when a file does not say what kind of identifier it carries."""
        found: list[tuple[IdentifierScheme, str]] = []
        for scheme in IdentifierScheme:
            instrument = self.resolve(scheme, value, on)
            if instrument is not None:
                found.append((scheme, instrument))
        return found

    def identifiers(self, instrument_id: str, on: date) -> dict[IdentifierScheme, str]:
        """Every identifier an instrument carried on one date."""
        return {
            entry.scheme: entry.value for entry in self._by_instrument.get(instrument_id, []) if entry.is_valid_on(on)
        }

    def history(self, scheme: IdentifierScheme | str, value: str) -> tuple[XrefEntry, ...]:
        """Everything an identifier has ever pointed at, in date order."""
        return tuple(self._by_value.get((IdentifierScheme(scheme), value.strip().upper()), []))

    def entries(self, instrument_id: str | None = None) -> tuple[XrefEntry, ...]:
        if instrument_id is not None:
            return tuple(self._by_instrument.get(instrument_id, []))
        return tuple(entry for items in self._by_value.values() for entry in items)

    def reused(self) -> dict[tuple[IdentifierScheme, str], tuple[str, ...]]:
        """Identifiers that have pointed at more than one instrument over time."""
        return {
            key: tuple(dict.fromkeys(entry.instrument_id for entry in items))
            for key, items in self._by_value.items()
            if len({entry.instrument_id for entry in items}) > 1
        }


def xref_from_instruments(
    instruments: Sequence[Instrument], *, valid_from: date, source: str = "security_master"
) -> CrossReference:
    """Seed a cross-reference with every identifier the instruments currently carry."""
    reference = CrossReference()
    for instrument in instruments:
        identifiers = instrument.identifiers
        for scheme_name, value in identifiers.as_dict().items():
            scheme = IdentifierScheme(scheme_name)
            if scheme is IdentifierScheme.TICKER and identifiers.ticker is not None:
                value = identifiers.ticker.symbol  # the venue is a separate attribute, not part of the symbol
            reference.add(XrefEntry(scheme, value, instrument.instrument_id, valid_from, source=source))
    return reference


def _isin(prefix: str) -> str:
    """A syntactically valid ISIN for illustrative data: the prefix plus its computed check digit."""
    return f"{prefix}{isin_check_digit(prefix)}"


def demo_cross_reference() -> CrossReference:
    """An illustrative history with the three things that break naive identifier handling.

    * A ticker change: Facebook's ``FB`` became ``META`` on 9 June 2022.
    * A ticker reused by an unrelated company after the first holder delisted.
    * An ISIN change when a company redomiciles, with its ticker unchanged.

    Apart from Meta, the companies are fictional and their ISINs are generated
    with valid check digits for the purpose.
    """
    reference = CrossReference()
    add = reference.add
    add(XrefEntry(IdentifierScheme.ISIN, "US30303M1027", "US-META", date(2012, 5, 18), source="exchange"))
    add(XrefEntry(IdentifierScheme.TICKER, "FB", "US-META", date(2012, 5, 18), source="exchange"))
    reference.rename(
        SymbolChange(
            action_id="META-RENAME",
            instrument_id="US-META",
            ex_date=date(2022, 6, 9),
            old_symbol="FB",
            new_symbol="META",
        )
    )

    add(XrefEntry(IdentifierScheme.ISIN, _isin("US59867Q100"), "DEMO-OLDCO", date(2015, 3, 2), date(2020, 12, 1)))
    add(XrefEntry(IdentifierScheme.TICKER, "MRDN", "DEMO-OLDCO", date(2015, 3, 2), date(2020, 12, 1)))
    add(XrefEntry(IdentifierScheme.TICKER, "MRDN", "DEMO-NEWCO", date(2023, 4, 3), source="exchange"))
    add(XrefEntry(IdentifierScheme.ISIN, _isin("US59867R200"), "DEMO-NEWCO", date(2023, 4, 3), date(2025, 7, 1)))
    add(XrefEntry(IdentifierScheme.ISIN, _isin("IE000MRDN00"), "DEMO-NEWCO", date(2025, 7, 1), source="exchange"))

    add(XrefEntry(IdentifierScheme.ISIN, "US0378331005", "US-AAPL", date(1980, 12, 12), source="exchange"))
    add(XrefEntry(IdentifierScheme.TICKER, "AAPL", "US-AAPL", date(1980, 12, 12), source="exchange"))
    add(XrefEntry(IdentifierScheme.CUSIP, "037833100", "US-AAPL", date(1980, 12, 12), source="exchange"))
    return reference
