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


class CurrencyBalance(BaseModel):
    """Per-currency cash/net-liq balance with its local->base exchange rate.

    `cash_balance`/`net_liquidation` are in the row's own `currency`. Use the
    `base_*` computed fields whenever presenting a single-currency total — the
    raw amounts mix currencies and must not be summed directly.
    """

    currency: str
    cash_balance: float
    net_liquidation: float
    exchange_rate: float = 1.0   # local currency -> account base; 1.0 when already base

    @computed_field  # type: ignore[prop-decorator]
    @property
    def base_cash_balance(self) -> float:
        """Cash balance converted into the account base currency."""
        return self.cash_balance * self.exchange_rate

    @computed_field  # type: ignore[prop-decorator]
    @property
    def base_net_liquidation(self) -> float:
        """Net liquidation converted into the account base currency."""
        return self.net_liquidation * self.exchange_rate


class AccountOverview(BaseModel):
    """Account-level financial overview: equity, margin, liquidity and P&L.

    A richer companion to `Account` for the /ib-account-overview command. All monetary
    figures are in `base_currency`; per-currency detail lives in
    `currency_balances`. This model reads account state only — it never carries
    positions, orders, or any write path to IB.
    """

    account_id: str
    base_currency: str
    net_liquidation: float
    total_cash: float
    buying_power: float
    margin_used: float          # current margin requirement in use
    init_margin_req: float      # initial margin requirement
    maint_margin_req: float     # maintenance margin requirement
    available_funds: float
    excess_liquidity: float
    gross_position_value: float
    daily_pnl: float            # today's P&L (mark-to-market)
    unrealized_pnl: float
    realized_pnl: float
    currency_balances: list[CurrencyBalance]
    ts: datetime


class PositionView(BaseModel):
    """A single position enriched for a human-readable positions overview.

    Extends the raw `Position` shape with the descriptive attributes a holder
    checks first — instrument `name`, `industry`, listing `market`/`country` —
    plus derived read-outs (`side`, `unrealized_return`) and the portfolio
    `weight`. `market_value`/`unrealized_pnl` are in the position's own
    `currency`; `fx_rate` converts them into the account base currency. Use the
    `base_*` computed fields whenever ranking across positions — summing raw
    `market_value` mixes currencies. This model reads position state only; it
    carries no order path to IB.
    """

    account_id: str
    symbol: str
    name: str = ""              # instrument long name; "" when IB has none
    sec_type: str
    quantity: float
    avg_cost: float
    market_price: float
    market_value: float         # in the position's own currency
    unrealized_pnl: float       # in the position's own currency
    currency: str               # pricing/quote currency
    industry: str = ""          # IB contract-detail industry; "" when unknown
    market: str = ""            # listing exchange (IB primaryExchange); "" when unknown
    country: str = ""           # market -> country label; "" when not mapped
    fx_rate: float = 1.0        # local currency -> account base; 1.0 when already base
    weight: float = 0.0         # base_value / account net liquidation; set at build time

    @computed_field  # type: ignore[prop-decorator]
    @property
    def side(self) -> str:
        """LONG for a positive quantity, SHORT for negative, FLAT for zero."""
        if self.quantity > 0:
            return "LONG"
        if self.quantity < 0:
            return "SHORT"
        return "FLAT"

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

    @computed_field  # type: ignore[prop-decorator]
    @property
    def unrealized_return(self) -> float:
        """Unrealized P&L as a fraction of cost basis (0.0 when cost is zero).

        Cost basis is recovered as `market_value - unrealized_pnl`, so this
        stays correct for shorts (negative basis) without re-deriving it from
        quantity/avg_cost. Returns 0.0 rather than dividing by zero.
        """
        cost_basis = self.market_value - self.unrealized_pnl
        if cost_basis == 0:
            return 0.0
        return self.unrealized_pnl / abs(cost_basis)


class PositionsOverview(BaseModel):
    """Account-level positions overview: every position, enriched and rankable.

    Companion to `AccountOverview` for the /ib-positions-overview command. All
    ranking must use each position's `base_value` (base currency); `weight` is
    already normalized against `net_liquidation`. Reads position state only —
    no orders, no write path to IB.
    """

    account_id: str
    base_currency: str
    net_liquidation: float
    positions: list[PositionView]
    ts: datetime


class Snapshot(BaseModel):
    """Point-in-time snapshot combining account summary and positions."""

    account: Account
    positions: list[Position]
    ts: datetime
