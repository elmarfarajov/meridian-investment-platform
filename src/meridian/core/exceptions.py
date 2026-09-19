"""Exception hierarchy.

Every error the platform raises deliberately inherits from :class:`MeridianError`,
so a caller can catch "something in the platform rejected this" without also
swallowing genuine programming errors such as ``AttributeError``.
"""

from __future__ import annotations


class MeridianError(Exception):
    """Base class for every error raised by the platform."""


class ValidationError(MeridianError):
    """Input failed a domain rule (a malformed identifier, a negative quantity)."""


class CurrencyMismatchError(MeridianError):
    """An arithmetic or comparison operation mixed two currencies."""

    def __init__(self, left: str, right: str, operation: str) -> None:
        super().__init__(f"Cannot {operation} amounts in {left} and {right}; convert to a common currency first")
        self.left = left
        self.right = right
        self.operation = operation


class UnknownCurrencyError(MeridianError):
    """A currency code is not in the registry."""


class RateNotFoundError(MeridianError):
    """No direct, inverse or cross FX rate connects two currencies."""


class CalendarError(MeridianError):
    """A trading calendar was asked for a date it cannot answer."""


class RepositoryError(MeridianError):
    """Persistence refused an operation (missing entity, violated uniqueness)."""


class EntityNotFoundError(RepositoryError):
    """A lookup by identifier found nothing."""

    def __init__(self, entity: str, key: object) -> None:
        super().__init__(f"{entity} {key!r} was not found")
        self.entity = entity
        self.key = key
