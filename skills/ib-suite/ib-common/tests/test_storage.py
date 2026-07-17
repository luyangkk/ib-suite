from pathlib import Path
from datetime import datetime, date, timezone
from ib_common.schema import Snapshot, Account, Position, DailyBar
from ib_common.storage import write_snapshot, append_timeseries, read_timeseries


def _snap():
    acct = Account(account_id="U1", base_currency="USD", net_liquidation=100.0,
                   total_cash=10.0, buying_power=20.0, ts=datetime(2026, 7, 15, tzinfo=timezone.utc))
    pos = Position(account_id="U1", symbol="AAPL", sec_type="STK", currency="USD",
                   quantity=1, avg_cost=1.0, market_price=2.0, market_value=2.0, unrealized_pnl=1.0)
    return Snapshot(account=acct, positions=[pos], ts=datetime(2026, 7, 15, tzinfo=timezone.utc))


def test_write_snapshot_creates_file(tmp_path):
    p = write_snapshot(_snap(), tmp_path)
    assert p.exists()
    assert "U1" in str(p)


def test_append_timeseries_dedupes(tmp_path):
    bar = DailyBar(symbol="AAPL", date=date(2026, 7, 15), open=1, high=2, low=0.5, close=1.5, volume=1000)
    append_timeseries([bar], tmp_path, "daily_bars")
    append_timeseries([bar], tmp_path, "daily_bars")   # duplicate append
    df = read_timeseries(tmp_path, "daily_bars")
    assert len(df) == 1                                 # dedup on all columns


def test_read_missing_returns_empty(tmp_path):
    df = read_timeseries(tmp_path, "nope")
    assert df.empty
