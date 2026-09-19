"""Decimal helpers.

Every monetary amount, quantity and price in the platform is a
:class:`decimal.Decimal`. Floating point is fine for analytics - a tracking error
of 4.13% does not care about the fifteenth digit - but it is not acceptable for
accounting, where 0.1 + 0.2 must equal 0.3 and a position must reconcile to the
cent across thousands of transactions.

The rounding default is banker's rounding (``ROUND_HALF_EVEN``), which is what
accounting systems and the IEEE standard use because it does not bias a long run
of roundings upwards.
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal, InvalidOperation, localcontext
from typing import Union

from .exceptions import ValidationError

Numeric = Union[int, float, str, Decimal]

MONEY_PRECISION = Decimal("0.01")
QUANTITY_PRECISION = Decimal("0.00000001")
RATE_PRECISION = Decimal("0.00000001")
PERCENT_PRECISION = Decimal("0.0001")


def to_decimal(value: Numeric, *, field: str = "value") -> Decimal:
    """Convert to :class:`Decimal` without inheriting binary floating point noise.

    Floats are routed through ``repr`` so that ``0.1`` becomes ``Decimal("0.1")``
    rather than ``Decimal("0.1000000000000000055511151231257827021181583404541015625")``.
    """
    if isinstance(value, Decimal):
        decimal_value = value
    elif isinstance(value, bool):  # bool is an int subclass; almost always a bug here
        raise ValidationError(f"{field} must be numeric, got a boolean")
    elif isinstance(value, int):
        decimal_value = Decimal(value)
    elif isinstance(value, float):
        decimal_value = Decimal(repr(value))
    elif isinstance(value, str):
        try:
            decimal_value = Decimal(value.strip().replace(",", ""))
        except InvalidOperation as exc:
            raise ValidationError(f"{field} {value!r} is not a valid decimal") from exc
    else:  # pragma: no cover - defensive
        raise ValidationError(f"{field} must be numeric, got {type(value).__name__}")

    if not decimal_value.is_finite():
        raise ValidationError(f"{field} must be finite, got {decimal_value}")
    return decimal_value


def quantize(value: Numeric, precision: Decimal = MONEY_PRECISION, *, field: str = "value") -> Decimal:
    """Round to a fixed number of places using banker's rounding."""
    with localcontext() as context:
        context.prec = 38
        return to_decimal(value, field=field).quantize(precision)


def safe_divide(numerator: Numeric, denominator: Numeric, *, default: Decimal | None = None) -> Decimal:
    """Divide, returning ``default`` when the denominator is zero.

    Ratios are everywhere in portfolio analytics (weights, returns, coverage) and a
    zero denominator is usually "no position" rather than a programming error.
    """
    left = to_decimal(numerator, field="numerator")
    right = to_decimal(denominator, field="denominator")
    if right == 0:
        if default is None:
            raise ValidationError("Division by zero and no default supplied")
        return default
    with localcontext() as context:
        context.prec = 38
        return left / right


def decimal_sum(values: Iterable[Numeric]) -> Decimal:
    """Sum an iterable exactly, starting from ``Decimal(0)`` rather than ``int``."""
    total = Decimal(0)
    for value in values:
        total += to_decimal(value)
    return total


def is_zero(value: Numeric, tolerance: Decimal = Decimal("1e-12")) -> bool:
    """True when a value is zero within a tolerance, for comparing computed residuals."""
    return abs(to_decimal(value)) <= tolerance
