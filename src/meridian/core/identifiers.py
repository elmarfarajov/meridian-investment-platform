"""Security identifiers with real check-digit validation.

Reference data is where portfolio systems quietly go wrong: a mistyped ISIN maps a
trade to the wrong instrument and the error surfaces weeks later in a
reconciliation. Every identifier here validates its own check digit, so bad data
is rejected at the boundary rather than stored.

* **ISIN** (ISO 6166): 12 characters, two-letter country prefix, Luhn check digit
  computed after expanding letters to their position in the alphabet plus nine.
* **CUSIP** (North America): 9 characters, weighted modulus 10 with letter expansion.
* **SEDOL** (UK): 7 characters, weighted sum with weights 1, 3, 1, 7, 3, 9, 1.
* **FIGI**: 12 characters beginning ``BBG``, modulus 10 double-add-double.
* **LEI** (ISO 17442): 20 characters identifying the *legal entity* rather than the
  security, validated by ISO 7064 MOD 97-10 - the same scheme as an IBAN.

The LEI is the one that matters for risk rather than for booking. An issuer limit,
a counterparty exposure and a look-through to a fund's parent are all questions
about entities, and a ticker cannot answer them: three instruments with three
ISINs can be one credit risk.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .exceptions import ValidationError

_ISIN_PATTERN = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")
_CUSIP_PATTERN = re.compile(r"^[0-9A-Z]{8}[0-9]$")
_SEDOL_PATTERN = re.compile(r"^[0-9B-DF-HJ-NP-TV-Z]{6}[0-9]$")
_FIGI_PATTERN = re.compile(r"^BBG[0-9B-DF-HJ-NP-TV-Z]{8}[0-9]$")
_LEI_PATTERN = re.compile(r"^[0-9A-Z]{18}[0-9]{2}$")
_TICKER_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9.\-/]{0,15}$")
_SEDOL_WEIGHTS = (1, 3, 1, 7, 3, 9, 1)


def _luhn_check_digit(digits: str) -> int:
    """Luhn modulus 10, doubling every second digit from the right."""
    total = 0
    for index, character in enumerate(reversed(digits)):
        value = int(character)
        if index % 2 == 0:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return (10 - total % 10) % 10


def _expand_alphanumerics(body: str) -> str:
    """Map letters to two-digit values (A=10 ... Z=35) as ISIN and FIGI require."""
    return "".join(str(ord(character) - 55) if character.isalpha() else character for character in body)


def isin_check_digit(body: str) -> int:
    """Check digit for the first 11 characters of an ISIN."""
    return _luhn_check_digit(_expand_alphanumerics(body.upper()))


def validate_isin(value: str) -> bool:
    candidate = value.strip().upper()
    if not _ISIN_PATTERN.match(candidate):
        return False
    return isin_check_digit(candidate[:11]) == int(candidate[11])


def cusip_check_digit(body: str) -> int:
    """Check digit for the first eight characters of a CUSIP."""
    total = 0
    for index, character in enumerate(body.upper()):
        if character.isdigit():
            value = int(character)
        elif character.isalpha():
            value = ord(character) - 55
        elif character == "*":
            value = 36
        elif character == "@":
            value = 37
        elif character == "#":
            value = 38
        else:
            raise ValidationError(f"{character!r} cannot appear in a CUSIP")
        if index % 2 == 1:
            value *= 2
        total += value // 10 + value % 10
    return (10 - total % 10) % 10


def validate_cusip(value: str) -> bool:
    candidate = value.strip().upper()
    if not _CUSIP_PATTERN.match(candidate):
        return False
    return cusip_check_digit(candidate[:8]) == int(candidate[8])


def sedol_check_digit(body: str) -> int:
    """Check digit for the first six characters of a SEDOL."""
    total = 0
    for weight, character in zip(_SEDOL_WEIGHTS, body.upper(), strict=False):
        value = int(character) if character.isdigit() else ord(character) - 55
        total += weight * value
    return (10 - total % 10) % 10


def validate_sedol(value: str) -> bool:
    candidate = value.strip().upper()
    if not _SEDOL_PATTERN.match(candidate):
        return False
    return sedol_check_digit(candidate[:6]) == int(candidate[6])


def figi_check_digit(body: str) -> int:
    """Check digit for the first 11 characters of a FIGI.

    FIGI does not use plain Luhn: each character is mapped (A=10 ... Z=35), the values
    in odd positions counting from the left are doubled, and then the *digits* of each
    value are summed. Verified against published FIGIs for Apple, Microsoft and Amazon.
    """
    total = 0
    for index, character in enumerate(body.upper()):
        value = int(character) if character.isdigit() else ord(character) - 55
        if index % 2 == 1:
            value *= 2
        total += sum(int(digit) for digit in str(value))
    return (10 - total % 10) % 10


def validate_figi(value: str) -> bool:
    candidate = value.strip().upper()
    if not _FIGI_PATTERN.match(candidate):
        return False
    return figi_check_digit(candidate[:11]) == int(candidate[11])


def lei_check_digits(body: str) -> int:
    """The two ISO 7064 MOD 97-10 check digits for the first 18 characters of an LEI."""
    expanded = _expand_alphanumerics(f"{body.upper()}00")
    return 98 - int(expanded) % 97


def validate_lei(value: str) -> bool:
    """An LEI is valid when the whole 20 characters, expanded, are 1 modulo 97."""
    candidate = value.strip().upper()
    if not _LEI_PATTERN.match(candidate):
        return False
    return int(_expand_alphanumerics(candidate)) % 97 == 1


def _identifier(name: str, validator: object, value: str) -> str:
    candidate = value.strip().upper()
    if not validator(candidate):  # type: ignore[operator]
        raise ValidationError(f"{candidate!r} is not a valid {name}")
    return candidate


@dataclass(frozen=True, slots=True)
class ISIN:
    value: str

    def __init__(self, value: str) -> None:
        object.__setattr__(self, "value", _identifier("ISIN", validate_isin, value))

    @property
    def country(self) -> str:
        """Issuing country prefix; ``XS`` marks an international security."""
        return self.value[:2]

    @property
    def national_number(self) -> str:
        return self.value[2:11]

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class CUSIP:
    value: str

    def __init__(self, value: str) -> None:
        object.__setattr__(self, "value", _identifier("CUSIP", validate_cusip, value))

    def to_isin(self, country: str = "US") -> ISIN:
        """CUSIPs embed in ISINs: country prefix, CUSIP, then a new check digit."""
        body = f"{country.upper()}{self.value}"
        return ISIN(f"{body}{isin_check_digit(body)}")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class SEDOL:
    value: str

    def __init__(self, value: str) -> None:
        object.__setattr__(self, "value", _identifier("SEDOL", validate_sedol, value))

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class FIGI:
    value: str

    def __init__(self, value: str) -> None:
        object.__setattr__(self, "value", _identifier("FIGI", validate_figi, value))

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class LEI:
    """A Legal Entity Identifier: who the obligor is, not what the instrument is."""

    value: str

    def __init__(self, value: str) -> None:
        object.__setattr__(self, "value", _identifier("LEI", validate_lei, value))

    @property
    def local_operating_unit(self) -> str:
        """The first four characters identify the issuing LOU."""
        return self.value[:4]

    @property
    def entity_part(self) -> str:
        return self.value[4:18]

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class Ticker:
    """An exchange ticker, which is only unique together with its listing venue."""

    symbol: str
    exchange: str | None = None

    def __init__(self, symbol: str, exchange: str | None = None) -> None:
        candidate = symbol.strip().upper()
        if not _TICKER_PATTERN.match(candidate):
            raise ValidationError(f"{symbol!r} is not a plausible ticker")
        object.__setattr__(self, "symbol", candidate)
        object.__setattr__(self, "exchange", exchange.strip().upper() if exchange else None)

    def __str__(self) -> str:
        return f"{self.symbol}.{self.exchange}" if self.exchange else self.symbol


_SCHEMES: tuple[tuple[str, object, int], ...] = (
    ("ISIN", validate_isin, 12),
    ("CUSIP", validate_cusip, 9),
    ("SEDOL", validate_sedol, 7),
    ("FIGI", validate_figi, 12),
    ("LEI", validate_lei, 20),
)


def identify(value: str) -> tuple[str, ...]:
    """Which schemes a string is a valid identifier for.

    A twelve-character string can be both an ISIN and a FIGI by shape, so the
    answer is a tuple rather than a single name. In practice the check digits
    disambiguate, but a system that assumes so is one bad feed away from a wrong
    instrument on a trade.
    """
    candidate = value.strip().upper()
    return tuple(
        name
        for name, validator, length in _SCHEMES
        if len(candidate) == length and validator(candidate)  # type: ignore[operator]
    )


def expected_check_digit(value: str) -> str:
    """What the check digit of a near-miss should have been, which is how a typo is explained."""
    candidate = value.strip().upper()
    try:
        if len(candidate) == 20:
            return f"{lei_check_digits(candidate[:18]):02d}"
        if len(candidate) == 12 and candidate.startswith("BBG"):
            return str(figi_check_digit(candidate[:11]))
        if len(candidate) == 12:
            return str(isin_check_digit(candidate[:11]))
        if len(candidate) == 9:
            return str(cusip_check_digit(candidate[:8]))
        if len(candidate) == 7:
            return str(sedol_check_digit(candidate[:6]))
    except (ValidationError, ValueError):  # a malformed body has no expected digit
        return ""
    return ""
