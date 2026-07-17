# skills/ib-common/tests/test_schema.py
from pathlib import Path
from ib_common.schema import Snapshot, Position

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
