# skills/ib-gateway/tests/test_ib_sync.py
from pathlib import Path
from datetime import datetime, timezone
import json, importlib.util, math

SPEC = Path(__file__).parent.parent / "scripts" / "ib_sync.py"
spec = importlib.util.spec_from_file_location("ib_sync", SPEC)
ib_sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ib_sync)

FIX = Path(__file__).parent / "fixtures"


def test_build_snapshot_from_raw():
    raw = json.loads((FIX / "ib_raw_account_sample.json").read_text())
    snap = ib_sync.build_snapshot(raw, datetime(2026, 7, 15, tzinfo=timezone.utc))
    assert snap.account.base_currency == "USD"
    assert snap.account.account_id == "U0000000"
    assert len(snap.positions) == 2


def test_sync_writes_snapshot_and_timeseries(tmp_path):
    raw = json.loads((FIX / "ib_raw_account_sample.json").read_text())

    # config pointing storage at tmp
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(f"storage:\n  root: {tmp_path}\ndata:\n  base_currency: USD\n")

    class FakeClient:
        """Stand-in for a read-only IB Gateway session."""
        def fetch_raw(self): return raw
        def disconnect(self): pass

    out = ib_sync.sync(str(cfg_path),
                       client_factory=lambda cfg: FakeClient(),
                       now=lambda: datetime(2026, 7, 15, tzinfo=timezone.utc))
    assert Path(out["snapshot"]).exists()
    assert Path(out["timeseries"]).exists()


def test_resolve_market_price_prefers_live_quote():
    """A finite, positive market quote wins over the cost basis."""
    assert ib_sync._resolve_market_price(live_price=190.0, avg_cost=150.0) == 190.0


def test_resolve_market_price_falls_back_when_quote_missing():
    """No market-data subscription => IB returns NaN/None => fall back to avg_cost."""
    assert ib_sync._resolve_market_price(live_price=math.nan, avg_cost=150.0) == 150.0
    assert ib_sync._resolve_market_price(live_price=None, avg_cost=150.0) == 150.0
    # a non-positive quote is not a real trade price; also fall back
    assert ib_sync._resolve_market_price(live_price=0.0, avg_cost=150.0) == 150.0


def test_resolve_market_price_uses_close_when_no_live_trade():
    """Off-hours/delayed data often has only the prior close; use it over cost."""
    # last/bid/ask unavailable but a valid prior close exists -> use close
    assert ib_sync._resolve_market_price(
        live_price=0.0, avg_cost=150.0, close_price=353.81) == 353.81
    assert ib_sync._resolve_market_price(
        live_price=math.nan, avg_cost=150.0, close_price=353.81) == 353.81
    # a live trade still beats close
    assert ib_sync._resolve_market_price(
        live_price=190.0, avg_cost=150.0, close_price=353.81) == 190.0
    # neither live nor close -> cost basis
    assert ib_sync._resolve_market_price(
        live_price=None, avg_cost=150.0, close_price=math.nan) == 150.0


def test_market_data_type_code_maps_config_to_ib_code():
    """Config string -> IB reqMarketDataType code (1 live / 2 frozen / 3 delayed / 4 delayed-frozen)."""
    assert ib_sync._market_data_type_code("realtime") == 1
    assert ib_sync._market_data_type_code("frozen") == 2
    assert ib_sync._market_data_type_code("delayed") == 3
    assert ib_sync._market_data_type_code("delayed_frozen") == 4


def test_market_data_type_code_rejects_unknown():
    """An unknown mode is a config error, not a silent fallback."""
    import pytest
    with pytest.raises(ValueError):
        ib_sync._market_data_type_code("bogus")


class _AV:
    """Minimal stand-in for an ib_async AccountValue row."""
    def __init__(self, tag, currency, value):
        self.tag, self.currency, self.value = tag, currency, value


def test_exchange_rates_reads_ledger_exchange_rate():
    """IB publishes a per-currency $LEDGER-ExchangeRate (local -> base); use it verbatim."""
    avs = [
        _AV("$LEDGER-ExchangeRate", "SGD", "0.775109"),
        _AV("$LEDGER-ExchangeRate", "USD", "1.00"),
        _AV("$LEDGER-StockMarketValue", "SGD", "7204.92"),   # ignored
        _AV("$LEDGER-ExchangeRate", "BASE", "1.00"),         # summary row, ignored
    ]
    rates = ib_sync._exchange_rates(avs)
    assert rates["SGD"] == 0.775109
    assert rates["USD"] == 1.0
    assert "BASE" not in rates


def test_build_snapshot_applies_position_fx_rate():
    """A raw position carrying fx_rate converts market_value/pnl into base currency."""
    raw = {
        "account": {"account_id": "U1", "base_currency": "USD",
                    "net_liquidation": 0.0, "total_cash": 0.0, "buying_power": 0.0},
        "positions": [
            {"symbol": "D05", "sec_type": "STK", "currency": "SGD", "quantity": 100,
             "avg_cost": 63.478, "market_price": 72.05, "fx_rate": 0.775109},
        ],
    }
    snap = ib_sync.build_snapshot(raw, datetime(2026, 7, 17, tzinfo=timezone.utc))
    pos = snap.positions[0]
    assert pos.fx_rate == 0.775109
    # 100 * 72.05 SGD, converted to USD
    assert pos.base_value == 100 * 72.05 * 0.775109


def test_build_snapshot_defaults_fx_rate_to_one():
    """Legacy raw positions without fx_rate stay in base currency (rate 1.0)."""
    raw = json.loads((FIX / "ib_raw_account_sample.json").read_text())
    snap = ib_sync.build_snapshot(raw, datetime(2026, 7, 15, tzinfo=timezone.utc))
    assert all(p.fx_rate == 1.0 for p in snap.positions)
