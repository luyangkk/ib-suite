from datetime import date, datetime, timezone
from pathlib import Path

from ib_common.schema import FlexTrade, Position, Snapshot, TradeHistoryReport, TradeHistorySummary

FIX = Path(__file__).parent / "fixtures"

def test_snapshot_round_trips_from_fixture():
    raw = (FIX / "snapshot_sample.json").read_text(encoding="utf-8")
    snap = Snapshot.model_validate_json(raw)
    assert snap.account.base_currency == "USD"
    assert len(snap.positions) == 2
    # round-trip must be lossless
    reparsed = Snapshot.model_validate_json(snap.model_dump_json())
    assert reparsed == snap

def test_position_market_value_types_are_floats():
    p = Position(account_id="U1", symbol="AAPL", sec_type="STK", currency="USD",
                 quantity=10, avg_cost=100.0, market_price=190.0,
                 market_value=1900.0, unrealized_pnl=900.0)
    assert isinstance(p.market_value, float)


def test_position_fx_rate_defaults_to_one():
    """Positions in the base currency need no conversion (fx_rate == 1.0)."""
    p = Position(account_id="U1", symbol="AAPL", sec_type="STK", currency="USD",
                 quantity=10, avg_cost=100.0, market_price=190.0,
                 market_value=1900.0, unrealized_pnl=900.0)
    assert p.fx_rate == 1.0
    assert p.base_value == 1900.0
    assert p.base_unrealized_pnl == 900.0


def test_position_base_value_applies_fx_rate():
    """A non-base position converts market_value and P&L into base currency."""
    p = Position(account_id="U1", symbol="D05", sec_type="STK", currency="SGD",
                 quantity=100, avg_cost=63.48, market_price=72.05,
                 market_value=7205.0, unrealized_pnl=857.0, fx_rate=0.775109)
    assert p.base_value == 7205.0 * 0.775109
    assert p.base_unrealized_pnl == 857.0 * 0.775109


def test_flex_trade_exposes_original_and_base_currency_amounts():
    """Trade-history rows retain local amounts and derive base amounts from Flex FX."""
    row = FlexTrade(
        exec_id="T-2",
        ts=datetime(2026, 7, 15, 9, 30, tzinfo=timezone.utc),
        symbol="D05",
        side="SELL",
        quantity=100.0,
        price=40.0,
        commission=4.0,
        currency="SGD",
        commission_currency="SGD",
        order_type="LMT",
        exchange="SGX",
        open_close="C",
        realized_pnl=200.0,
        fx_rate_to_base=0.75,
    )

    assert row.notional == 4000.0
    assert row.commission_currency == "SGD"
    assert row.base_notional == 3000.0
    assert row.base_commission == 3.0
    assert row.base_realized_pnl == 150.0

    report = TradeHistoryReport(
        start_date=date(2026, 7, 9),
        end_date=date(2026, 7, 15),
        base_currency="USD",
        trades=[row],
        summary=TradeHistorySummary(
            total_trades=1, buy_count=0, sell_count=1, total_notional=3000.0,
            total_commission=3.0, profitable_trades=1, losing_trades=0,
            win_rate=1.0, average_profit=150.0, average_loss=None,
            profit_loss_ratio=None,
        ),
    )
    assert report.model_dump(mode="json")["trades"][0]["base_realized_pnl"] == 150.0
