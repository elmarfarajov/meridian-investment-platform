"""Flat files: the format market data still most often arrives in.

Custodian price files, vendor end-of-day drops and manual overrides from the
pricing desk are overwhelmingly CSV. The reader is strict about structure and
honest about failure: every rejected line is reported with its line number and
the reason, because "the load succeeded" and "every line loaded" are different
statements, and operations need to know which one is true.
"""

from __future__ import annotations

import csv
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from ...core.decimals import to_decimal
from ...core.exceptions import ValidationError
from ..quotes import FxQuote, Quote
from .base import ProviderError

QUOTE_COLUMNS = ("date", "instrument_id", "close", "currency", "bid", "ask", "volume", "source")
FX_COLUMNS = ("date", "base", "quote", "rate", "source")
_REQUIRED_QUOTE = {"date", "instrument_id", "close", "currency"}
_REQUIRED_FX = {"date", "base", "quote", "rate"}


@dataclass(frozen=True, slots=True)
class LoadIssue:
    path: str
    line: int
    message: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.message}"


@dataclass
class LoadResult:
    quotes: list[Quote] = field(default_factory=list)
    fx: list[FxQuote] = field(default_factory=list)
    issues: list[LoadIssue] = field(default_factory=list)
    lines_read: int = 0

    @property
    def accepted(self) -> int:
        return len(self.quotes) + len(self.fx)

    @property
    def is_clean(self) -> bool:
        return not self.issues


def _parse_date(text: str) -> date:
    try:
        return date.fromisoformat(text.strip())
    except ValueError as error:
        raise ValidationError(f"date {text!r} is not ISO 8601 (YYYY-MM-DD)") from error


def _optional(row: dict[str, str], name: str) -> str | None:
    value = (row.get(name) or "").strip()
    return value or None


def read_quotes(path: str | Path, *, default_source: str | None = None, strict: bool = False) -> LoadResult:
    """Read an end-of-day price file. With ``strict``, the first bad line raises."""
    target = Path(path)
    result = LoadResult()
    source = default_source or target.stem
    with target.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        header = {name.strip().lower() for name in (reader.fieldnames or [])}
        missing = _REQUIRED_QUOTE - header
        if missing:
            raise ProviderError(f"{target.name}: missing required column(s) {', '.join(sorted(missing))}")
        for line_number, raw in enumerate(reader, start=2):
            result.lines_read += 1
            row = {key.strip().lower(): (value or "") for key, value in raw.items() if key is not None}
            try:
                volume_text = _optional(row, "volume")
                bid_text, ask_text = _optional(row, "bid"), _optional(row, "ask")
                result.quotes.append(
                    Quote(
                        instrument_id=row["instrument_id"].strip(),
                        day=_parse_date(row["date"]),
                        close=to_decimal(row["close"], field="close"),
                        currency=row["currency"].strip(),
                        source=_optional(row, "source") or source,
                        bid=to_decimal(bid_text, field="bid") if bid_text else None,
                        ask=to_decimal(ask_text, field="ask") if ask_text else None,
                        volume=int(volume_text) if volume_text else None,
                    )
                )
            except (ValidationError, ValueError) as error:
                issue = LoadIssue(target.name, line_number, str(error))
                if strict:
                    raise ProviderError(str(issue)) from error
                result.issues.append(issue)
    return result


def read_fx(path: str | Path, *, default_source: str | None = None, strict: bool = False) -> LoadResult:
    target = Path(path)
    result = LoadResult()
    source = default_source or target.stem
    with target.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        header = {name.strip().lower() for name in (reader.fieldnames or [])}
        missing = _REQUIRED_FX - header
        if missing:
            raise ProviderError(f"{target.name}: missing required column(s) {', '.join(sorted(missing))}")
        for line_number, raw in enumerate(reader, start=2):
            result.lines_read += 1
            row = {key.strip().lower(): (value or "") for key, value in raw.items() if key is not None}
            try:
                result.fx.append(
                    FxQuote(
                        base=row["base"].strip(),
                        quote=row["quote"].strip(),
                        day=_parse_date(row["date"]),
                        rate=to_decimal(row["rate"], field="rate"),
                        source=_optional(row, "source") or source,
                    )
                )
            except (ValidationError, ValueError) as error:
                issue = LoadIssue(target.name, line_number, str(error))
                if strict:
                    raise ProviderError(str(issue)) from error
                result.issues.append(issue)
    return result


def write_quotes(path: str | Path, quotes: Iterable[Quote]) -> int:
    """Write quotes in the format :func:`read_quotes` reads, and return the row count."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with target.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(QUOTE_COLUMNS)
        for quote in sorted(quotes, key=lambda item: (item.day, item.instrument_id, item.source)):
            writer.writerow(
                [
                    quote.day.isoformat(),
                    quote.instrument_id,
                    str(quote.close),
                    quote.currency,
                    "" if quote.bid is None else str(quote.bid),
                    "" if quote.ask is None else str(quote.ask),
                    "" if quote.volume is None else str(quote.volume),
                    quote.source,
                ]
            )
            count += 1
    return count


def write_fx(path: str | Path, rates: Iterable[FxQuote]) -> int:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with target.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(FX_COLUMNS)
        for rate in sorted(rates, key=lambda item: (item.day, item.pair, item.source)):
            writer.writerow([rate.day.isoformat(), rate.base, rate.quote, str(rate.rate), rate.source])
            count += 1
    return count


class CsvProvider:
    """A directory of price and FX files presented as one provider."""

    def __init__(self, name: str, quote_files: Sequence[str | Path] = (), fx_files: Sequence[str | Path] = ()) -> None:
        self._name = name
        self._quotes: list[Quote] = []
        self._fx: list[FxQuote] = []
        self.issues: list[LoadIssue] = []
        for path in quote_files:
            loaded = read_quotes(path, default_source=name)
            self._quotes.extend(loaded.quotes)
            self.issues.extend(loaded.issues)
        for path in fx_files:
            loaded = read_fx(path, default_source=name)
            self._fx.extend(loaded.fx)
            self.issues.extend(loaded.issues)

    @property
    def name(self) -> str:
        return self._name

    def quotes(self, instrument_ids: Sequence[str], start: date, end: date) -> list[Quote]:
        wanted = set(instrument_ids)
        return [quote for quote in self._quotes if quote.instrument_id in wanted and start <= quote.day <= end]

    def fx_quotes(self, pairs: Sequence[str], start: date, end: date) -> list[FxQuote]:
        wanted = {pair.upper() for pair in pairs}
        return [rate for rate in self._fx if rate.pair in wanted and start <= rate.day <= end]
