"""Typed data models for the IB analyst pipeline.

These are the single source of truth for the shape of account, position,
execution, bar and dividend records. Storage and analysis layers depend
only on these types, never on raw ib_async objects.
"""
from __future__ import annotations
from datetime import date, datetime
from pydantic import BaseModel, computed_field


class Account(BaseModel):
    """Account-level summary snapshot at a point in time."""

    account_id: str
    base_currency: str
    net_liquidation: float
    total_cash: float
    buying_power: float
    ts: datetime


class Position(BaseModel):
    """A single held position with cost basis and mark-to-market values.

    `market_value`/`unrealized_pnl` are in the position's own `currency`.
    `fx_rate` converts that currency into the account base currency (1.0 when
    the position is already in base). Use `base_value`/`base_unrealized_pnl`
    whenever aggregating across positions — summing raw `market_value` mixes
    currencies and understates or overstates the book.
    """

    account_id: str
    symbol: str
    sec_type: str
    currency: str
    quantity: float
    avg_cost: float
    market_price: float
    market_value: float
    unrealized_pnl: float
    fx_rate: float = 1.0   # local currency -> account base; 1.0 when already base

    @computed_field  # type: ignore[prop-decorator]
    @property
    def base_value(self) -> float:
        """Market value converted into the account base currency."""
        return self.market_value * self.fx_rate

    @computed_field  # type: ignore[prop-decorator]
    @property
    def base_unrealized_pnl(self) -> float:
        """Unrealized P&L converted into the account base currency."""
        return self.unrealized_pnl * self.fx_rate


class Execution(BaseModel):
    """A single trade execution (fill) record."""

    exec_id: str
    symbol: str
    side: str
    quantity: float
    price: float
    commission: float
    ts: datetime


class DailyBar(BaseModel):
    """Daily OHLCV price bar for a symbol."""

    symbol: str
    date: date
    open: float
    high: float
    low: float
    close: float
    volume: float


class Dividend(BaseModel):
    """A dividend event with ex/pay dates and gross/tax amounts."""

    symbol: str
    ex_date: date
    pay_date: date | None
    gross: float
    tax: float
    currency: str


class Snapshot(BaseModel):
    """Point-in-time snapshot combining account summary and positions."""

    account: Account
    positions: list[Position]
    ts: datetime
