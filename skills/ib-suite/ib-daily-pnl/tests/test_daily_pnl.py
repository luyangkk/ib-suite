# skills/ib-suite/ib-daily-pnl/tests/test_daily_pnl.py
"""Tests for the /ib-daily-pnl entrypoint.

Mirrors ib-positions-overview's style: load the script by path, exercise the
pure build_daily_pnl() plus the deterministic ranking/attribution helpers, then
the offline orchestration via an injected FakeClient. No network/IB access is
used and the live client is never constructed here.
"""
from pathlib import Path
from datetime import datetime, timezone
import json, importlib.util

SPEC = Path(__file__).parent.parent / "scripts" / "daily_pnl.py"
spec = importlib.util.spec_from_file_location("daily_pnl", SPEC)
daily_pnl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(daily_pnl)

FIX = Path(__file__).parent / "fixtures"
TS = datetime(2026, 7, 17, tzinfo=timezone.utc)


def _raw():
    return json.loads((FIX / "ib_raw_daily_pnl_sample.json").read_text())


def test_build_maps_account_totals_and_positions():
    """Account daily/realized/unrealized totals and every position survive mapping."""
    ov = daily_pnl.build_daily_pnl(_raw(), TS)
    assert ov.account_id == "U0000000"
    assert ov.base_currency == "USD"
    assert ov.daily_pnl == 1650.0
    assert ov.realized_pnl == 500.0
    assert ov.unrealized_pnl == 1355.0
    assert len(ov.positions) == 7

    nvda = next(p for p in ov.positions if p.symbol == "NVDA")
    assert nvda.name == "NVDA 20260116 180 CALL"
    assert nvda.sec_type == "OPT"
    assert nvda.daily_pnl == 2500.0
    assert nvda.realized_pnl == 500.0
    assert nvda.currency == "USD"


def test_asset_class_is_derived_from_sec_type_and_stock_type():
    """STK+ETF -> ETF; STK+common -> Stock; OPT -> Option; CASH -> Forex."""
    ov = daily_pnl.build_daily_pnl(_raw(), TS)
    by_sym = {p.symbol: p for p in ov.positions}
    assert by_sym["AAPL"].asset_class == "Stock"
    assert by_sym["SPY"].asset_class == "ETF"
    assert by_sym["NVDA"].asset_class == "Option"
    assert by_sym["TSLA"].asset_class == "Option"
    assert by_sym["EUR"].asset_class == "Forex"
    assert by_sym["D05"].asset_class == "Stock"


def test_ranking_by_profit_contrib_desc():
    """Winners first: daily P&L high to low."""
    ov = daily_pnl.build_daily_pnl(_raw(), TS)
    order = [p.symbol for p in daily_pnl.by_profit_contrib(ov.positions)]
    assert order == ["NVDA", "AAPL", "SPY", "EUR", "D05", "MSFT", "TSLA"]


def test_ranking_by_loss_contrib_desc():
    """Losers first: daily P&L most negative first."""
    ov = daily_pnl.build_daily_pnl(_raw(), TS)
    order = [p.symbol for p in daily_pnl.by_loss_contrib(ov.positions)]
    assert order == ["TSLA", "MSFT", "D05", "EUR", "SPY", "AAPL", "NVDA"]


def test_by_asset_class_sums_daily_pnl():
    """Asset-class breakdown sums per-position daily P&L to the account total."""
    ov = daily_pnl.build_daily_pnl(_raw(), TS)
    ac = daily_pnl.by_asset_class(ov.positions)
    assert ac["Stock"] == 200.0        # 1200 - 800 - 200
    assert ac["ETF"] == 300.0
    assert ac["Option"] == 1000.0      # 2500 - 1500
    assert ac["Forex"] == 150.0
    assert abs(sum(ac.values()) - 1650.0) < 1e-9


def test_by_currency_sums_daily_pnl():
    """Currency breakdown groups per-position daily P&L by trading currency."""
    ov = daily_pnl.build_daily_pnl(_raw(), TS)
    cc = daily_pnl.by_currency(ov.positions)
    assert cc["USD"] == 1850.0
    assert cc["SGD"] == -200.0
    assert abs(sum(cc.values()) - 1650.0) < 1e-9


def test_top_driver_is_largest_absolute_daily_pnl():
    """The single position moving today's P&L the most (by absolute daily P&L)."""
    ov = daily_pnl.build_daily_pnl(_raw(), TS)
    top = daily_pnl.top_pnl_driver(ov.positions)
    assert top.symbol == "NVDA"
    assert top.daily_pnl == 2500.0


def test_orchestration_uses_injected_client_and_emits_full_contract():
    """daily_pnl() runs fully offline and returns a parseable dict carrying the
    totals, rankings, asset-class/currency attribution, top driver, and the
    honest attribution note (no fabricated price/vol/theta/fx split)."""
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
        out = daily_pnl.daily_pnl(
            cfg_path,
            client_factory=lambda cfg: FakeClient(),
            now=lambda: TS,
        )

    assert FakeClient.disconnected is True             # connection always closed
    assert out["account_id"] == "U0000000"
    assert out["daily_pnl"] == 1650.0
    assert out["realized_pnl"] == 500.0
    assert out["unrealized_pnl"] == 1355.0
    assert len(out["positions"]) == 7
    assert out["rankings"]["by_profit_contrib"][0] == "NVDA"
    assert out["rankings"]["by_loss_contrib"][0] == "TSLA"
    assert out["attribution"]["by_asset_class"]["Option"] == 1000.0
    assert out["attribution"]["by_currency"]["SGD"] == -200.0
    assert out["top_driver"]["symbol"] == "NVDA"
    # share of gross daily P&L = 2500 / 6650
    assert abs(out["top_driver"]["share_of_gross"] - (2500.0 / 6650.0)) < 1e-6
    # honest limitation is a structural part of the contract, not a prose afterthought
    note = out["attribution"]["note"].lower()
    assert "theta" in note or "time" in note
    assert "volatility" in note or "greeks" in note


def test_ib_max_value_sentinel_is_treated_as_zero():
    """IB reports an unset figure as Double.MAX_VALUE (~1.7977e308), not None.

    A name with no closing trade today has an undefined realized P&L; passing
    the sentinel through would fabricate a nonsense number. It must clean to 0.0
    and never leak into any total or ranking.
    """
    raw = _raw()
    raw["positions"][0]["realized_pnl"] = 1.7976931348623157e+308  # AAPL: no close today
    raw["account"]["realized_pnl"] = 1.7976931348623157e+308
    ov = daily_pnl.build_daily_pnl(raw, TS)

    aapl = next(p for p in ov.positions if p.symbol == "AAPL")
    assert aapl.realized_pnl == 0.0            # sentinel cleaned, not passed through
    assert aapl.daily_pnl == 1200.0           # real daily figure untouched
    assert ov.realized_pnl == 0.0             # account sentinel cleaned too


def test_module_never_imports_order_apis():
    """Read-only guarantee: the module source must not touch any order path."""
    src = SPEC.read_text()
    for forbidden in ("placeOrder", "cancelOrder", "reqGlobalCancel", "bracketOrder"):
        assert forbidden not in src, f"order API {forbidden!r} must never appear"
