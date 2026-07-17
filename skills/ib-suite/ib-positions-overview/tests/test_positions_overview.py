# skills/ib-suite/ib-positions-overview/tests/test_positions_overview.py
"""Tests for the /ib-positions-overview entrypoint.

Mirrors ib-account-overview's style: load the script by path, exercise the pure
build_positions() + deterministic ranking helpers, then the offline
orchestration via an injected FakeClient. No network/IB access is used and the
live client is never constructed here.
"""
from pathlib import Path
from datetime import datetime, timezone
import json, importlib.util

SPEC = Path(__file__).parent.parent / "scripts" / "positions_overview.py"
spec = importlib.util.spec_from_file_location("positions_overview", SPEC)
positions_overview = importlib.util.module_from_spec(spec)
spec.loader.exec_module(positions_overview)

FIX = Path(__file__).parent / "fixtures"
TS = datetime(2026, 7, 17, tzinfo=timezone.utc)


def _raw():
    return json.loads((FIX / "ib_raw_positions_sample.json").read_text())


def test_build_positions_maps_all_requested_fields():
    """Every one of the 14 requested per-position fields survives the mapping."""
    ov = positions_overview.build_positions(_raw(), TS)
    assert ov.account_id == "U0000000"
    assert ov.base_currency == "USD"
    assert ov.net_liquidation == 100000.0
    assert len(ov.positions) == 5

    aapl = next(p for p in ov.positions if p.symbol == "AAPL")
    assert aapl.name == "APPLE INC"          # 2. name
    assert aapl.sec_type == "STK"            # 3. asset type
    assert aapl.quantity == 100              # 4. quantity
    assert aapl.side == "LONG"               # 5. long/short
    assert aapl.avg_cost == 150.0            # 6. average cost
    assert aapl.market_price == 190.0        # 7. current price
    assert aapl.market_value == 19000.0      # 8. current market value
    assert aapl.unrealized_pnl == 4000.0     # 9. unrealized P&L
    assert aapl.industry == "Technology"     # 12. industry
    assert aapl.market == "NASDAQ"           # 13. market
    assert aapl.country == "United States"   # 13. country (mapped from market)
    assert aapl.currency == "USD"            # 14. pricing currency


def test_unrealized_return_and_weight_are_derived():
    """10. return = pnl/|cost basis|; 11. weight = base_value / net liquidation."""
    ov = positions_overview.build_positions(_raw(), TS)
    aapl = next(p for p in ov.positions if p.symbol == "AAPL")
    # cost basis = market_value - pnl = 15000; 4000/15000
    assert abs(aapl.unrealized_return - (4000.0 / 15000.0)) < 1e-9
    assert abs(aapl.weight - 0.19) < 1e-9    # 19000 / 100000

    # a profitable short: positive return, negative weight
    tsla = next(p for p in ov.positions if p.symbol == "TSLA")
    assert tsla.side == "SHORT"
    assert abs(tsla.unrealized_return - (500.0 / 2500.0)) < 1e-9
    assert abs(tsla.weight - (-0.02)) < 1e-9


def test_foreign_currency_position_converts_to_base():
    """A SGD position's base_value/weight use its fx_rate, not raw local value."""
    ov = positions_overview.build_positions(_raw(), TS)
    d05 = next(p for p in ov.positions if p.symbol == "D05")
    assert d05.currency == "SGD"
    assert d05.country == "Singapore"
    assert abs(d05.base_value - 7205.0 * 0.7747392) < 1e-6
    assert abs(d05.weight - (7205.0 * 0.7747392) / 100000.0) < 1e-9


def test_ranking_by_market_value_desc():
    """Sort view 1: by base-currency market value, high to low."""
    ov = positions_overview.build_positions(_raw(), TS)
    order = [p.symbol for p in positions_overview.by_market_value(ov.positions)]
    assert order == ["MSFT", "AAPL", "D05", "BABA", "TSLA"]


def test_ranking_by_profit_desc():
    """Sort view 2: by base-currency unrealized P&L, profit high to low."""
    ov = positions_overview.build_positions(_raw(), TS)
    order = [p.symbol for p in positions_overview.by_profit(ov.positions)]
    assert order == ["AAPL", "BABA", "TSLA", "D05", "MSFT"]


def test_ranking_by_loss_desc():
    """Sort view 3: by loss amount high to low (most negative P&L first)."""
    ov = positions_overview.build_positions(_raw(), TS)
    order = [p.symbol for p in positions_overview.by_loss(ov.positions)]
    assert order == ["MSFT", "D05", "TSLA", "BABA", "AAPL"]


def test_ranking_by_weight_desc():
    """Sort view 4: by account-weight, high to low."""
    ov = positions_overview.build_positions(_raw(), TS)
    order = [p.symbol for p in positions_overview.by_weight(ov.positions)]
    assert order == ["MSFT", "AAPL", "D05", "BABA", "TSLA"]


def test_top_concentration_is_largest_absolute_weight():
    """Concentration call-out: the single position with the largest |weight|."""
    ov = positions_overview.build_positions(_raw(), TS)
    top = positions_overview.top_concentration(ov.positions)
    assert top.symbol == "MSFT"
    assert abs(top.weight - 0.21) < 1e-9


def test_orchestration_uses_injected_client_and_emits_rankings():
    """positions_overview() runs fully offline and returns a parseable dict
    carrying the enriched positions, all four rankings, and top concentration."""
    raw = _raw()

    class FakeClient:
        """Stand-in for a read-only IB Gateway session."""
        disconnected = False
        def fetch_raw(self):
            return raw
        def disconnect(self):
            FakeClient.disconnected = True

    import tempfile, os
    with tempfile.TemporaryDirectory() as d:
        cfg_path = os.path.join(d, "config.yaml")
        Path(cfg_path).write_text("data:\n  base_currency: USD\n")
        out = positions_overview.positions_overview(
            cfg_path,
            client_factory=lambda cfg: FakeClient(),
            now=lambda: TS,
        )

    assert FakeClient.disconnected is True            # connection always closed
    assert out["account_id"] == "U0000000"
    assert out["net_liquidation"] == 100000.0
    assert len(out["positions"]) == 5
    assert out["rankings"]["by_market_value"] == ["MSFT", "AAPL", "D05", "BABA", "TSLA"]
    assert out["rankings"]["by_profit"] == ["AAPL", "BABA", "TSLA", "D05", "MSFT"]
    assert out["rankings"]["by_loss"] == ["MSFT", "D05", "TSLA", "BABA", "AAPL"]
    assert out["rankings"]["by_weight"] == ["MSFT", "AAPL", "D05", "BABA", "TSLA"]
    assert out["top_concentration"]["symbol"] == "MSFT"


def test_module_never_imports_order_apis():
    """Read-only guarantee: the module source must not touch any order path."""
    src = SPEC.read_text()
    for forbidden in ("placeOrder", "cancelOrder", "reqGlobalCancel", "bracketOrder"):
        assert forbidden not in src, f"order API {forbidden!r} must never appear"
