"""The golden record: one version of the truth about a security, from several vendors.

Every data vendor describes the same bond slightly differently. One has the
coupon as 4.125, another as 4.12500; one files it under "Financials", another
under "Banks"; one has last year's rating. A security master builds a single
*golden record* from them by *survivorship rules*: for each field, an ordered
list of the sources to trust, applied after the values have been validated and
normalised.

Two properties make the result auditable rather than merely plausible:

* **Lineage.** Every field of the golden record says which source it came from.
  When a coupon is questioned, the answer is "vendor B, loaded on the 14th",
  not "the system says so".
* **Conflicts are kept.** Where sources disagree beyond normalisation, the
  disagreement is recorded even though a winner was chosen, because a
  disagreement between two reputable vendors is often the first sign that one
  of them has missed a corporate action.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation

from ..core.exceptions import ValidationError
from ..core.identifiers import identify

#: Fields whose values are validated by a check digit before they can win.
_IDENTIFIER_FIELDS = {"isin": "ISIN", "cusip": "CUSIP", "sedol": "SEDOL", "figi": "FIGI", "lei": "LEI"}
#: Fields compared numerically, so 4.125 and 4.12500 are the same value.
_NUMERIC_FIELDS = {"coupon", "face_value", "multiplier", "shares_outstanding", "expense_ratio"}
#: Fields that are dates.
_DATE_FIELDS = {"maturity", "issue_date", "inception"}

#: Vendors use different names for the same classification; this is the part of the mapping
#: that the demonstration data needs, not a complete taxonomy.
SECTOR_SYNONYMS: dict[str, str] = {
    "INFORMATION TECH": "Information Technology",
    "INFORMATION TECHNOLOGY": "Information Technology",
    "TECHNOLOGY": "Information Technology",
    "IT": "Information Technology",
    "HEALTHCARE": "Health Care",
    "HEALTH CARE": "Health Care",
    "PHARMACEUTICALS": "Health Care",
    "INDUSTRIALS": "Industrials",
    "AEROSPACE & DEFENSE": "Industrials",
    "FINANCIALS": "Financials",
    "BANKS": "Financials",
}


@dataclass(frozen=True, slots=True)
class VendorRecord:
    """What one source says about one security on one date."""

    source: str
    instrument_id: str
    fields: Mapping[str, str]
    as_of: date | None = None


@dataclass(frozen=True, slots=True)
class FieldConflict:
    """Sources that disagreed about one field after normalisation."""

    field: str
    values: tuple[tuple[str, str], ...]  # (source, normalised value)
    chosen_source: str

    def describe(self) -> str:
        listed = ", ".join(f"{source}={value}" for source, value in self.values)
        return f"{self.field}: {listed} (kept {self.chosen_source})"


@dataclass(frozen=True, slots=True)
class RejectedValue:
    """A value that failed validation and could not win, whatever its source's rank."""

    field: str
    source: str
    value: str
    reason: str


@dataclass(frozen=True)
class GoldenRecord:
    instrument_id: str
    values: dict[str, str]
    lineage: dict[str, str]
    conflicts: tuple[FieldConflict, ...] = ()
    rejected: tuple[RejectedValue, ...] = ()

    def get(self, name: str, default: str | None = None) -> str | None:
        return self.values.get(name, default)

    @property
    def completeness(self) -> float:
        """Share of the fields any source offered that ended up with a value."""
        offered = set(self.values) | {item.field for item in self.rejected}
        return len(self.values) / len(offered) if offered else 1.0

    def source_share(self) -> dict[str, int]:
        """How many fields each source won - the headline number of a vendor review."""
        counts: dict[str, int] = {}
        for source in self.lineage.values():
            counts[source] = counts.get(source, 0) + 1
        return dict(sorted(counts.items()))


@dataclass
class SurvivorshipPolicy:
    """Which source wins each field. Sources not listed rank below every listed one."""

    default_ranking: Sequence[str]
    field_ranking: dict[str, Sequence[str]] = field(default_factory=dict)

    def ranking(self, name: str) -> list[str]:
        return list(self.field_ranking.get(name, self.default_ranking))

    def rank(self, name: str, source: str) -> int:
        order = self.ranking(name)
        return order.index(source) if source in order else len(order)


def normalise(name: str, value: str) -> str:
    """Put a raw vendor value into the platform's canonical form, or raise if it is invalid."""
    text = value.strip()
    if not text:
        raise ValidationError("empty")
    if name in _IDENTIFIER_FIELDS:
        text = text.upper()
        if _IDENTIFIER_FIELDS[name] not in identify(text):
            raise ValidationError(f"fails the {_IDENTIFIER_FIELDS[name]} check digit")
        return text
    if name in _NUMERIC_FIELDS:
        try:
            number = Decimal(text.replace(",", ""))
        except InvalidOperation as error:
            raise ValidationError("not a number") from error
        if not number.is_finite():
            raise ValidationError("not finite")
        return format(number.normalize(), "f")
    if name in _DATE_FIELDS:
        try:
            return date.fromisoformat(text).isoformat()
        except ValueError as error:
            raise ValidationError("not an ISO date") from error
    if name == "sector":
        return SECTOR_SYNONYMS.get(text.upper(), text)
    if name in {"currency", "country", "exchange", "ticker"}:
        return text.upper()
    return " ".join(text.split())


def build_golden_record(
    records: Sequence[VendorRecord],
    policy: SurvivorshipPolicy,
    *,
    normaliser: Callable[[str, str], str] = normalise,
) -> GoldenRecord:
    """Combine vendor records for one instrument into a golden record with lineage."""
    if not records:
        raise ValidationError("a golden record needs at least one vendor record")
    instrument_ids = {record.instrument_id for record in records}
    if len(instrument_ids) != 1:
        raise ValidationError(f"records describe more than one instrument: {sorted(instrument_ids)}")
    instrument_id = instrument_ids.pop()

    candidates: dict[str, list[tuple[str, str]]] = {}
    rejected: list[RejectedValue] = []
    for record in records:
        for name, raw in record.fields.items():
            try:
                value = normaliser(name, raw)
            except ValidationError as error:
                rejected.append(RejectedValue(name, record.source, raw, str(error)))
                continue
            candidates.setdefault(name, []).append((record.source, value))

    values: dict[str, str] = {}
    lineage: dict[str, str] = {}
    conflicts: list[FieldConflict] = []
    for name, offered in sorted(candidates.items()):
        ordered = sorted(offered, key=lambda item: (policy.rank(name, item[0]), item[0]))
        winner_source, winner_value = ordered[0]
        values[name] = winner_value
        lineage[name] = winner_source
        if len({value for _, value in offered}) > 1:
            conflicts.append(FieldConflict(name, tuple(ordered), winner_source))
    return GoldenRecord(instrument_id, values, lineage, tuple(conflicts), tuple(rejected))


def build_security_master(records: Sequence[VendorRecord], policy: SurvivorshipPolicy) -> dict[str, GoldenRecord]:
    """Golden records for every instrument the vendor records mention."""
    grouped: dict[str, list[VendorRecord]] = {}
    for record in records:
        grouped.setdefault(record.instrument_id, []).append(record)
    return {key: build_golden_record(items, policy) for key, items in sorted(grouped.items())}


def demo_vendor_records() -> list[VendorRecord]:
    """Three vendors' descriptions of three securities, disagreeing the way real vendors do."""
    return [
        VendorRecord(
            "exchange",
            "US-AAPL",
            {"name": "APPLE INC", "isin": "US0378331005", "ticker": "aapl", "currency": "usd", "exchange": "XNAS"},
        ),
        VendorRecord(
            "vendor-b",
            "US-AAPL",
            {
                "name": "Apple Inc.",
                "isin": "US0378331005",
                "cusip": "037833100",
                "sector": "Information Tech",
                "industry": "Technology Hardware",
                "country": "us",
                "shares_outstanding": "14,840,390,000",
            },
        ),
        VendorRecord(
            "evaluated",
            "US-AAPL",
            {
                "name": "Apple Inc",
                "isin": "US0378331006",  # bad check digit
                "sector": "Technology",
                "shares_outstanding": "15204137000",
            },
        ),
        VendorRecord("exchange", "US-T-2032", {"name": "T 2 7/8 05/15/32", "isin": "US91282CEF41", "currency": "USD"}),
        VendorRecord(
            "vendor-b",
            "US-T-2032",
            {
                "name": "US Treasury 2.875% 15 May 2032",
                "coupon": "2.875",
                "maturity": "2032-05-15",
                "issue_date": "2022-05-16",
                "cusip": "91282CEF4",
            },
        ),
        VendorRecord(
            "evaluated",
            "US-T-2032",
            {"coupon": "2.87500", "maturity": "2032-05-15", "issue_date": "2022-05-15", "face_value": "100"},
        ),
        VendorRecord(
            "exchange",
            "GB-BAE",
            {
                "name": "BAE SYSTEMS PLC",
                "isin": "GB0002634946",
                "sedol": "0263494",
                "currency": "GBP",
                "exchange": "XLON",
            },
        ),
        VendorRecord(
            "vendor-b",
            "GB-BAE",
            {"name": "BAE Systems plc", "sector": "Aerospace & Defense", "currency": "GBX", "country": "GB"},
        ),
        VendorRecord("evaluated", "GB-BAE", {"sector": "Industrials", "sedol": "0263495"}),  # bad check digit
    ]


def demo_policy() -> SurvivorshipPolicy:
    """Exchange for listing data, the data vendor for classification, the evaluator for bond terms."""
    return SurvivorshipPolicy(
        default_ranking=("exchange", "vendor-b", "evaluated"),
        field_ranking={
            "name": ("vendor-b", "exchange", "evaluated"),
            "sector": ("vendor-b", "evaluated", "exchange"),
            "industry": ("vendor-b", "evaluated", "exchange"),
            "coupon": ("evaluated", "vendor-b", "exchange"),
            "maturity": ("evaluated", "vendor-b", "exchange"),
            "issue_date": ("vendor-b", "evaluated", "exchange"),
            "currency": ("exchange", "vendor-b", "evaluated"),
        },
    )
