"""The factors of the model, and the groups a risk report shows them in.

The model is a fundamental one in the Barra tradition: a stock's return is
explained by characteristics that can be observed today - which industry it is
in, how large it is, how cheap, how it has been trading - rather than by
statistical factors extracted from past returns. Each factor is a return that
the market paid, day by day, to the stocks exposed to it.

* **World.** Every stock has exposure one: the return of the market as a whole.
* **Industries.** The eleven GICS sectors. Their returns are measured relative
  to the world factor, so they are constrained to sum to zero when weighted by
  market capitalisation; without the constraint, the world factor and the
  industries would be the same thing counted twice.
* **Styles.** Beta, size, value, momentum and quality: standardised
  characteristics, each a number of cross-sectional standard deviations from
  the capitalisation-weighted average stock.
* **Currencies.** For a dollar investor, a European stock's return is its local
  return plus the euro's. The currency factors are the currencies' own returns
  against the dollar, and the exposure is the share of the position held in
  that currency.
"""

from __future__ import annotations

from dataclasses import dataclass

WORLD = "World"

INDUSTRIES: tuple[str, ...] = (
    "Communication Services",
    "Consumer Discretionary",
    "Consumer Staples",
    "Energy",
    "Financials",
    "Health Care",
    "Industrials",
    "Information Technology",
    "Materials",
    "Real Estate",
    "Utilities",
)

STYLES: tuple[str, ...] = ("Beta", "Size", "Value", "Momentum", "Quality")

#: Currencies other than the base currency, each a factor against it.
CURRENCIES: tuple[str, ...] = ("EUR", "GBP", "CHF", "JPY")
BASE_CURRENCY = "USD"

#: Region of each currency's market, for reporting.
REGION_OF_CURRENCY = {
    "USD": "North America",
    "EUR": "Europe ex UK",
    "GBP": "United Kingdom",
    "CHF": "Switzerland",
    "JPY": "Japan",
}

GROUPS: tuple[str, ...] = ("World", "Industry", "Style", "Currency")


def currency_factor(code: str) -> str:
    return f"FX {code}"


@dataclass(frozen=True)
class FactorSet:
    """An ordered set of factors; the order fixes the columns of every exposure matrix."""

    names: tuple[str, ...]

    @classmethod
    def standard(cls) -> FactorSet:
        return cls((WORLD, *INDUSTRIES, *STYLES, *(currency_factor(code) for code in CURRENCIES)))

    def __len__(self) -> int:
        return len(self.names)

    def index(self, name: str) -> int:
        return self.names.index(name)

    def indices(self, group: str) -> list[int]:
        return [position for position, name in enumerate(self.names) if group_of(name) == group]

    @property
    def local(self) -> tuple[str, ...]:
        """The factors estimated by regression on local returns: everything but the currencies."""
        return tuple(name for name in self.names if group_of(name) != "Currency")


def group_of(name: str) -> str:
    if name == WORLD:
        return "World"
    if name in INDUSTRIES:
        return "Industry"
    if name in STYLES:
        return "Style"
    if name.startswith("FX "):
        return "Currency"
    raise KeyError(name)
