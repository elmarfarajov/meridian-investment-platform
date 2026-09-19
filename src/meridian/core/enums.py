"""Enumerations shared across the platform."""

from __future__ import annotations

from enum import Enum


class AssetClass(str, Enum):
    EQUITY = "equity"
    FIXED_INCOME = "fixed_income"
    CASH = "cash"
    ALTERNATIVE = "alternative"
    DERIVATIVE = "derivative"
    MULTI_ASSET = "multi_asset"


class InstrumentType(str, Enum):
    COMMON_STOCK = "common_stock"
    PREFERRED_STOCK = "preferred_stock"
    ETF = "etf"
    MUTUAL_FUND = "mutual_fund"
    GOVERNMENT_BOND = "government_bond"
    CORPORATE_BOND = "corporate_bond"
    MONEY_MARKET = "money_market"
    CASH = "cash"
    EQUITY_OPTION = "equity_option"
    FUTURE = "future"
    PRIVATE_FUND = "private_fund"

    @property
    def asset_class(self) -> AssetClass:
        return _INSTRUMENT_ASSET_CLASS[self]


_INSTRUMENT_ASSET_CLASS: dict[InstrumentType, AssetClass] = {
    InstrumentType.COMMON_STOCK: AssetClass.EQUITY,
    InstrumentType.PREFERRED_STOCK: AssetClass.EQUITY,
    InstrumentType.ETF: AssetClass.MULTI_ASSET,
    InstrumentType.MUTUAL_FUND: AssetClass.MULTI_ASSET,
    InstrumentType.GOVERNMENT_BOND: AssetClass.FIXED_INCOME,
    InstrumentType.CORPORATE_BOND: AssetClass.FIXED_INCOME,
    InstrumentType.MONEY_MARKET: AssetClass.CASH,
    InstrumentType.CASH: AssetClass.CASH,
    InstrumentType.EQUITY_OPTION: AssetClass.DERIVATIVE,
    InstrumentType.FUTURE: AssetClass.DERIVATIVE,
    InstrumentType.PRIVATE_FUND: AssetClass.ALTERNATIVE,
}


class SecurityStatus(str, Enum):
    ACTIVE = "active"
    DELISTED = "delisted"
    MATURED = "matured"
    SUSPENDED = "suspended"


class TransactionType(str, Enum):
    BUY = "buy"
    SELL = "sell"
    DIVIDEND = "dividend"
    INTEREST = "interest"
    FEE = "fee"
    TAX = "tax"
    DEPOSIT = "deposit"
    WITHDRAWAL = "withdrawal"
    TRANSFER_IN = "transfer_in"
    TRANSFER_OUT = "transfer_out"
    SPLIT = "split"
    SPIN_OFF = "spin_off"
    FX = "fx"

    @property
    def affects_position(self) -> bool:
        return self in {
            TransactionType.BUY,
            TransactionType.SELL,
            TransactionType.TRANSFER_IN,
            TransactionType.TRANSFER_OUT,
            TransactionType.SPLIT,
            TransactionType.SPIN_OFF,
        }

    @property
    def is_income(self) -> bool:
        return self in {TransactionType.DIVIDEND, TransactionType.INTEREST}


class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"

    @property
    def sign(self) -> int:
        return 1 if self is Side.BUY else -1


class LotSelectionMethod(str, Enum):
    """Which tax lots are relieved when a position is sold."""

    FIFO = "fifo"
    LIFO = "lifo"
    HIFO = "hifo"  # highest cost first: defers gains
    AVERAGE_COST = "average_cost"
    SPECIFIC_LOT = "specific_lot"


class AccountType(str, Enum):
    TAXABLE = "taxable"
    IRA = "ira"
    ROTH_IRA = "roth_ira"
    PENSION = "pension"
    TRUST = "trust"
    CORPORATE = "corporate"
    INSTITUTIONAL = "institutional"

    @property
    def is_tax_deferred(self) -> bool:
        return self in {AccountType.IRA, AccountType.ROTH_IRA, AccountType.PENSION}


class Frequency(str, Enum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    SEMI_ANNUAL = "semi_annual"
    ANNUAL = "annual"

    @property
    def periods_per_year(self) -> int:
        return {
            Frequency.DAILY: 252,
            Frequency.WEEKLY: 52,
            Frequency.MONTHLY: 12,
            Frequency.QUARTERLY: 4,
            Frequency.SEMI_ANNUAL: 2,
            Frequency.ANNUAL: 1,
        }[self]


class PriceType(str, Enum):
    CLOSE = "close"
    ADJUSTED_CLOSE = "adjusted_close"
    BID = "bid"
    ASK = "ask"
    MID = "mid"
    NAV = "nav"
    EVALUATED = "evaluated"
